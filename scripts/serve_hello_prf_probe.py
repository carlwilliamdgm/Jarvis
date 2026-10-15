"""Serve the isolated WebAuthn PRF probe on loopback only."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


PROBE = Path(__file__).with_name("hello_prf_probe.html")
ELECTRON_PROBE = Path(__file__).with_name("hello_prf_electron_probe.html")


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            page = PROBE
        elif self.path == "/electron":
            page = ELECTRON_PROBE
        else:
            self.send_error(404)
            return
        try:
            body = page.read_bytes()
        except OSError:
            self.send_error(500, "Probe HTML unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return  # The probe carries no server-side state or request logging.


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8765), ProbeHandler)
    print("Sonde locale prête : http://127.0.0.1:8765/ (Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
