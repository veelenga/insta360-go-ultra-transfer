import collections
import logging
import os
import socket
import struct
import threading
import time

log = logging.getLogger("goultra")

CAMERA_IP = os.environ.get("GOULTRA_IP", "192.168.42.1")
CAMERA_PORT = int(os.environ.get("GOULTRA_TCP_PORT", "6666"))

PKT_SYNC = b"\x06\x00\x00syNceNdinS"
PKT_KEEPALIVE = b"\x05\x00\x00"
TYPE_COMMAND = b"\x04\x00\x00"
TYPE_VIDEO = b"\x01\x00\x00"

CMD_GET_FILE_EXTRA = 11
CMD_GET_FILE_LIST = 13
CMD_GET_MINI_THUMBNAIL = 30

MEDIA_VIDEO_AND_PHOTO = 2

KEEPALIVE_INTERVAL = 2.0
RESPONSE_TIMEOUT = 8.0


def encode_varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def field_varint(field, value):
    return encode_varint(field << 3) + encode_varint(value)


def field_bytes(field, data):
    return encode_varint(field << 3 | 2) + encode_varint(len(data)) + data


def decode_fields(body):
    fields = []
    i = 0
    n = len(body)
    while i < n:
        tag = 0
        shift = 0
        while True:
            if i >= n:
                return fields
            b = body[i]
            i += 1
            tag |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value = 0
            shift = 0
            while i < n:
                b = body[i]
                i += 1
                value |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            fields.append((field, wire, value))
        elif wire == 2:
            length = 0
            shift = 0
            while i < n:
                b = body[i]
                i += 1
                length |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
            fields.append((field, wire, body[i:i + length]))
            i += length
        elif wire == 1:
            fields.append((field, wire, body[i:i + 8]))
            i += 8
        elif wire == 5:
            fields.append((field, wire, body[i:i + 4]))
            i += 4
        else:
            return fields
    return fields


def pack_packet(payload):
    return struct.pack("<I", len(payload) + 4) + payload


def make_command(cmd_id, seq, proto=b""):
    return (
        TYPE_COMMAND
        + struct.pack("<H", cmd_id)
        + b"\x02"
        + struct.pack("<I", seq)[:3]
        + b"\x80\x00\x00"
        + proto
    )


class GoUltraClient:
    def __init__(self, host=CAMERA_IP, port=CAMERA_PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = threading.Event()
        self.closed = threading.Event()
        self.last_error = None
        self._seq = 0
        self._lock = threading.Lock()
        self._pending = {}
        self._notifications = collections.deque(maxlen=50)
        self._reader = None
        self._keepalive = None

    def connect(self, timeout=8.0):
        self.close()
        self.closed.clear()
        self.connected.clear()
        self.last_error = None
        log.info("TCP connect -> %s:%s", self.host, self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((self.host, self.port))
        except OSError:
            sock.close()
            raise
        sock.settimeout(None)
        self.sock = sock
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._send(PKT_SYNC)
        log.info("sent SYNC handshake (%s)", PKT_SYNC.hex())
        if not self.connected.wait(timeout):
            raise TimeoutError("camera did not echo SYNC handshake")
        log.info("SYNC echoed by camera - session established")
        self._keepalive = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive.start()

    def close(self):
        self.closed.set()
        self.connected.clear()
        sock, self.sock = self.sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
            log.info("session closed")
        with self._lock:
            for evt, slot in self._pending.values():
                slot.append((None, b""))
                evt.set()
            self._pending.clear()

    def _send(self, payload):
        sock = self.sock
        if not sock:
            raise ConnectionError("not connected")
        data = pack_packet(payload)
        log.debug("send len=%d %s", len(data), data[:32].hex())
        sock.sendall(data)

    def _keepalive_loop(self):
        while not self.closed.is_set():
            time.sleep(KEEPALIVE_INTERVAL)
            if self.closed.is_set():
                return
            try:
                self._send(PKT_KEEPALIVE)
                log.debug("keepalive sent")
            except OSError as exc:
                self._fail(f"keepalive failed: {exc}")
                return

    def _fail(self, message):
        if not self.closed.is_set():
            self.last_error = message
            log.error("connection lost: %s", message)
            self.close()

    def _read_loop(self):
        buf = b""
        while not self.closed.is_set():
            sock = self.sock
            if not sock:
                return
            try:
                chunk = sock.recv(65536)
            except OSError as exc:
                self._fail(f"recv failed: {exc}")
                return
            if not chunk:
                self._fail("camera closed the connection")
                return
            buf += chunk
            while len(buf) >= 4:
                pkt_len = struct.unpack("<I", buf[:4])[0]
                if pkt_len < 4 or pkt_len > 32 * 1024 * 1024:
                    self._fail(f"bad frame length {pkt_len}")
                    return
                if len(buf) < pkt_len:
                    break
                pkt = buf[4:pkt_len]
                buf = buf[pkt_len:]
                self._handle(pkt)

    def _handle(self, pkt):
        if len(pkt) < 3:
            return
        ptype = pkt[:3]
        if pkt == PKT_SYNC:
            log.debug("recv SYNC echo")
            self.connected.set()
        elif ptype == TYPE_COMMAND:
            if len(pkt) < 12:
                log.warning("short command frame: %s", pkt.hex())
                return
            code = struct.unpack("<H", pkt[3:5])[0]
            seq = int.from_bytes(pkt[6:9], "little")
            body = pkt[12:]
            log.debug("recv cmd frame code=%d seq=%d body_len=%d head=%s",
                      code, seq, len(body), pkt[:16].hex())
            with self._lock:
                waiter = self._pending.pop(seq, None)
            if waiter:
                evt, slot = waiter
                slot.append((code, body))
                evt.set()
            else:
                log.info("camera notification code=%d len=%d head=%s",
                         code, len(body), body[:24].hex())
                self._notifications.append((code, body))
        elif ptype == PKT_KEEPALIVE:
            log.debug("recv keepalive echo")
        elif ptype == TYPE_VIDEO:
            pass
        else:
            log.info("recv unknown frame type=%s len=%d head=%s",
                     ptype.hex(), len(pkt), pkt[:24].hex())

    def send_command(self, cmd_id, proto=b"", timeout=RESPONSE_TIMEOUT):
        if not self.connected.is_set():
            raise ConnectionError(self.last_error or "not connected")
        evt = threading.Event()
        slot = []
        with self._lock:
            self._seq += 1
            seq = self._seq
            self._pending[seq] = (evt, slot)
        log.info("command %d seq=%d proto_len=%d", cmd_id, seq, len(proto))
        try:
            self._send(make_command(cmd_id, seq, proto))
        except OSError as exc:
            with self._lock:
                self._pending.pop(seq, None)
            self._fail(f"send failed: {exc}")
            raise ConnectionError(str(exc)) from exc
        if not evt.wait(timeout):
            with self._lock:
                self._pending.pop(seq, None)
            log.warning("command %d seq=%d timed out after %.1fs", cmd_id, seq, timeout)
            raise TimeoutError(f"command {cmd_id} timed out")
        code, body = slot[0]
        if code is None:
            raise ConnectionError(self.last_error or "connection closed")
        log.info("response cmd=%d seq=%d code=%d body_len=%d", cmd_id, seq, code, len(body))
        return code, body

    def list_files(self, media_type=MEDIA_VIDEO_AND_PHOTO, page_size=50):
        uris = []
        total = None
        start = 0
        while True:
            body = (
                field_varint(1, media_type)
                + field_varint(2, start)
                + field_varint(3, page_size)
            )
            code, resp = self.send_command(CMD_GET_FILE_LIST, body)
            if code != 200:
                raise RuntimeError(f"GET_FILE_LIST returned code {code}")
            page = []
            for field, wire, value in decode_fields(resp):
                if field == 1 and wire == 2:
                    page.append(value.decode("utf-8", "replace"))
                elif field == 2 and wire == 0:
                    total = value
            log.info("file list page start=%d got=%d total=%s", start, len(page), total)
            uris.extend(page)
            start += len(page)
            if not page or (total is not None and start >= total):
                return uris, (total if total is not None else len(uris))

    def get_thumbnail(self, uri, timeout=5.0):
        code, body = self.send_command(
            CMD_GET_MINI_THUMBNAIL, field_bytes(1, uri.encode()), timeout=timeout
        )
        if code != 200:
            raise RuntimeError(f"GET_MINI_THUMBNAIL returned code {code}")
        soi = body.find(b"\xff\xd8\xff")
        if soi < 0:
            raise ValueError("no JPEG payload in thumbnail response")
        return body[soi:]
