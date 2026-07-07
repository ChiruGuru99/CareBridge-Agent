const state = {
  plan: null,
};

const els = {
  caseText: document.querySelector("#caseText"),
  location: document.querySelector("#location"),
  householdSize: document.querySelector("#householdSize"),
  language: document.querySelector("#language"),
  sampleButton: document.querySelector("#sampleButton"),
  runButton: document.querySelector("#runButton"),
  status: document.querySelector("#status"),
  urgency: document.querySelector("#urgency"),
  panels: {
    plan: document.querySelector("#plan"),
    resources: document.querySelector("#resources"),
    security: document.querySelector("#security"),
    trace: document.querySelector("#trace"),
  },
};

const sampleText = "My work hours were cut, rent is due Friday, and I need groceries for two kids. My phone is 512-555-0188 and email is alex@example.com.";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function chip(value, className = "need") {
  return `<span class="chip ${className}">${escapeHtml(value.replaceAll("_", " "))}</span>`;
}

function setStatus(text) {
  els.status.textContent = text;
}

function emptyPanels() {
  Object.values(els.panels).forEach((panel) => {
    panel.innerHTML = '<div class="empty">Generate a plan to see agent output.</div>';
  });
}

function renderPlan(plan) {
  els.urgency.textContent = plan.urgency;
  els.urgency.className = `urgency ${plan.urgency === "urgent" ? "chip warn" : ""}`;

  els.panels.plan.innerHTML = `
    <div class="summary-grid">
      <div class="metric"><strong>Track</strong>${escapeHtml(plan.track)}</div>
      <div class="metric"><strong>Mode</strong>${escapeHtml(plan.mode === "gemini" ? `Gemini: ${plan.llm.model}` : "Offline fallback")}</div>
      <div class="metric"><strong>Location</strong>${escapeHtml(plan.location)}</div>
      <div class="metric"><strong>Household</strong>${escapeHtml(plan.household_size)}</div>
    </div>
    <h3>Detected Needs</h3>
    <div class="chip-row">${plan.needs.map((need) => chip(need)).join("")}</div>
    <h3>Sanitized Request</h3>
    <pre>${escapeHtml(plan.sanitized_request)}</pre>
    <h3>Action Steps</h3>
    ${plan.steps.map((step) => `
      <section class="step">
        <h3>${escapeHtml(step.title)}</h3>
        <ul>${step.actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ul>
      </section>
    `).join("")}
    <h3>Call Script</h3>
    <div class="script-box">${escapeHtml(plan.call_script)}</div>
    <h3>Safety Notes</h3>
    <div class="chip-row">${plan.safety_notes.map((note) => chip(note, note.includes("emergency") ? "danger" : "warn")).join("")}</div>
  `;

  els.panels.resources.innerHTML = plan.resources.map((resource) => `
    <article class="resource">
      <h3>${escapeHtml(resource.name)}</h3>
      <div class="resource-meta">${escapeHtml(resource.category)} &middot; ${escapeHtml(resource.city)}, ${escapeHtml(resource.state)} &middot; ${escapeHtml(resource.hours)}</div>
      <div>${escapeHtml(resource.services.join(", "))}</div>
      <div><strong>Phone:</strong> ${escapeHtml(resource.phone)}</div>
      <div><strong>Eligibility:</strong> ${escapeHtml(resource.eligibility)}</div>
      <a href="${escapeHtml(resource.website)}" target="_blank" rel="noreferrer">Open resource</a>
    </article>
  `).join("");

  const pii = plan.security.pii_findings.length
    ? plan.security.pii_findings.map((item) => chip(`${item.kind}: ${item.count}`, "warn")).join("")
    : chip("no PII found", "need");
  const injections = plan.security.prompt_injection_flags.length
    ? plan.security.prompt_injection_flags.map((item) => chip(item, "danger")).join("")
    : chip("no injection flags", "need");

  els.panels.security.innerHTML = `
    <section class="security-block">
      <h3>Status</h3>
      <div class="chip-row">${chip(plan.security.status, plan.security.status === "clear" ? "need" : "danger")}</div>
    </section>
    <section class="security-block">
      <h3>PII Redaction</h3>
      <div class="chip-row">${pii}</div>
    </section>
    <section class="security-block">
      <h3>Prompt Injection Scan</h3>
      <div class="chip-row">${injections}</div>
    </section>
    <section class="security-block">
      <h3>Tool Policy</h3>
      <p>${escapeHtml(plan.security.tool_policy)}</p>
    </section>
    <section class="security-block">
      <h3>LLM Runtime</h3>
      <div class="chip-row">
        ${chip(plan.llm.enabled ? `Gemini enabled: ${plan.llm.model}` : "offline fallback", plan.llm.enabled ? "warn" : "need")}
        ${plan.llm.errors.map((item) => chip(item, "danger")).join("")}
      </div>
    </section>
  `;

  els.panels.trace.innerHTML = plan.trace.map((item) => `
    <section class="trace-item">
      <h3>${escapeHtml(item.agent)}</h3>
      <p>${escapeHtml(item.summary)}</p>
      ${item.tool_calls.length ? `<code>${escapeHtml(item.tool_calls.join(" | "))}</code>` : ""}
    </section>
  `).join("");
}

async function generatePlan() {
  const text = els.caseText.value.trim();
  if (!text) {
    setStatus("Add a situation first");
    return;
  }

  setStatus("Running agents");
  els.runButton.disabled = true;
  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        location: els.location.value,
        household_size: Number(els.householdSize.value || 1),
        language: els.language.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Plan generation failed.");
    }
    state.plan = payload;
    renderPlan(payload);
    setStatus("Plan ready");
  } catch (error) {
    setStatus("Error");
    els.panels.plan.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  } finally {
    els.runButton.disabled = false;
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`#${tab.dataset.tab}`).classList.add("active");
  });
});

els.sampleButton.addEventListener("click", () => {
  els.caseText.value = sampleText;
  els.location.value = "Austin, TX";
  els.householdSize.value = "3";
  setStatus("Sample loaded");
});

els.runButton.addEventListener("click", generatePlan);
emptyPanels();
