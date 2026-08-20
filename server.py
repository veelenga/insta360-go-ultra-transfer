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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import go_ultra
from go_ultra import GoUltraClient
from transfer import CameraTransfer, download_file

APP_DIR = Path(__file__).resolve().parent
DIST_DIR = APP_DIR / "static" / "dist"
UI_PORT = int(os.environ.get("GOULTRA_UI_PORT", "8765"))
CAMERA_HTTP_PORT = int(os.environ.get("GOULTRA_HTTP_PORT", "80"))
DEFAULT_DEST = str(Path.home() / "Downloads" / "GoUltra")

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


def default_log_path():
    override = os.environ.get("GOULTRA_LOG")
    if override:
        return Path(override).expanduser()
    if os.access(APP_DIR, os.W_OK):
        return APP_DIR / "go-ultra.log"
    return Path.home() / ".go-ultra.log"


LOG_PATH = default_log_path()
ring = RingLogHandler()
ring.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
file_handler = logging.FileHandler(LOG_PATH)
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
logging.basicConfig(level=logging.DEBUG, handlers=[ring, file_handler])
logging.getLogger().addHandler(logging.StreamHandler())
log = logging.getLogger("server")

client = GoUltraClient()
transfer = CameraTransfer(client, CAMERA_HTTP_PORT)

state_lock = threading.Lock()
size_scan_running = False

dl_lock = threading.Lock()
downloads = {
    "active": False, "files_done": 0, "files_total": 0,
    "bytes_done": 0, "bytes_total": None, "speed": 0, "eta": None,
    "current": None, "dest": None, "done": [], "errors": [],
}


def size_scan(uris):
    global size_scan_running
    log.info("size scan started for %d file(s)", len(uris))
    found = 0
    for uri in uris:
        if not client.connected.is_set():
            break
        while downloads["active"]:
            time.sleep(1)
        if transfer.get_size(uri) is not None:
            found += 1
    with state_lock:
        size_scan_running = False
    log.info("size scan finished: %d/%d sizes known", found, len(uris))


def download_worker(uris, dest):
    dest_dir = Path(dest).expanduser()
    log.info("download batch: %d file(s) -> %s", len(uris), dest_dir)

    total = 0
    all_known = True
    for uri in uris:
        size = transfer.get_size(uri)
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
        with dl_lock:
            downloads["current"] = {"name": name, "bytes": 0,
                                    "total": transfer.size_of(uri)}
        written = 0

        def on_progress(done, _expected):
            nonlocal written
            written = done
            elapsed = time.time() - started
            with dl_lock:
                downloads["current"]["bytes"] = done
                downloads["bytes_done"] = completed + done
                if elapsed > 0.5:
                    speed = (completed + done) / elapsed
                    downloads["speed"] = speed
                    if downloads["bytes_total"] and speed > 0:
                        remaining = downloads["bytes_total"] - completed - done
                        downloads["eta"] = max(0, remaining / speed)

        try:
            t0 = time.time()
            target, written = download_file(transfer, uri, dest_dir, on_progress)
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
                start_scan = not size_scan_running
                if start_scan:
                    size_scan_running = True
            if start_scan:
                threading.Thread(target=size_scan, args=(uris,), daemon=True).start()
            self._json({"uris": uris, "total": total, "sizes": transfer.known_sizes()})
        elif path == "/api/sizes":
            with state_lock:
                scanning = size_scan_running
            self._json({"sizes": transfer.known_sizes(), "scanning": scanning})
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
            resp = transfer.open(uri, headers or None)
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


def main(port=UI_PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    log.info("GO Ultra transfer UI: http://127.0.0.1:%d", port)
    log.info("log file: %s", LOG_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        client.close()


if __name__ == "__main__":
    main()
