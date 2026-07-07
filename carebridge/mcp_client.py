from __future__ import annotations

import json
import subprocess
import sys
from itertools import count
from pathlib import Path
from typing import Any, BinaryIO


class ResourceMCPClient:
    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._ids = count(1)

    def __enter__(self) -> "ResourceMCPClient":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        project_root = Path(__file__).resolve().parent.parent
        self._process = subprocess.Popen(
            [sys.executable, "-m", "carebridge.resource_mcp_server"],
            cwd=str(project_root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._request("initialize", {"clientInfo": {"name": "carebridge-agent"}, "protocolVersion": "2024-11-05"})
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self._process is None:
            return
        process = self._process
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        self._process = None

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        return result["tools"]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        content = result["content"][0]["text"]
        return json.loads(content)

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = next(self._ids)
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        response = self._read()
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return response["result"]

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, payload: dict[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP server is not running.")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self._process.stdin.write(header + body)
        self._process.stdin.flush()

    def _read(self) -> dict[str, Any]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("MCP server is not running.")
        return read_message(self._process.stdout)


def read_message(stream: BinaryIO) -> dict[str, Any]:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout.")
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("utf-8").split(":", 1)
        headers[key.lower()] = value.strip()

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        raise RuntimeError("MCP response did not include a body.")
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))
