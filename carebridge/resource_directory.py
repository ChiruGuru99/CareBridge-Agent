from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "resources.json"


def load_resources(path: Path = DATA_PATH) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize(value: str) -> str:
    return " ".join(value.lower().replace(",", " ").split())


def location_tokens(location: str) -> set[str]:
    return set(normalize(location).split())


def score_resource(resource: dict[str, Any], query: str, location: str, needs: list[str]) -> int:
    score = 0
    query_text = normalize(query)
    loc_tokens = location_tokens(location)
    resource_text = normalize(
        " ".join(
            [
                resource.get("name", ""),
                resource.get("category", ""),
                resource.get("city", ""),
                resource.get("state", ""),
                resource.get("scope", ""),
                " ".join(resource.get("tags", [])),
                " ".join(resource.get("services", [])),
            ]
        )
    )

    for need in needs:
        if need and need.lower() in resource_text:
            score += 8
        if need in resource.get("tags", []):
            score += 4

    for token in query_text.split():
        if len(token) > 3 and token in resource_text:
            score += 1

    if resource.get("scope") == "national":
        score += 3

    city = normalize(resource.get("city", ""))
    state = normalize(resource.get("state", ""))
    if city and city in normalize(location):
        score += 8
    if state and state in loc_tokens:
        score += 6
    if resource.get("scope") == "remote":
        score += 2

    return score


def search_resources(query: str, location: str, needs: list[str] | None = None, limit: int = 6) -> list[dict[str, Any]]:
    needs = needs or []
    resources = load_resources()
    ranked = sorted(
        resources,
        key=lambda item: (score_resource(item, query, location, needs), item.get("name", "")),
        reverse=True,
    )
    return ranked[: max(1, min(limit, 10))]


CHECKLISTS = {
    "food": [
        "Household size and ages",
        "Photo ID if available",
        "Proof of address if available",
        "Any dietary restrictions",
    ],
    "housing": [
        "Lease or rent notice",
        "Utility bill or shutoff notice",
        "Proof of income or loss of income",
        "Court date or case number if eviction has been filed",
    ],
    "healthcare": [
        "Medication names and dosage",
        "Insurance card if available",
        "Recent discharge papers or prescriptions",
        "Preferred clinic or pharmacy",
    ],
    "mental_health": [
        "Immediate safety concerns",
        "Current support person to contact",
        "Medication or treatment history if comfortable sharing",
        "Preferred crisis line or provider",
    ],
    "legal": [
        "Deadlines and notices",
        "Court paperwork",
        "Relevant contracts or letters",
        "Timeline of events",
    ],
    "transportation": [
        "Appointment address and time",
        "Mobility needs",
        "Public transit access",
        "Backup contact",
    ],
    "employment": [
        "Recent pay stubs",
        "Resume or work history",
        "Availability",
        "Training interests",
    ],
    "childcare": [
        "Child ages",
        "School or care schedule",
        "Subsidy paperwork if available",
        "Emergency contacts",
    ],
}


def get_preparation_checklist(category: str) -> list[str]:
    return CHECKLISTS.get(category, ["Photo ID if available", "Proof of address if available", "A short summary of the situation"])

