"""Minimal HTTP server to serve /.well-known/mcp/server-card.json for Smithery scanning."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CARD_PATH = Path(__file__).parent / ".well-known" / "mcp" / "server-card.json"


class CardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/.well-known/mcp/server-card.json":
            data = CARD_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress noisy access logs on stdio


def start_card_server(port: int = 8080):
    """Start the card server in a background daemon thread."""
    server = HTTPServer(("0.0.0.0", port), CardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server