#!/usr/bin/env python3
import argparse
import errno
import fnmatch
import logging
import posixpath
import re
import sys
import time
from pathlib import Path

import go_ultra
from go_ultra import GoUltraClient
from transfer import CameraTransfer, download_file

DEFAULT_DEST = Path.home() / "Downloads" / "GoUltra"
TIMESTAMP_PATTERN = re.compile(r"(\d{4})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})")


def format_bytes(value):
    if value is None:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(value)
    unit = 0
    while n >= 1000 and unit < len(units) - 1:
        n /= 1000
        unit += 1
    digits = 0 if n >= 10 or unit == 0 else 1
    return f"{n:.{digits}f} {units[unit]}"


class MediaEntry:
    def __init__(self, uri):
        self.uri = uri
        self.name = posixpath.basename(uri)
        stamp = TIMESTAMP_PATTERN.search(self.name)
        self.date = f"{stamp[1]}-{stamp[2]}-{stamp[3]}" if stamp else "unknown"
        self.time = f"{stamp[4]}:{stamp[5]}:{stamp[6]}" if stamp else ""
        self.is_lrv = (self.name.lower().endswith(".lrv")
                       or self.name.upper().startswith("LRV_"))


def fetch_entries(client, include_lrv, day=None):
    uris, _total = client.list_files()
    entries = [MediaEntry(uri) for uri in uris]
    if not include_lrv:
        entries = [e for e in entries if not e.is_lrv]
    if day:
        entries = [e for e in entries if e.date == day]
    return entries


def connected_client(host):
    print(f"Connecting to {host} ...", file=sys.stderr)
    client = GoUltraClient(host)
    client.connect()
    return client


def cmd_ls(args):
    client = connected_client(args.host)
    transfer = CameraTransfer(client, args.http_port)
    try:
        entries = fetch_entries(client, args.lrv, args.day)
        name_width = max((len(e.name) for e in entries), default=0)
        total_bytes = 0
        for date in sorted({e.date for e in entries}, reverse=True):
            print(date)
            for entry in sorted((e for e in entries if e.date == date),
                                key=lambda e: e.name):
                size = transfer.get_size(entry.uri)
                total_bytes += size or 0
                print(f"  {entry.name:<{name_width}}  {format_bytes(size):>8}")
        print(f"{len(entries)} file(s), {format_bytes(total_bytes)}", file=sys.stderr)
    finally:
        client.close()
    return 0


def select_for_download(entries, args):
    if args.patterns:
        return [e for e in entries
                if any(fnmatch.fnmatch(e.name, p) for p in args.patterns)]
    return entries


def print_progress(name, done, expected, speed):
    total = f" / {format_bytes(expected)}" if expected else ""
    rate = f"  {format_bytes(speed)}/s" if speed else ""
    sys.stderr.write(f"\r  {name}  {format_bytes(done)}{total}{rate}   ")
    sys.stderr.flush()


def cmd_download(args):
    if not (args.all or args.day or args.patterns):
        print("Nothing selected: pass file patterns, --day, or --all.",
              file=sys.stderr)
        return 2
    client = connected_client(args.host)
    transfer = CameraTransfer(client, args.http_port)
    failures = 0
    try:
        entries = select_for_download(fetch_entries(client, args.lrv, args.day), args)
        if not entries:
            print("No files matched.", file=sys.stderr)
            return 1
        dest = Path(args.output).expanduser()
        print(f"Downloading {len(entries)} file(s) to {dest}", file=sys.stderr)
        copied_bytes = 0
        for entry in entries:
            started = time.time()

            def on_progress(done, expected):
                elapsed = time.time() - started
                speed = done / elapsed if elapsed > 0.5 else None
                print_progress(entry.name, done, expected, speed)

            try:
                target, written = download_file(transfer, entry.uri, dest, on_progress)
                copied_bytes += written
                sys.stderr.write("\r\033[K")
                print(f"  {entry.name}  {format_bytes(written)}  -> {target}",
                      file=sys.stderr)
            except Exception as exc:
                failures += 1
                sys.stderr.write("\r\033[K")
                print(f"  {entry.name}  failed: {exc}", file=sys.stderr)
        summary = f"Copied {len(entries) - failures} file(s) ({format_bytes(copied_bytes)}) to {dest}"
        if failures:
            summary += f", {failures} failed"
        print(summary, file=sys.stderr)
    finally:
        client.close()
    return 1 if failures else 0


def cmd_server(args):
    import server
    server.main(port=args.port)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="igut",
        description="Browse, preview, and copy media from the Insta360 GO Ultra over WiFi.",
    )
    parser.add_argument("--verbose", action="store_true",
                        help="show protocol debug output")
    commands = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=go_ultra.CAMERA_IP,
                        help=f"camera address (default {go_ultra.CAMERA_IP})")
    common.add_argument("--http-port", type=int, default=80, help=argparse.SUPPRESS)
    common.add_argument("--lrv", action="store_true",
                        help="include LRV proxy files")
    common.add_argument("--day", metavar="YYYY-MM-DD",
                        help="only files recorded on this day")

    server_cmd = commands.add_parser("server", help="run the web UI")
    server_cmd.add_argument("--port", type=int, default=8765,
                            help="UI port (default 8765)")
    server_cmd.set_defaults(func=cmd_server)

    ls = commands.add_parser("ls", parents=[common],
                             help="list files on the camera")
    ls.set_defaults(func=cmd_ls)

    download = commands.add_parser("download", parents=[common],
                                   help="copy files to a local folder")
    download.add_argument("patterns", nargs="*", metavar="pattern",
                          help='file name globs, e.g. "VID_20260820*"')
    download.add_argument("--all", action="store_true", help="all files")
    download.add_argument("-o", "--output", default=str(DEFAULT_DEST),
                          help=f"destination folder (default {DEFAULT_DEST})")
    download.set_defaults(func=cmd_download)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    if args.command != "server":
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.WARNING,
            format="%(levelname)s %(message)s",
        )
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, TimeoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if getattr(exc, "errno", None) == errno.EADDRINUSE:
            print("Is igut server already running? Pass --port to use another port.",
                  file=sys.stderr)
        elif args.command != "server":
            print("Are you connected to the camera's WiFi hotspot?", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
