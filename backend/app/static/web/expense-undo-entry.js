/* An undo keeps the rejected version it originally targeted, including after a later ignore. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "expense_id", "expected_row_version", "idempotency_key"];
  const names = [...fields, "return_context"];
  const prefix = "ticketbox:expenseundo-edit-draft:v1:";
  function read(form) {
    return {...Object.fromEntries(fields.map(name => [name, form.elements.namedItem(name).value])),
      return_context: JSON.stringify(Object.fromEntries([...form.elements].filter(input => input.name.startsWith("return_")).map(input => [input.name, input.value])))};
  }
  function href(record) {
    const saved = record.values;
    const next = new URL("/web/expenses/" + saved.expense_id + "/undo", window.location.href);
    next.search = new URLSearchParams({ledger_id: saved.ledger_id, undo_version: saved.expected_row_version,
      undo_key: saved.idempotency_key, ...JSON.parse(saved.return_context)});
    if (record.clientRef) next.hash = "expenseundo-edit-" + record.clientRef;
    return next.href;
  }
  function put(form, name, value) {
    let input = form.elements.namedItem(name);
    if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = name; form.append(input); }
    input.value = value;
  }
  function body(body, saved) {
    fields.forEach(name => body.set(name, saved[name]));
    for (const [name, value] of Object.entries(JSON.parse(saved.return_context))) body.set(name, value);
  }
  function mount(form) {
    window.TicketboxPlanEntry.mount(form, {family: "expenseundo", label: "撤销操作", list: "/web/pending",
      create: names, edit: names, idField: "idempotency_key", commandKeyField: "idempotency_key",
      submitSelector: "[data-expenseundo-submit]", pendingLabel: "核实这次撤销", reviewRequiresRejection: true,
      read, href: record => href(record || {values: read(form)}), body,
      action: saved => "/web/expenses/" + saved.expense_id + "/undo",
      restore(current, saved) {
        fields.forEach(name => put(current, name, saved[name]));
        for (const input of [...current.elements].filter(input => input.name.startsWith("return_"))) input.remove();
        for (const [name, value] of Object.entries(JSON.parse(saved.return_context))) put(current, name, value);
      },
      receiptMatches: (receipt, saved) => receipt?.id === Number(saved.expense_id) &&
        ["pending", "confirmed"].includes(receipt.status) && Number.isInteger(receipt.row_version),
      acceptsDestination: (next, saved) => next.pathname === "/web/pending" ||
        /^\/web\/recurring\/[^/]+\/occurrence$/.test(next.pathname) || next.pathname === "/web/expenses/" + saved.expense_id + "/edit",
    });
  }
  document.querySelectorAll("form[data-expenseundo-draft-scope]").forEach(mount);
  document.querySelectorAll("[data-expenseundo-scope]").forEach(element => {
    try {
      const store = window.TicketboxDraftStore.createStore({prefix, fields: [...names, "amount_placeholder", "amount_inputmode"],
        validRef: /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i});
      const scope = JSON.parse(element.dataset.expenseundoScope), list = element.querySelector("ul");
      list.replaceChildren();
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(record); link.dataset.expenseundoRef = record.clientRef;
        link.textContent = store.matches(record.scope, scope) ? "原撤销结果待核实" : "原身份的撤销操作，待核对";
        item.append(link); list.append(item);
      }
      element.hidden = !list.childElementCount;
    } catch (_) {
      element.hidden = false;
      element.querySelector("ul").textContent = "暂时读不到原撤销任务，请恢复浏览器存储后继续。";
    }
  });
})(window, document);
