#!/usr/bin/env python3
"""Serve the offline gallery using only Python's standard library."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GalleryHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Keep terminal output useful; errors still appear.
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    handler = partial(GalleryHandler, directory=str(ROOT))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as error:
        parser.exit(1, f"Could not start preview: {error}\nTry --port 4174.\n")
    print(f"Local: http://127.0.0.1:{server.server_port}/", flush=True)
    print("Press Ctrl+C to stop. No internet connection is required.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
