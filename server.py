#!/usr/bin/env python3
import collections
import json
import logging
import mimetypes
import os
import posixpath
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import go_ultra
from go_ultra import GoUltraClient

APP_DIR = Path(__file__).resolve().parent
DIST_DIR = APP_DIR / "static" / "dist"
UI_PORT = int(os.environ.get("GOULTRA_UI_PORT", "8765"))
CAMERA_HTTP_PORT = int(os.environ.get("GOULTRA_HTTP_PORT", "80"))
DEFAULT_DEST = str(Path.home() / "Downloads" / "GoUltra")
HTTP_TIMEOUT = 25

MEDIA_TYPES = {
    ".mp4": "video/mp4", ".lrv": "video/mp4", ".mov": "video/quicktime",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".insp": "image/jpeg",
    ".dng": "application/octet-stream",
}


class RingLogHandler(logging.Handler):
    def __init__(self, capacity=2000):
        super().__init__()
        self.records = collections.deque(maxlen=capacity)
        self.counter = 0
        self.lock_ = threading.Lock()

    def emit(self, record):
        line = self.format(record)
        with self.lock_:
            self.counter += 1
            self.records.append((self.counter, line))

    def since(self, cursor):
        with self.lock_:
            return [(n, line) for n, line in self.records if n > cursor]


ring = RingLogHandler()
ring.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
file_handler = logging.FileHandler(APP_DIR / "go-ultra.log")
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
logging.basicConfig(level=logging.DEBUG, handlers=[ring, file_handler])
logging.getLogger().addHandler(logging.StreamHandler())
log = logging.getLogger("server")

client = GoUltraClient()

state_lock = threading.Lock()
sizes = {}
resolved = {}
size_scan_running = False

dl_lock = threading.Lock()
downloads = {
    "active": False, "files_done": 0, "files_total": 0,
    "bytes_done": 0, "bytes_total": None, "speed": 0, "eta": None,
    "current": None, "dest": None, "done": [], "errors": [],
}


def http_url_candidates(uri):
    path = uri if uri.startswith("/") else "/" + uri
    candidates = [path]
    if not path.startswith("/storage_internal"):
        candidates.append("/storage_internal" + path)
    else:
        candidates.append(path[len("/storage_internal"):])
    netloc = client.host if CAMERA_HTTP_PORT == 80 else f"{client.host}:{CAMERA_HTTP_PORT}"
    return [f"http://{netloc}{urllib.parse.quote(p)}" for p in candidates]


def open_camera(uri, headers=None, method="GET"):
    with state_lock:
        known = resolved.get(uri)
    candidates = [known] if known else http_url_candidates(uri)
    last_exc = None
    for url in candidates:
        req = urllib.request.Request(url, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
            with state_lock:
                resolved[uri] = url
            return resp
        except urllib.error.HTTPError as exc:
            log.debug("HTTP %s %s %s", method, exc.code, url)
            last_exc = exc
        except OSError as exc:
            log.debug("HTTP %s failed %s: %s", method, url, exc)
            last_exc = exc
    raise last_exc


def get_size(uri):
    with state_lock:
        cached = sizes.get(uri)
    if cached is not None:
        return cached
    size = None
    try:
        resp = open_camera(uri, method="HEAD")
        length = resp.headers.get("Content-Length")
        resp.close()
        if length:
            size = int(length)
    except Exception:
        pass
    if size is None:
        try:
            resp = open_camera(uri, headers={"Range": "bytes=0-0"})
            content_range = resp.headers.get("Content-Range", "")
            resp.read()
            resp.close()
            if "/" in content_range:
                size = int(content_range.rsplit("/", 1)[1])
        except Exception as exc:
            log.debug("size unavailable for %s: %s", uri, exc)
            return None
    if size is not None:
        with state_lock:
            sizes[uri] = size
    return size


def size_scan(uris):
    global size_scan_running
    log.info("size scan started for %d file(s)", len(uris))
    found = 0
    for uri in uris:
        if not client.connected.is_set():
            break
        while downloads["active"]:
            time.sleep(1)
        if get_size(uri) is not None:
            found += 1
    with state_lock:
        size_scan_running = False
    log.info("size scan finished: %d/%d sizes known", found, len(uris))


def unique_path(dest_dir, name):
    target = dest_dir / name
    stem, suffix = target.stem, target.suffix
    n = 1
    while target.exists():
        target = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return target


def download_worker(uris, dest):
    dest_dir = Path(dest).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    log.info("download batch: %d file(s) -> %s", len(uris), dest_dir)

    total = 0
    all_known = True
    for uri in uris:
        size = get_size(uri)
        if size is None:
            all_known = False
        else:
            total += size
    with dl_lock:
        downloads["bytes_total"] = total if all_known else None

    completed = 0
    started = time.time()
    for uri in uris:
        name = posixpath.basename(uri)
        with state_lock:
            expected = sizes.get(uri)
        with dl_lock:
            downloads["current"] = {"name": name, "bytes": 0, "total": expected}
        written = 0
        try:
            resp = open_camera(uri)
            with state_lock:
                url = resolved.get(uri)
            log.info("downloading %s (HTTP %s, Content-Length=%s)",
                     url, resp.status, resp.headers.get("Content-Length"))
            target = unique_path(dest_dir, name)
            t0 = time.time()
            with open(target, "wb") as out:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    elapsed = time.time() - started
                    with dl_lock:
                        downloads["current"]["bytes"] = written
                        downloads["bytes_done"] = completed + written
                        if elapsed > 0.5:
                            speed = (completed + written) / elapsed
                            downloads["speed"] = speed
                            if downloads["bytes_total"] and speed > 0:
                                remaining = downloads["bytes_total"] - completed - written
                                downloads["eta"] = max(0, remaining / speed)
            if expected is not None and written != expected:
                raise IOError(f"short read: {written}/{expected} bytes")
            elapsed = time.time() - t0
            mbps = written / 1e6 / elapsed if elapsed > 0 else 0
            log.info("saved %s (%d bytes, %.1f MB/s)", target, written, mbps)
            with dl_lock:
                downloads["files_done"] += 1
                downloads["done"].append({"name": name, "bytes": written,
                                          "path": str(target)})
        except Exception as exc:
            log.error("download failed for %s: %s", uri, exc)
            with dl_lock:
                downloads["errors"].append({"name": name, "error": str(exc)})
        completed += written
        with dl_lock:
            downloads["bytes_done"] = completed
    with dl_lock:
        downloads["current"] = None
        downloads["active"] = False
        downloads["eta"] = None
    log.info("download batch finished: %d ok, %d failed",
             downloads["files_done"], len(downloads["errors"]))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _json(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        if not path.startswith("/api/"):
            self._serve_ui(path)
        elif path == "/api/status":
            with dl_lock:
                dl = json.loads(json.dumps(downloads))
            self._json({
                "connected": client.connected.is_set(),
                "host": client.host,
                "error": client.last_error,
                "downloads": dl,
                "defaultDest": DEFAULT_DEST,
            })
        elif path == "/api/files":
            global size_scan_running
            try:
                uris, total = client.list_files()
            except Exception as exc:
                log.error("file listing failed: %s", exc)
                self._json({"error": str(exc)}, 502)
                return
            with state_lock:
                known = dict(sizes)
                start_scan = not size_scan_running
                if start_scan:
                    size_scan_running = True
            if start_scan:
                threading.Thread(target=size_scan, args=(uris,), daemon=True).start()
            self._json({"uris": uris, "total": total, "sizes": known})
        elif path == "/api/sizes":
            with state_lock:
                known = dict(sizes)
                scanning = size_scan_running
            self._json({"sizes": known, "scanning": scanning})
        elif path == "/api/media":
            self._serve_media(params)
        elif path == "/api/logs":
            cursor = int(params.get("since", 0))
            lines = ring.since(cursor)
            self._json({
                "cursor": lines[-1][0] if lines else cursor,
                "lines": [line for _, line in lines],
            })
        else:
            self._json({"error": "not found"}, 404)

    def _serve_ui(self, path):
        target = (DIST_DIR / path.lstrip("/")).resolve()
        if not target.is_relative_to(DIST_DIR) or not target.is_file():
            target = DIST_DIR / "index.html"
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if path.startswith("/assets/"):
            self.send_header("Cache-Control", "max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(data)

    def _serve_media(self, params):
        uri = params.get("uri", "")
        if not uri:
            self._json({"error": "missing uri"}, 400)
            return
        headers = {}
        range_header = self.headers.get("Range")
        if range_header:
            headers["Range"] = range_header
        try:
            resp = open_camera(uri, headers or None)
        except Exception as exc:
            self._json({"error": str(exc)}, 502)
            return
        ext = posixpath.splitext(uri)[1].lower()
        try:
            self.send_response(resp.status)
            self.send_header("Content-Type",
                             MEDIA_TYPES.get(ext, "application/octet-stream"))
            for header in ("Content-Length", "Content-Range", "Accept-Ranges"):
                value = resp.headers.get(header)
                if value:
                    self.send_header(header, value)
            self.end_headers()
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            resp.close()

    def do_POST(self):
        if self.path == "/api/connect":
            body = self._body()
            host = body.get("host") or go_ultra.CAMERA_IP
            client.host = host
            try:
                client.connect()
                self._json({"ok": True})
            except Exception as exc:
                log.error("connect failed: %s", exc)
                self._json({"error": str(exc)}, 502)
        elif self.path == "/api/disconnect":
            client.close()
            self._json({"ok": True})
        elif self.path == "/api/open-folder":
            folder = Path(self._body().get("path") or DEFAULT_DEST).expanduser()
            if not folder.is_dir():
                self._json({"error": f"folder does not exist: {folder}"}, 400)
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            elif os.name == "nt":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            self._json({"ok": True})
        elif self.path == "/api/download":
            body = self._body()
            uris = body.get("uris") or []
            dest = body.get("dest") or DEFAULT_DEST
            if not uris:
                self._json({"error": "no files selected"}, 400)
                return
            with dl_lock:
                if downloads["active"]:
                    self._json({"error": "a download batch is already running"}, 409)
                    return
                downloads.update({
                    "active": True, "files_done": 0, "files_total": len(uris),
                    "bytes_done": 0, "bytes_total": None, "speed": 0, "eta": None,
                    "current": None, "dest": dest, "done": [], "errors": [],
                })
            threading.Thread(target=download_worker, args=(uris, dest),
                             daemon=True).start()
            self._json({"ok": True, "count": len(uris)})
        else:
            self._json({"error": "not found"}, 404)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", UI_PORT), Handler)
    log.info("GO Ultra transfer UI: http://127.0.0.1:%d", UI_PORT)
    log.info("log file: %s", APP_DIR / "go-ultra.log")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
