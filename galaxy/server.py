#!/usr/bin/env python3
"""Local, viewer-only HTTP server. Python standard library; no packages."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

VIEWER = (Path(__file__).resolve().parent / 'viewer').resolve()


class ViewerHandler(SimpleHTTPRequestHandler):
    def allowed(self):
        try:
            path = unquote(urlsplit(self.path).path, errors='strict')
            target = (VIEWER / path.lstrip('/')).resolve()
            if target.is_dir():
                for name in ('index.html', 'index.htm'):
                    candidate = target / name
                    if candidate.exists():
                        target = candidate.resolve()
                        break
            return target.is_relative_to(VIEWER) and '\\' not in path and '\x00' not in path
        except (OSError, ValueError, UnicodeError):
            return False

    def do_GET(self):
        if not self.allowed():
            self.send_error(403, 'Only viewer files are available.'); return
        super().do_GET()

    def do_HEAD(self):
        if not self.allowed():
            self.send_error(403, 'Only viewer files are available.'); return
        super().do_HEAD()

    def list_directory(self, path):
        self.send_error(403, 'Directory listing is disabled.')
        return None

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4700)
    args = parser.parse_args()
    if not (VIEWER/'index.html').is_file() or not (VIEWER/'graph-data.js').is_file():
        parser.exit(1, 'Viewer or graph data missing. Run python3 build.py first.\n')
    handler = partial(ViewerHandler, directory=str(VIEWER))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as error:
        parser.exit(1, f'Could not start the galaxy server: {error}\n')
    print(f'Knowledge galaxy: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
