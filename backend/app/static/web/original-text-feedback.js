/* Optional pixel feedback travels with the existing expense command and durable draft. */
(function () {
  "use strict";
  const metadata = new WeakMap();
  const editable = panel => !panel.closest("form").dataset.expensereviewDraftPhase || panel.closest("form").dataset.expensereviewDraftPhase === "editing";
  const values = form => JSON.parse(form.elements.namedItem("original_text_feedback")?.value || "[]");
  function draft(panel) {
    return values(panel.closest("form")).find(value => value.field === panel.dataset.originalFeedback) || {
      field: panel.dataset.originalFeedback, image_sha256: panel.dataset.imageSha256, width: 0, height: 0,
      coordinate_space: "exif-transposed-pixels", location_state: "unlocated", verbatim_text: "", issue: "transcription",
      role: panel.dataset.originalFeedback === "amount_cents" ? "payment" : panel.dataset.originalFeedback === "expense_time" ? "transaction" : panel.dataset.originalFeedback,
      text_verified: false, ...metadata.get(panel)
    };
  }
  function render(panel) {
    const value = draft(panel), noText = ["unreadable", "cropped", "absent"].includes(value.issue);
    panel.querySelectorAll("[data-feedback-input]").forEach(input => {
      const key = input.dataset.feedbackInput;
      if (input.type === "checkbox") input.checked = key === "region_verified" ? value.location_state === "verified_region" : value[key];
      else input.value = value[key];
    });
    panel.querySelector("[data-feedback-text-label]").hidden = noText;
    panel.querySelector("[data-feedback-text-check]").hidden = noText;
    panel.querySelector("[data-feedback-region-check]").hidden = !value.box;
    panel.querySelector("[data-feedback-location]").textContent = {
      unlocated: "尚未定位，可以直接保存。", coarse_point: "仅记录大致位置。",
      suggested_region: "范围尚待核对。", verified_region: "已核对范围与原文对应。"
    }[value.location_state];
  }
  function write(panel, value) {
    if (!editable(panel)) return;
    const form = panel.closest("form"), list = values(form).filter(item => item.field !== panel.dataset.originalFeedback);
    if (value) list.push(value);
    let input = form.elements.namedItem("original_text_feedback");
    if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = "original_text_feedback"; form.append(input); }
    input.value = list.length ? JSON.stringify(list) : "";
    input.dispatchEvent(new Event("input", {bubbles: true}));
    render(panel);
    panel.querySelector("[data-feedback-status]").textContent = value ? "这处原文反馈将随本次保存记录。" : "已移除本次原文反馈。";
  }
  async function prepare(panel) {
    const status = panel.querySelector("[data-feedback-status]"), form = panel.closest("form");
    if (metadata.has(panel)) return;
    status.textContent = "正在核对原图…";
    try {
      const source = await window.TicketboxRecognitionSource.original(form, panel.dataset.sourceImageHref, panel.dataset.imageSha256);
      metadata.set(panel, source);
      const current = values(form).find(value => value.field === panel.dataset.originalFeedback);
      if (current && current.width === 0 && current.image_sha256 === source.image_sha256) write(panel, {...current, ...source});
      else status.textContent = current ? "这处原文反馈将随本次保存记录。" : "可直接记录原文，定位可以跳过。";
    } catch (_) { status.textContent = "原图暂时无法核对。填写仍保留；请稍后重试，或移除此反馈后保存账目。"; }
  }
  document.addEventListener("toggle", event => {
    const panel = event.target;
    if (panel.matches?.("[data-original-feedback]") && panel.open) { render(panel); prepare(panel); }
  }, true);
  document.addEventListener("input", event => {
    const input = event.target, panel = input.closest("[data-original-feedback]");
    if (!panel || !input.dataset.feedbackInput || !editable(panel)) return;
    const value = draft(panel), key = input.dataset.feedbackInput;
    if (key === "region_verified") value.location_state = input.checked ? "verified_region" : "suggested_region";
    else value[key] = input.type === "checkbox" ? input.checked : input.value;
    if (key === "verbatim_text" || key === "issue") value.text_verified = false;
    if (["unreadable", "cropped", "absent"].includes(value.issue)) { value.verbatim_text = ""; value.text_verified = false; }
    write(panel, value);
  });
  document.addEventListener("click", event => {
    const panel = event.target.closest("[data-original-feedback]");
    if (!panel || !editable(panel)) return;
    if (event.target.closest("[data-feedback-remove]")) { write(panel, null); panel.open = false; }
    if (event.target.closest("[data-feedback-locate]")) {
      window.TicketboxRecognitionSource.locate(panel.closest("form"), panel.dataset.sourceImageHref, draft(panel), value => write(panel, value));
    }
  });
  function restore(form) {
    const list = values(form);
    form.querySelectorAll("[data-original-feedback]").forEach(panel => {
      if (list.some(value => value.field === panel.dataset.originalFeedback)) panel.open = true;
      render(panel);
    });
  }
  document.addEventListener("ticketbox:original-feedback-state", event => restore(event.target));
  document.querySelectorAll("form").forEach(form => { if (form.querySelector("[data-original-feedback]")) restore(form); });
  document.addEventListener("submit", event => {
    const form = event.target;
    if (form.dataset.expensereviewDraftPhase && form.dataset.expensereviewDraftPhase !== "editing") return;
    const invalid = values(form).find(value => value.width < 1 || value.height < 1 ||
      (!["unreadable", "cropped", "absent"].includes(value.issue) && !value.verbatim_text.trim()));
    if (!invalid) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const panel = form.querySelector(`[data-original-feedback="${invalid.field}"]`);
    if (panel) { panel.open = true; panel.querySelector("[data-feedback-status]").textContent = "原文或原图尚未核对完整。请补全、等待原图载入，或移除此反馈后保存账目。"; panel.scrollIntoView({block: "center"}); }
  }, true);
})();
