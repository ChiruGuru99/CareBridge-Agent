from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from carebridge.agents import run_carebridge_agent


ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"


class CareBridgeHandler(BaseHTTPRequestHandler):
    server_version = "CareBridgeHTTP/0.1"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send_file(WEB_ROOT / "index.html")
            return
        requested = (WEB_ROOT / unquote(path.lstrip("/"))).resolve()
        if WEB_ROOT in requested.parents and requested.is_file():
            self._send_file(requested)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path != "/api/plan":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not payload.get("text"):
                self._send_json({"error": "text is required"}, status=400)
                return
            plan = run_carebridge_agent(payload)
            self._send_json(plan)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_server(host: str, port: int) -> None:
    httpd = ThreadingHTTPServer((host, port), CareBridgeHandler)
    print(f"CareBridge Agent running at http://{host}:{port}")
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CareBridge Agent web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(args.host, args.port)

