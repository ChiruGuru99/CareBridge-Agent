from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactionFinding:
    kind: str
    count: int


PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "phone": re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "address": re.compile(
        r"\b\d{1,5}\s+[A-Z0-9][A-Z0-9 .'-]{1,50}\s+"
        r"(?:STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|LANE|LN|DRIVE|DR)\b",
        re.IGNORECASE,
    ),
}

INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(r"\b(ignore|override|forget)\b.{0,40}\b(previous|prior|system|developer)\b", re.IGNORECASE),
    "secret_request": re.compile(r"\b(api key|password|token|secret|credential|private key)\b", re.IGNORECASE),
    "system_prompt_request": re.compile(r"\b(system prompt|developer message|hidden instructions|tool schema)\b", re.IGNORECASE),
    "tool_abuse": re.compile(r"\b(exfiltrate|download files|run shell|open network|disable safety)\b", re.IGNORECASE),
}

ALLOWED_TOOLS = {"search_resources", "get_preparation_checklist"}
MAX_TOOL_STRING_LENGTH = 240


def redact_pii(text: str) -> tuple[str, list[RedactionFinding]]:
    """Replace common direct identifiers with stable placeholders."""
    redacted = text
    findings: list[RedactionFinding] = []

    for kind, pattern in PII_PATTERNS.items():
        redacted, count = pattern.subn(f"[REDACTED_{kind.upper()}]", redacted)
        if count:
            findings.append(RedactionFinding(kind=kind, count=count))

    return redacted, findings


def detect_prompt_injection(text: str) -> list[str]:
    flags = []
    for name, pattern in INJECTION_PATTERNS.items():
        if pattern.search(text):
            flags.append(name)
    return flags


def validate_tool_call(tool_name: str, arguments: dict[str, Any]) -> None:
    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool is not allowlisted: {tool_name}")

    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")

    for key, value in arguments.items():
        if not isinstance(key, str):
            raise ValueError("Tool argument keys must be strings.")
        if isinstance(value, str) and len(value) > MAX_TOOL_STRING_LENGTH:
            raise ValueError(f"Tool argument '{key}' is too long.")
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and len(item) > MAX_TOOL_STRING_LENGTH:
                    raise ValueError(f"Tool argument '{key}' contains an item that is too long.")


def security_report(text: str) -> dict[str, Any]:
    redacted, findings = redact_pii(text)
    injection_flags = detect_prompt_injection(text)
    return {
        "redacted_text": redacted,
        "pii_findings": [finding.__dict__ for finding in findings],
        "prompt_injection_flags": injection_flags,
        "allowed_tools": sorted(ALLOWED_TOOLS),
        "status": "review" if injection_flags else "clear",
    }

