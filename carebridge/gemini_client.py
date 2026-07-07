from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_MODEL = "gemini-3.5-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class GeminiError(RuntimeError):
    pass


class GeminiClient:
    """Minimal Gemini REST client using only the Python standard library."""

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: int = 30) -> None:
        load_env_file()
        self.api_key, self.key_source = resolve_api_key(api_key)
        self.model = normalize_model_name(model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def generate_json(self, system_instruction: str, user_payload: dict[str, Any]) -> dict[str, Any]:
        text = self.generate_text(system_instruction, user_payload)
        return parse_json_object(text)

    def generate_text(self, system_instruction: str, user_payload: dict[str, Any]) -> str:
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY or GOOGLE_API_KEY is not configured.")

        endpoint = (
            f"{API_BASE}/models/{urllib.parse.quote(self.model, safe='')}:generateContent"
            f"?key={urllib.parse.quote(self.api_key, safe='')}"
        )
        body = {
            "systemInstruction": {
                "parts": [{"text": system_instruction}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(user_payload, ensure_ascii=True, indent=2)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise GeminiError(f"Gemini API HTTP {exc.code}: {error_body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GeminiError(f"Gemini API request failed: {exc}") from exc

        try:
            return payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiError(f"Gemini API response did not include text: {payload}") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GeminiError("Gemini response did not contain a JSON object.")
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini response was not valid JSON: {exc}") from exc


def load_env_file(path: Path = ENV_PATH) -> None:
    """Load simple KEY=VALUE entries from .env without overriding real env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_api_key(explicit_key: str | None = None) -> tuple[str | None, str]:
    if explicit_key:
        return explicit_key, "explicit"
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.getenv(name)
        if value:
            return value, name
    return None, "not_configured"


def normalize_model_name(model: str) -> str:
    normalized = " ".join(str(model or DEFAULT_MODEL).strip().split())
    if normalized.startswith("models/"):
        normalized = normalized.removeprefix("models/")
    if " " in normalized:
        normalized = normalized.lower().replace(" ", "-")
    return normalized or DEFAULT_MODEL
