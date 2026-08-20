import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("goultra.transfer")

HTTP_TIMEOUT = 25
CHUNK_SIZE = 256 * 1024
INTERNAL_STORAGE_PREFIX = "/storage_internal"


class CameraTransfer:
    def __init__(self, client, http_port=80):
        self.client = client
        self.http_port = http_port
        self._lock = threading.Lock()
        self._sizes = {}
        self._resolved = {}

    def url_candidates(self, uri):
        path = uri if uri.startswith("/") else "/" + uri
        candidates = [path]
        if path.startswith(INTERNAL_STORAGE_PREFIX):
            candidates.append(path[len(INTERNAL_STORAGE_PREFIX):])
        else:
            candidates.append(INTERNAL_STORAGE_PREFIX + path)
        host = self.client.host
        netloc = host if self.http_port == 80 else f"{host}:{self.http_port}"
        return [f"http://{netloc}{urllib.parse.quote(p)}" for p in candidates]

    def open(self, uri, headers=None, method="GET"):
        with self._lock:
            known = self._resolved.get(uri)
        candidates = [known] if known else self.url_candidates(uri)
        last_exc = None
        for url in candidates:
            request = urllib.request.Request(url, method=method)
            for key, value in (headers or {}).items():
                request.add_header(key, value)
            try:
                response = urllib.request.urlopen(request, timeout=HTTP_TIMEOUT)
                with self._lock:
                    self._resolved[uri] = url
                return response
            except urllib.error.HTTPError as exc:
                log.debug("HTTP %s %s %s", method, exc.code, url)
                last_exc = exc
            except OSError as exc:
                log.debug("HTTP %s failed %s: %s", method, url, exc)
                last_exc = exc
        raise last_exc

    def get_size(self, uri):
        cached = self.size_of(uri)
        if cached is not None:
            return cached
        size = self._probe_size(uri)
        if size is not None:
            with self._lock:
                self._sizes[uri] = size
        return size

    def _probe_size(self, uri):
        try:
            response = self.open(uri, method="HEAD")
            length = response.headers.get("Content-Length")
            response.close()
            if length:
                return int(length)
        except Exception:
            pass
        try:
            response = self.open(uri, headers={"Range": "bytes=0-0"})
            content_range = response.headers.get("Content-Range", "")
            response.read()
            response.close()
            if "/" in content_range:
                return int(content_range.rsplit("/", 1)[1])
        except Exception as exc:
            log.debug("size unavailable for %s: %s", uri, exc)
        return None

    def size_of(self, uri):
        with self._lock:
            return self._sizes.get(uri)

    def known_sizes(self):
        with self._lock:
            return dict(self._sizes)

    def resolved_url(self, uri):
        with self._lock:
            return self._resolved.get(uri)


def unique_path(dest_dir, name):
    target = dest_dir / name
    stem, suffix = target.stem, target.suffix
    n = 1
    while target.exists():
        target = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return target


def download_file(transfer, uri, dest_dir, on_progress=None):
    dest_dir = Path(dest_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    response = transfer.open(uri)
    length = response.headers.get("Content-Length")
    expected = int(length) if length else None
    log.info("downloading %s (HTTP %s, Content-Length=%s)",
             transfer.resolved_url(uri), response.status, length)
    name = uri.rstrip("/").rsplit("/", 1)[-1]
    target = unique_path(dest_dir, name)
    written = 0
    with open(target, "wb") as out:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
            written += len(chunk)
            if on_progress:
                on_progress(written, expected)
    if expected is not None and written != expected:
        raise IOError(f"short read: {written}/{expected} bytes")
    return target, written
