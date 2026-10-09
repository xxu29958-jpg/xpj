/* A comparison decision retains the original pair, versions, identity and command. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "expense_id", "task_id", "action", "label", "idempotency_key", "draft_ref",
    "expected_row_version", "original_expense_id", "expected_original_row_version", "return_duplicate_expense_id"];
  const prefix = "ticketbox:duplicatechoice-edit-draft:v1:";
  function read(form) { return Object.fromEntries(names.map(name => [name, form.elements.namedItem(name).value])); }
  function href(record, scope) {
    if (!record) return new URL("/web/duplicates?" + new URLSearchParams({ledger_id: scope.ledgerId}), window.location.href).href;
    const saved = record.values;
    return new URL("/web/duplicates/" + saved.expense_id + "/decision?" + new URLSearchParams({ledger_id: saved.ledger_id,
      action: saved.action, original_expense_id: saved.original_expense_id}) + "#duplicatechoice-edit-" + record.clientRef, window.location.href).href;
  }
  function body(data, saved) {
    names.forEach(name => data.set(name, saved[name]));
    data.set("keep_idempotency_key", saved.idempotency_key); data.set("return_to", "duplicates");
  }
  function present(form, state, confirmation) {
    const submit = form.querySelector("[data-duplicatechoice-submit]");
    if (state.phase === "editing" && confirmation) submit.dataset.confirm = confirmation;
    else delete submit.dataset.confirm;
    const forms = [...form.closest(".duplicate-decision").querySelectorAll("form[data-duplicatechoice-plan-id]")];
    const pending = forms.some(current => current.dataset.duplicatechoiceDraftPhase && current.dataset.duplicatechoiceDraftPhase !== "editing");
    if (pending) forms.filter(current => current.dataset.duplicatechoiceDraftPhase === "editing")
      .forEach(current => { current.querySelector("[data-duplicatechoice-submit]").disabled = true; });
  }
  document.querySelectorAll("form[data-duplicatechoice-draft-scope]").forEach(form => {
    const confirmation = form.querySelector("[data-duplicatechoice-submit]").dataset.confirm;
    window.TicketboxPlanEntry.mount(form, {family: "duplicatechoice", label: "相似账单决定", list: "/web/duplicates",
      create: names, edit: names, idField: "task_id", titleField: "label", commandKeyField: "idempotency_key",
      draftRefField: "draft_ref", multiple: true, submitSelector: "[data-duplicatechoice-submit]",
      pendingLabel: "核实这次决定", reviewRequiresRejection: true,
      inactiveMessage: "两笔账单的状态已变化。原决定仍保留；已发出的提交可核实原结果。",
      read, href, body, action: saved => "/web/duplicates/" + saved.expense_id + "/" + saved.action,
      updatePresentation: (current, state) => present(current, state, confirmation),
      receiptMatches: (receipt, saved) => receipt?.accepted === true && receipt.action === saved.action &&
        receipt.expense_id === Number(saved.expense_id) && receipt.decision_key === saved.idempotency_key &&
        (saved.action !== "reject-original" || receipt.original_expense_id === Number(saved.original_expense_id)),
    });
  });
  document.querySelectorAll("[data-duplicatechoice-scope]").forEach(element => {
    try {
      const scope = JSON.parse(element.dataset.duplicatechoiceScope), list = element.querySelector("ul");
      const store = window.TicketboxDraftStore.createStore({prefix, fields: [...names, "amount_placeholder", "amount_inputmode"],
        validRef: /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i});
      list.replaceChildren();
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(record); link.dataset.duplicatechoiceRef = record.clientRef;
        link.textContent = record.values.label + " · " + (!store.matches(record.scope, scope) ? "原身份，待核对" :
          record.serverResult === "rejected" ? "原决定未接受，待核对" : "原决定结果待核实");
        item.append(link); list.append(item);
      }
      element.hidden = !list.childElementCount;
    } catch (_) {
      element.hidden = false; element.querySelector("ul").textContent = "暂时无法读取保留的决定，请恢复浏览器存储后继续。";
    }
  });
})(window, document);
