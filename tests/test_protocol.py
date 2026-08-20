import unittest

from go_ultra import GoUltraClient
from tests.mock_camera import MockCamera

FILES = {
    f"/storage_internal/DCIM/Camera01/VID_20260820_1000{i:02d}_{i:03d}.mp4": b"x"
    for i in range(120)
}


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.camera = MockCamera(FILES)
        cls.camera.start()

    @classmethod
    def tearDownClass(cls):
        cls.camera.stop()

    def test_connect_performs_sync_handshake(self):
        client = GoUltraClient("127.0.0.1", self.camera.tcp_port)
        try:
            client.connect(timeout=5)
            self.assertTrue(client.connected.is_set())
        finally:
            client.close()

    def test_list_files_pages_through_full_listing(self):
        client = GoUltraClient("127.0.0.1", self.camera.tcp_port)
        try:
            client.connect(timeout=5)
            uris, total = client.list_files()
            self.assertEqual(total, 120)
            self.assertEqual(sorted(uris), sorted(FILES))
        finally:
            client.close()

    def test_connect_fails_fast_when_camera_is_absent(self):
        client = GoUltraClient("127.0.0.1", 1)
        with self.assertRaises(OSError):
            client.connect(timeout=2)


if __name__ == "__main__":
    unittest.main()
