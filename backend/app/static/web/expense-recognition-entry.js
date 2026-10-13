/* Recognition intent uses the existing draft lease and command acknowledgement owner. */
(function (window, document) {
  "use strict";
  const definitions = {
    expensetext: {label: "小票文字", path: "recognize-text", operation: "recognize_text", extra: ["raw_text"]},
    expenseocr: {label: "原件识别", path: "ocr/retry", operation: "retry_ocr", extra: []},
  };
  const scalars = ["ledger_id", "expense_id", "expected_row_version", "idempotency_key", "draft_ref"];
  const validRef = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const names = definition => [...scalars, ...definition.extra, "return_context"];
  function read(form, definition) {
    return {...Object.fromEntries([...scalars, ...definition.extra].map(name => [name, form.elements.namedItem(name).value])),
      return_context: JSON.stringify(Object.fromEntries([...form.elements].filter(input => input.name.startsWith("return_")).map(input => [input.name, input.value])))};
  }
  function href(family, record, scope, form) {
    const values = record?.values || read(form, definitions[family]);
    const next = new URL("/web/expenses/" + values.expense_id + "/" + definitions[family].path, window.location.href);
    next.search = new URLSearchParams({ledger_id: scope.ledgerId, ...JSON.parse(values.return_context)});
    if (record) next.hash = family + "-edit-" + record.clientRef;
    else next.searchParams.set("new_" + family, "1");
    return next.href;
  }
  function mount(form, family, definition) {
    const continuity = window.TicketboxPlanEntry.mount(form, {
      family, label: definition.label, list: "/web/pending", create: names(definition), edit: names(definition),
      idField: "expense_id", titleField: "expense_id", commandKeyField: "idempotency_key", draftRefField: "draft_ref",
      reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-recognition-submit]",
      pendingLabel: "核实这次识别结果", inactiveMessage: "账单当前无法发起新的识别。原请求仍保留，可核实已发出的结果。",
      read: current => read(current, definition), present: () => {},
      restore(current, saved) {
        [...scalars, ...definition.extra].forEach(name => { current.elements.namedItem(name).value = saved[name]; });
        for (const input of [...current.elements].filter(input => input.name.startsWith("return_"))) input.remove();
        for (const [name, value] of Object.entries(JSON.parse(saved.return_context))) {
          const input = document.createElement("input"); input.type = "hidden"; input.name = name; input.value = value; current.append(input);
        }
      },
      href: (record, scope, current) => href(family, record, scope, current),
      body(body, saved) {
        [...scalars, ...definition.extra].forEach(name => body.set(name, saved[name]));
        for (const [name, value] of Object.entries(JSON.parse(saved.return_context))) body.set(name, value);
      },
      receiptMatches: (receipt, saved) => receipt?.accepted === true && receipt.expense_id === Number(saved.expense_id) &&
        receipt.operation === definition.operation && receipt.request_key === saved.idempotency_key,
      acceptsDestination: (next, saved) => next.pathname === "/web/expenses/" + saved.expense_id + "/edit",
      updatePresentation(current, state) {
        const changed = current.dataset[family + "RowVersion"] !== current.elements.expected_row_version.value;
        if (!changed && !state.rejected) {
          current.querySelector("[data-" + family + "-review]").hidden = true;
          current.querySelector("[data-" + family + "-review-note]").hidden = true;
        }
        const values = read(current, definition), link = current.querySelector("[data-recognition-current]");
        const next = new URL(current.querySelector("[data-recognition-return]").href);
        next.searchParams.set("return_review_ref", values.draft_ref);
        next.searchParams.set("return_review_expense_id", values.expense_id);
        next.searchParams.set("return_review_family", family);
        link.href = next.href; link.hidden = !state.retained;
      },
    });
    form.expenseReviewContinuity = continuity;
    window.TicketboxWeb.preserveReviewForms([form]);
  }
  function appendShelf(scope, list) {
    for (const [family, definition] of Object.entries(definitions)) {
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-edit-draft:v1:",
        fields: [...names(definition), "amount_placeholder", "amount_inputmode"], validRef});
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(family, record, scope);
        link.textContent = definition.label + " · 账单 " + record.values.expense_id + " · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "原结果待核对");
        item.append(link); list.append(item);
      }
    }
  }
  window.TicketboxExpenseRecognition = {appendShelf};
  for (const [family, definition] of Object.entries(definitions)) {
    document.querySelectorAll("form[data-" + family + "-draft-scope]").forEach(form => mount(form, family, definition));
  }
})(window, document);
