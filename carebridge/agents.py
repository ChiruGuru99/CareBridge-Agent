from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from carebridge.gemini_client import GeminiClient, GeminiError
from carebridge.mcp_client import ResourceMCPClient
from carebridge.resource_directory import get_preparation_checklist, search_resources
from carebridge.security import detect_prompt_injection, redact_pii, validate_tool_call


LOGGER = logging.getLogger(__name__)

NEED_KEYWORDS = {
    "food": ["food", "meal", "groceries", "hungry", "pantry", "snap", "wic"],
    "housing": ["rent", "eviction", "shelter", "housing", "utility", "homeless", "landlord"],
    "healthcare": ["doctor", "clinic", "medicine", "medication", "health", "prescription", "hospital"],
    "mental_health": ["anxious", "depressed", "panic", "suicide", "self-harm", "crisis", "unsafe"],
    "legal": ["court", "legal", "lawyer", "notice", "rights", "eviction filed"],
    "transportation": ["ride", "bus", "transport", "appointment", "car", "transit"],
    "employment": ["job", "work", "hours", "unemployed", "resume", "training"],
    "childcare": ["child", "kids", "childcare", "daycare", "school"],
}

URGENCY_KEYWORDS = ["tonight", "today", "emergency", "unsafe", "violence", "eviction", "suicide", "self-harm", "no food"]


@dataclass
class AgentTrace:
    agent: str
    summary: str
    tool_calls: list[str] = field(default_factory=list)


@dataclass
class CaseContext:
    raw_text: str
    location: str
    household_size: int = 1
    language: str = "English"
    redacted_text: str = ""
    pii_findings: list[dict[str, Any]] = field(default_factory=list)
    injection_flags: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    urgency: str = "standard"
    resources: list[dict[str, Any]] = field(default_factory=list)
    checklists: dict[str, list[str]] = field(default_factory=dict)
    safety_flags: list[str] = field(default_factory=list)
    trace: list[AgentTrace] = field(default_factory=list)
    llm_enabled: bool = False
    llm_model: str = ""
    llm_key_source: str = "not_configured"
    llm_errors: list[str] = field(default_factory=list)


class IntakeAgent:
    name = "IntakeAgent"

    def run(self, context: CaseContext) -> None:
        redacted, findings = redact_pii(context.raw_text)
        context.redacted_text = redacted.strip()
        context.pii_findings = [finding.__dict__ for finding in findings]
        context.trace.append(
            AgentTrace(
                agent=self.name,
                summary=f"Redacted {sum(item['count'] for item in context.pii_findings)} direct identifier(s).",
            )
        )


class SecurityGuardAgent:
    name = "SecurityGuardAgent"

    def run(self, context: CaseContext) -> None:
        context.injection_flags = detect_prompt_injection(context.raw_text)
        status = "flagged prompt-injection risk" if context.injection_flags else "cleared prompt-injection scan"
        context.trace.append(AgentTrace(agent=self.name, summary=status))

    def validate_tool(self, tool_name: str, arguments: dict[str, Any]) -> None:
        validate_tool_call(tool_name, arguments)


class NeedClassifierAgent:
    name = "NeedClassifierAgent"

    def __init__(self, llm: GeminiClient | None = None) -> None:
        self.llm = llm

    def run(self, context: CaseContext) -> None:
        if self.llm and self.llm.configured:
            try:
                self._run_with_gemini(context)
                return
            except GeminiError as exc:
                context.llm_errors.append(str(exc))
                LOGGER.warning("Gemini classification failed: %s", exc)
                context.trace.append(
                    AgentTrace(
                        agent=self.name,
                        summary=f"Gemini classification failed; used deterministic fallback. Error: {exc}",
                    )
                )
        self._run_deterministic(context)

    def _run_with_gemini(self, context: CaseContext) -> None:
        allowed_needs = sorted(NEED_KEYWORDS.keys()) + ["general_navigation"]
        result = self.llm.generate_json(
            system_instruction=(
                "You are the need-classification agent in a privacy-first social-support navigator. "
                "Use only the sanitized user request. Return JSON only with keys: needs, urgency, rationale. "
                "needs must be an array using only the allowed labels. urgency must be standard or urgent."
            ),
            user_payload={
                "sanitized_request": context.redacted_text,
                "location": context.location,
                "household_size": context.household_size,
                "allowed_needs": allowed_needs,
                "urgent_if": URGENCY_KEYWORDS,
            },
        )
        needs = [need for need in result.get("needs", []) if need in allowed_needs]
        context.needs = needs or ["general_navigation"]
        context.urgency = "urgent" if result.get("urgency") == "urgent" else "standard"
        context.trace.append(
            AgentTrace(
                agent=self.name,
                summary=f"Gemini classified needs as {', '.join(context.needs)} with {context.urgency} urgency.",
                tool_calls=[f"gemini.generateContent:{self.llm.model}"],
            )
        )

    def _run_deterministic(self, context: CaseContext) -> None:
        text = context.redacted_text.lower()
        needs = []
        for need, keywords in NEED_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                needs.append(need)
        if not needs:
            needs = ["general_navigation"]
        context.needs = needs
        context.urgency = "urgent" if any(keyword in text for keyword in URGENCY_KEYWORDS) else "standard"
        context.trace.append(
            AgentTrace(
                agent=self.name,
                summary=f"Classified needs as {', '.join(context.needs)} with {context.urgency} urgency.",
            )
        )


class ResourceMatcherAgent:
    name = "ResourceMatcherAgent"

    def __init__(self, security: SecurityGuardAgent) -> None:
        self.security = security

    def run(self, context: CaseContext) -> None:
        tool_calls = []
        search_args = {
            "query": context.redacted_text,
            "location": context.location,
            "needs": context.needs,
            "limit": 6,
        }
        self.security.validate_tool("search_resources", search_args)

        try:
            with ResourceMCPClient() as client:
                context.resources = client.call_tool("search_resources", search_args)
                tool_calls.append("mcp.search_resources")
                for need in context.needs:
                    checklist_args = {"category": need}
                    self.security.validate_tool("get_preparation_checklist", checklist_args)
                    context.checklists[need] = client.call_tool("get_preparation_checklist", checklist_args)
                    tool_calls.append(f"mcp.get_preparation_checklist:{need}")
        except Exception:
            context.resources = search_resources(**search_args)
            for need in context.needs:
                context.checklists[need] = get_preparation_checklist(need)
            tool_calls.append("direct_fallback.resource_directory")

        context.trace.append(
            AgentTrace(
                agent=self.name,
                summary=f"Matched {len(context.resources)} resource(s) using local directory tools.",
                tool_calls=tool_calls,
            )
        )


class SafetyReviewAgent:
    name = "SafetyReviewAgent"

    def run(self, context: CaseContext) -> None:
        text = context.redacted_text.lower()
        flags = []
        if any(term in text for term in ["suicide", "self-harm", "hurt myself"]):
            flags.append("If there is immediate danger, call emergency services now. In the U.S., call or text 988 for crisis support.")
        if any(term in text for term in ["violence", "unsafe at home", "abuse"]):
            flags.append("If someone is in immediate danger, call emergency services. For domestic violence support in the U.S., call 1-800-799-7233.")
        if any(term in text for term in ["chest pain", "overdose", "can't breathe", "cannot breathe"]):
            flags.append("This may be a medical emergency. Call emergency services now.")
        if not flags:
            flags.append("This is navigation support, not medical, legal, financial, or emergency advice.")
        context.safety_flags = flags
        context.trace.append(AgentTrace(agent=self.name, summary=f"Added {len(flags)} safety note(s)."))


class PlanWriterAgent:
    name = "PlanWriterAgent"

    def __init__(self, llm: GeminiClient | None = None) -> None:
        self.llm = llm

    def run(self, context: CaseContext) -> dict[str, Any]:
        if self.llm and self.llm.configured:
            try:
                return self._run_with_gemini(context)
            except GeminiError as exc:
                context.llm_errors.append(str(exc))
                LOGGER.warning("Gemini plan generation failed: %s", exc)
                context.trace.append(
                    AgentTrace(
                        agent=self.name,
                        summary=f"Gemini plan generation failed; used deterministic fallback. Error: {exc}",
                    )
                )
        return self._run_deterministic(context)

    def _run_with_gemini(self, context: CaseContext) -> dict[str, Any]:
        result = self.llm.generate_json(
            system_instruction=(
                "You are the plan-writing agent in CareBridge, a privacy-first community support navigator. "
                "Use the sanitized request and the supplied MCP resource results. Do not invent phone numbers, "
                "websites, eligibility rules, or resource names. Return JSON only with keys: summary, steps, "
                "call_script. steps must be an array of objects with title and actions. Keep advice practical, "
                "nonjudgmental, and clear that this is navigation support, not professional advice."
            ),
            user_payload={
                "sanitized_request": context.redacted_text,
                "location": context.location,
                "household_size": context.household_size,
                "language": context.language,
                "needs": context.needs,
                "urgency": context.urgency,
                "resources": context.resources[:6],
                "checklists": context.checklists,
                "safety_notes": context.safety_flags,
            },
        )
        steps = normalize_steps(result.get("steps"))
        if not steps:
            raise GeminiError("Gemini plan did not include usable steps.")

        plan = self._base_plan(
            context=context,
            summary=str(result.get("summary") or "A privacy-preserving action plan for community support navigation."),
            steps=steps,
            call_script=str(result.get("call_script") or default_call_script(context)),
            mode="gemini",
        )
        context.trace.append(
            AgentTrace(
                agent=self.name,
                summary="Gemini generated the user-facing action plan from sanitized context and MCP results.",
                tool_calls=[f"gemini.generateContent:{self.llm.model}"],
            )
        )
        plan["trace"] = [trace.__dict__ for trace in context.trace]
        return plan

    def _run_deterministic(self, context: CaseContext) -> dict[str, Any]:
        documents = []
        for items in context.checklists.values():
            for item in items:
                if item not in documents:
                    documents.append(item)

        steps = [
            {
                "title": "Stabilize immediate needs",
                "actions": [
                    "If anyone is in immediate danger, contact emergency services first.",
                    "Call 211 and ask for same-day referrals for the highest-priority needs.",
                    f"Use the script below and mention household size: {context.household_size}.",
                ],
            },
            {
                "title": "Contact the top resources",
                "actions": [
                    f"Start with {resource['name']} ({resource['phone']})." for resource in context.resources[:3]
                ]
                or ["No direct resource matched. Start with 211 or a local community action agency."],
            },
            {
                "title": "Prepare documents",
                "actions": documents[:8] or ["Write a short timeline of what happened and what help is needed."],
            },
            {
                "title": "Track follow-up",
                "actions": [
                    "Record who was contacted, date, promised next step, and required paperwork.",
                    "If an appointment is unavailable, ask for a waitlist, partner referral, or emergency fund option.",
                ],
            },
        ]

        plan = self._base_plan(
            context=context,
            summary="A privacy-preserving action plan for community support navigation.",
            steps=steps,
            call_script=default_call_script(context),
            mode="deterministic_fallback",
        )
        context.trace.append(AgentTrace(agent=self.name, summary="Created user-facing action plan with deterministic fallback."))
        plan["trace"] = [trace.__dict__ for trace in context.trace]
        return plan

    def _base_plan(
        self,
        context: CaseContext,
        summary: str,
        steps: list[dict[str, Any]],
        call_script: str,
        mode: str,
    ) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "track": "Agents for Good",
            "summary": summary,
            "mode": mode,
            "llm": {
                "enabled": context.llm_enabled,
                "model": context.llm_model,
                "key_source": context.llm_key_source,
                "errors": context.llm_errors,
            },
            "sanitized_request": context.redacted_text,
            "location": context.location,
            "household_size": context.household_size,
            "language": context.language,
            "needs": context.needs,
            "urgency": context.urgency,
            "resources": context.resources,
            "steps": steps,
            "call_script": call_script,
            "safety_notes": context.safety_flags,
            "security": {
                "pii_findings": context.pii_findings,
                "prompt_injection_flags": context.injection_flags,
                "tool_policy": "Only local resource-directory tools are allowlisted.",
                "status": "review" if context.injection_flags else "clear",
            },
            "trace": [trace.__dict__ for trace in context.trace],
        }


def default_call_script(context: CaseContext) -> str:
    return (
        "Hi, I am looking for help with "
        + ", ".join(context.needs).replace("_", " ")
        + f" in {context.location}. My household size is {context.household_size}. "
        + "Can you tell me eligibility, documents needed, and the fastest next step?"
    )


def normalize_steps(raw_steps: Any) -> list[dict[str, Any]]:
    normalized = []
    if not isinstance(raw_steps, list):
        return normalized
    for item in raw_steps[:6]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        actions = item.get("actions")
        if not title or not isinstance(actions, list):
            continue
        clean_actions = [str(action).strip() for action in actions if str(action).strip()]
        if clean_actions:
            normalized.append({"title": title, "actions": clean_actions[:6]})
    return normalized


def run_carebridge_agent(payload: dict[str, Any]) -> dict[str, Any]:
    llm = GeminiClient()
    context = CaseContext(
        raw_text=str(payload.get("text", "")),
        location=str(payload.get("location", "National")),
        household_size=max(1, int(payload.get("household_size", 1) or 1)),
        language=str(payload.get("language", "English")),
        llm_enabled=llm.configured,
        llm_model=llm.model if llm.configured else "",
        llm_key_source=llm.key_source,
    )

    intake = IntakeAgent()
    security = SecurityGuardAgent()
    classifier = NeedClassifierAgent(llm)
    matcher = ResourceMatcherAgent(security)
    safety = SafetyReviewAgent()
    writer = PlanWriterAgent(llm)

    intake.run(context)
    security.run(context)
    if context.llm_enabled:
        context.trace.append(
            AgentTrace(
                agent="GeminiRuntime",
                summary=f"Gemini configured from {context.llm_key_source}; using model {context.llm_model}.",
            )
        )
    else:
        context.llm_errors.append("Gemini API key was not visible to this process. Set GEMINI_API_KEY or GOOGLE_API_KEY before starting the app.")
        context.trace.append(
            AgentTrace(
                agent="GeminiRuntime",
                summary="Gemini not configured; using offline deterministic fallback.",
            )
        )
    classifier.run(context)
    matcher.run(context)
    safety.run(context)
    return writer.run(context)


def pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
