/* One explicit event choice reuses the ordinary field controls and save command. */
(function () {
  "use strict";
  function groups(form) {
    const result = new Map();
    for (const button of form.querySelectorAll("[data-recognized-field], [data-recognized-time]")) {
      const candidate = JSON.parse(button.dataset.recognizedField || button.dataset.recognizedTime);
      if (!candidate.event_id || !candidate.event_selected || !candidate.can_apply || candidate.requires_year || button.disabled) continue;
      const key = JSON.stringify([candidate.source, candidate.evidence_public_id, candidate.event_id]);
      if (!result.has(key)) result.set(key, []);
      result.get(key).push({button, candidate, field: candidate.field || "expense_time"});
    }
    return result;
  }
  function render(container) {
    if (container.dataset.ready || !container.closest("form")) return;
    const form = container.closest("form");
    for (const [key, items] of groups(form)) {
      const fields = items.map(item => item.field);
      if (fields.length < 2 || new Set(fields).size !== fields.length) continue;
      const number = items[0].candidate.label.match(/第\d+笔/)?.[0];
      if (!number) continue;
      const button = document.createElement("button");
      button.type = "button"; button.className = "product-button product-button--secondary";
      button.dataset.recognizedEvent = key;
      button.textContent = `填入${number}的${fields.map(field => ({amount_cents: "金额", merchant: "商户", expense_time: "时间"})[field]).join("、")}`;
      container.append(button);
    }
    container.dataset.ready = "true";
  }
  function initialize() { document.querySelectorAll("[data-recognized-events]").forEach(render); }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-recognized-event]");
    if (!button || button.disabled || button.closest("fieldset")?.disabled) return;
    const items = groups(button.closest("form")).get(button.dataset.recognizedEvent) || [];
    // Choosing a transaction accepts a proposed bundle; it is not a field-role label.
    for (const item of items) {
      item.button.dataset.eventDraftApply = "true";
      try { item.button.click(); } finally { delete item.button.dataset.eventDraftApply; }
    }
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, {once: true});
  else initialize();
  document.addEventListener("toggle", event => {
    if (event.target.matches("[data-recognized-fields]")) initialize();
  }, true);
})();
