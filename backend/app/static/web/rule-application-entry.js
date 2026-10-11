/* Original application intents reuse the browser command store and its binding/lease owner. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "apply_status", "preview_confirmed", "preview_token", "idempotency_key", "draft_ref",
    "original_scanned", "original_changed"];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function href(record, scope, form) {
    const target = record?.values.apply_status || form.elements.apply_status.value;
    const next = new URL("/web/rules", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    if (record) {
      next.searchParams.set("view", "application"); next.searchParams.set("target", target);
      next.hash = "ruleapplication-create-" + record.clientRef;
    } else {
      next.searchParams.set(target === "confirmed" ? "confirmed_preview" : "apply_preview", "1");
      next.searchParams.set("new_ruleapplication", "1");
    }
    return next.href;
  }
  document.querySelectorAll("form[data-rule-application]").forEach(form => {
    if (!form.dataset.ruleapplicationDraftScope) return;
    window.TicketboxPlanEntry.mount(form, {family: "ruleapplication", label: "规则应用", list: "/web/rules",
      create: fields, edit: fields, idField: "apply_status", titleField: "apply_status",
      commandKeyField: "idempotency_key", draftRefField: "draft_ref", pendingLabel: "核实原应用",
      reviewRequiresRejection: true, href,
      present: (current, saved) => { current.action = "/web/rules/apply-" + saved.apply_status; },
      updatePresentation: (current, state) => {
        const pending = state.phase !== "editing";
        document.querySelector("[data-ruleapplication-impact]").hidden = pending;
        document.querySelector("[data-ruleapplication-heading]").textContent = pending ? "核实这次规则应用" : "这次会改哪些账单";
        document.querySelector("[data-ruleapplication-new]").hidden = pending;
        const original = current.querySelector("[data-ruleapplication-original]");
        original.hidden = !pending;
        if (!pending && (!current.elements.preview_token.value || Number(current.elements.original_changed.value) === 0)) {
          current.querySelector('[type="submit"]:not([name="review_new"])').disabled = true;
        }
        original.textContent = "原预览扫描 " + current.elements.original_scanned.value + " 笔" +
          (current.elements.apply_status.value === "confirmed" ? "已确认" : "待确认") + "，预计改写 " +
          current.elements.original_changed.value + " 笔。";
      },
      receiptMatches: (receipt, saved) => receipt?.command_key === saved.idempotency_key &&
        Number.isSafeInteger(receipt.changed_count) && receipt.changed_count >= 0 &&
        (receipt.changed_count === 0 ? receipt.application_public_id === null : uuid.test(receipt.application_public_id)) &&
        (saved.apply_status === "confirmed" ? receipt.dry_run === false : Number.isSafeInteger(receipt.pending_scanned)),
      acceptsDestination: next => next.pathname === "/web/rules" && next.searchParams.get("view") === "history",
    });
  });
  if (document.querySelector("form[data-rule-application]")) return;
  document.querySelectorAll("[data-ruleapplication-draft-shelf]").forEach(shelf => {
    try {
      const scope = JSON.parse(shelf.dataset.ruleScope), list = shelf.querySelector("ul");
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:ruleapplication-create-draft:v1:",
        fields: [...fields, "amount_placeholder", "amount_inputmode"], validRef: uuid});
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(record, scope);
        link.textContent = (record.values.apply_status === "confirmed" ? "已确认" : "待确认") + "账单规则应用 · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : "原结果待核对");
        item.append(link); list.append(item);
      }
      shelf.hidden = !list.childElementCount;
    } catch (_) { /* Retained commands remain in the existing store when browser storage is unavailable. */ }
  });
})(window, document);
