#!/usr/bin/env python3
"""
LifeOS local server.

Serves the dashboard on your computer AND your phone (same Wi-Fi).
Run it, then bookmark the printed URL.

    python3 serve.py            # default port 8080
    python3 serve.py 5000       # custom port
"""
import http.server
import socket
import socketserver
import sys
import os

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".js": "application/javascript",
        ".json": "application/json",
    }

    def end_headers(self):
        # let the service worker control the whole scope; avoid stale caching of the shell
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *a):
        pass  # quiet


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    ip = lan_ip()
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        print("\n  LifeOS is running\n")
        print(f"  • This computer:  http://localhost:{PORT}")
        print(f"  • Phone (same Wi-Fi):  http://{ip}:{PORT}")
        print("\n  Bookmark either link. On iPhone, open the phone link in")
        print("  Safari → Share → Add to Home Screen to install it as an app.")
        print("\n  Ctrl+C to stop.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")
