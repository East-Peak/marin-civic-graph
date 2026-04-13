#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ReusableThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the local graph viewer over a simple read-only HTTP shell.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.chdir(ROOT)
    handler = http.server.SimpleHTTPRequestHandler
    with ReusableThreadingTCPServer((args.host, args.port), handler) as httpd:
        url = f"http://{args.host}:{args.port}/viewer/"
        print(f"Serving Marin Civic Graph viewer at {url}")
        if args.open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
