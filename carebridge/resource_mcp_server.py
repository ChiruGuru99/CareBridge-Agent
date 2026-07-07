from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from carebridge.resource_directory import get_preparation_checklist, search_resources


PROTOCOL_VERSION = "2024-11-05"


TOOLS = [
    {
        "name": "search_resources",
        "description": "Search the local community resource directory by need and location.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "location": {"type": "string"},
                "needs": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query", "location"],
        },
    },
    {
        "name": "get_preparation_checklist",
        "description": "Return documents or details to gather for a support category.",
        "inputSchema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": ["category"],
        },
    },
]


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode("utf-8").split(":", 1)
        headers[key.lower()] = value.strip()

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    stream.write(header + body)
    stream.flush()


def tool_result(result: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, indent=2),
            }
        ]
    }


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")

    if method == "notifications/initialized":
        return None

    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "carebridge-resource-mcp", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            if name == "search_resources":
                result = tool_result(
                    search_resources(
                        query=arguments.get("query", ""),
                        location=arguments.get("location", ""),
                        needs=arguments.get("needs", []),
                        limit=int(arguments.get("limit", 6)),
                    )
                )
            elif name == "get_preparation_checklist":
                result = tool_result(get_preparation_checklist(arguments.get("category", "")))
            else:
                raise ValueError(f"Unknown tool: {name}")
        else:
            raise ValueError(f"Unsupported method: {method}")

        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        message = read_message(stdin)
        if message is None:
            break
        response = handle_request(message)
        if response is not None and "id" in message:
            write_message(stdout, response)


if __name__ == "__main__":
    main()

