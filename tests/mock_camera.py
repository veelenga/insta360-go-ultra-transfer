import re
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PKT_SYNC = b"\x06\x00\x00syNceNdinS"
CMD_GET_FILE_LIST = 13


def varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def field_bytes(field, data):
    return varint(field << 3 | 2) + varint(len(data)) + data


def field_varint(field, value):
    return varint(field << 3) + varint(value)


def pack(payload):
    return struct.pack("<I", len(payload) + 4) + payload


def response_frame(code, seq, body):
    return (b"\x04\x00\x00" + struct.pack("<H", code) + b"\x02"
            + struct.pack("<I", seq)[:3] + b"\x80\x00\x00" + body)


def parse_request_fields(body):
    values = {}
    i = 0
    while i < len(body):
        tag = body[i]
        i += 1
        field, wire = tag >> 3, tag & 7
        if wire != 0:
            break
        value = 0
        shift = 0
        while i < len(body):
            byte = body[i]
            i += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        values[field] = value
    return values


class MockCamera:
    def __init__(self, files):
        self.files = files
        self.gate_open = False
        self._running = False
        self._tcp = None
        self._http = None
        self.tcp_port = None
        self.http_port = None

    def start(self):
        self._running = True
        self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp.bind(("127.0.0.1", 0))
        self._tcp.listen(4)
        self.tcp_port = self._tcp.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

        camera = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _lookup(self):
                if not camera.gate_open:
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                data = camera.files.get(self.path)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                return data

            def do_HEAD(self):
                data = self._lookup()
                if data is None:
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

            def do_GET(self):
                data = self._lookup()
                if data is None:
                    return
                match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
                if match and (match.group(1) or match.group(2)):
                    start = int(match.group(1) or 0)
                    end = int(match.group(2)) if match.group(2) else len(data) - 1
                    end = min(end, len(data) - 1)
                    body = data[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
                else:
                    body = data
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_port = self._http.server_address[1]
        threading.Thread(target=self._http.serve_forever, daemon=True).start()

    def stop(self):
        self._running = False
        if self._tcp:
            self._tcp.close()
        if self._http:
            self._http.shutdown()
            self._http.server_close()

    def _accept_loop(self):
        while self._running:
            try:
                conn, _ = self._tcp.accept()
            except OSError:
                return
            threading.Thread(target=self._serve_control, args=(conn,),
                             daemon=True).start()

    def _serve_control(self, conn):
        buf = b""
        while self._running:
            try:
                chunk = conn.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while len(buf) >= 4:
                length = struct.unpack("<I", buf[:4])[0]
                if len(buf) < length:
                    break
                pkt = buf[4:length]
                buf = buf[length:]
                self._handle_packet(conn, pkt)
        self.gate_open = False
        conn.close()

    def _handle_packet(self, conn, pkt):
        if pkt == PKT_SYNC:
            self.gate_open = True
            conn.sendall(pack(PKT_SYNC))
        elif pkt[:3] == b"\x04\x00\x00":
            cmd = struct.unpack("<H", pkt[3:5])[0]
            seq = int.from_bytes(pkt[6:9], "little")
            if cmd == CMD_GET_FILE_LIST:
                request = parse_request_fields(pkt[12:])
                start = request.get(2, 0)
                limit = request.get(3, 50)
                uris = sorted(self.files)[start:start + limit]
                body = b"".join(field_bytes(1, u.encode()) for u in uris)
                body += field_varint(2, len(self.files))
                conn.sendall(pack(response_frame(200, seq, body)))
            else:
                conn.sendall(pack(response_frame(500, seq, b"")))
