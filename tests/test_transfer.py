import tempfile
import unittest
from pathlib import Path

from go_ultra import GoUltraClient
from tests.mock_camera import MockCamera
from transfer import CameraTransfer, download_file

VIDEO = b"v" * 300_000
FILES = {
    "/storage_internal/DCIM/Camera01/VID_20260820_100000_001.mp4": VIDEO,
}
URI = "/storage_internal/DCIM/Camera01/VID_20260820_100000_001.mp4"
BARE_URI = "/DCIM/Camera01/VID_20260820_100000_001.mp4"


class TransferTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = MockCamera(FILES)
        cls.camera.start()
        cls.client = GoUltraClient("127.0.0.1", cls.camera.tcp_port)
        cls.client.connect(timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.camera.stop()

    def make_transfer(self):
        return CameraTransfer(self.client, self.camera.http_port)

    def test_get_size_reports_content_length(self):
        self.assertEqual(self.make_transfer().get_size(URI), len(VIDEO))

    def test_uri_without_storage_prefix_falls_back(self):
        self.assertEqual(self.make_transfer().get_size(BARE_URI), len(VIDEO))

    def test_download_file_writes_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, written = download_file(self.make_transfer(), URI, tmp)
            self.assertEqual(written, len(VIDEO))
            self.assertEqual(Path(target).read_bytes(), VIDEO)

    def test_download_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            transfer = self.make_transfer()
            first, _ = download_file(transfer, URI, tmp)
            second, _ = download_file(transfer, URI, tmp)
            self.assertNotEqual(first, second)
            self.assertEqual(Path(second).read_bytes(), VIDEO)


if __name__ == "__main__":
    unittest.main()
