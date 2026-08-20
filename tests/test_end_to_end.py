import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from tests.mock_camera import MockCamera

REPO_ROOT = Path(__file__).resolve().parent.parent
VIDEO = b"v" * 200_000
PHOTO = b"p" * 40_000
FILES = {
    "/storage_internal/DCIM/Camera01/VID_20260820_100000_001.mp4": VIDEO,
    "/storage_internal/DCIM/Camera01/VID_20260817_090000_002.mp4": VIDEO,
    "/storage_internal/DCIM/Camera01/IMG_20260820_110000_003.jpg": PHOTO,
}
DEADLINE = 20


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout=DEADLINE):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def api(port, path, body=None):
    options = {"method": "POST", "data": json.dumps(body).encode()} if body is not None else {}
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", **options)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


class ServerEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = MockCamera(FILES)
        cls.camera.start()
        cls.ui_port = free_port()
        cls.server = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=REPO_ROOT,
            env={**os.environ,
                 "GOULTRA_TCP_PORT": str(cls.camera.tcp_port),
                 "GOULTRA_HTTP_PORT": str(cls.camera.http_port),
                 "GOULTRA_UI_PORT": str(cls.ui_port),
                 "GOULTRA_LOG": str(REPO_ROOT / "go-ultra.log")},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for(cls._server_up):
            raise RuntimeError("server did not start")

    @classmethod
    def _server_up(cls):
        try:
            api(cls.ui_port, "/api/status")
            return True
        except OSError:
            return False

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.camera.stop()

    def test_full_flow_connect_list_and_download(self):
        result = api(self.ui_port, "/api/connect", {"host": "127.0.0.1"})
        self.assertTrue(result.get("ok"))

        listing = api(self.ui_port, "/api/files")
        self.assertEqual(sorted(listing["uris"]), sorted(FILES))
        self.assertEqual(listing["total"], len(FILES))

        with tempfile.TemporaryDirectory() as tmp:
            uris = sorted(FILES)[:2]
            started = api(self.ui_port, "/api/download", {"uris": uris, "dest": tmp})
            self.assertTrue(started.get("ok"))
            self.assertTrue(wait_for(lambda: not api(
                self.ui_port, "/api/status")["downloads"]["active"]))
            downloads = api(self.ui_port, "/api/status")["downloads"]
            self.assertEqual(downloads["files_done"], 2)
            self.assertEqual(downloads["errors"], [])
            expected_bytes = sum(len(FILES[u]) for u in uris)
            self.assertEqual(downloads["bytes_done"], expected_bytes)
            for uri in uris:
                name = uri.rsplit("/", 1)[-1]
                self.assertEqual((Path(tmp) / name).read_bytes(), FILES[uri])

    def test_media_proxy_supports_range_requests(self):
        api(self.ui_port, "/api/connect", {"host": "127.0.0.1"})
        uri = sorted(FILES)[0]
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.ui_port}/api/media?uri={urllib.request.quote(uri)}",
            headers={"Range": "bytes=0-1023"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 1024)


class CliEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = MockCamera(FILES)
        cls.camera.start()

    @classmethod
    def tearDownClass(cls):
        cls.camera.stop()

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "cli.py", *args,
             "--host", "127.0.0.1", "--http-port", str(self.camera.http_port)],
            cwd=REPO_ROOT,
            env={**os.environ, "GOULTRA_TCP_PORT": str(self.camera.tcp_port)},
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_ls_lists_files_with_sizes(self):
        result = self.run_cli("ls")
        self.assertEqual(result.returncode, 0)
        self.assertIn("VID_20260820_100000_001.mp4", result.stdout)
        self.assertIn("200 KB", result.stdout)
        self.assertIn("3 file(s)", result.stderr)

    def test_download_by_glob_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("download", "VID_20260820*", "-o", tmp)
            self.assertEqual(result.returncode, 0)
            target = Path(tmp) / "VID_20260820_100000_001.mp4"
            self.assertEqual(target.read_bytes(), VIDEO)

    def test_download_without_selector_fails_cleanly(self):
        result = self.run_cli("download")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Nothing selected", result.stderr)


if __name__ == "__main__":
    unittest.main()
