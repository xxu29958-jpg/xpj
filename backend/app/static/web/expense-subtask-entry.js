/* Independent expense subtasks consume the existing draft lease and first-receipt protocol. */
(function (window, document) {
  "use strict";
  const definitions = {
    expenseitems: {kind: "items", label: "商品明细", columns: ["item_name", "item_kind", "item_quantity", "item_unit_price_yuan", "item_amount_yuan", "item_category"]},
    expensesplits: {kind: "splits", label: "家庭拆账", columns: ["split_member_id", "split_amount_yuan", "split_note"]},
    expenseack: {kind: "ack", label: "小票差异确认", columns: []},
  };
  const scalars = ["ledger_id", "expense_id", "expected_row_version", "idempotency_key", "draft_ref"];
  const names = [...scalars, "rows", "return_context"];
  const validRef = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function read(form, definition) {
    return {...Object.fromEntries(scalars.map(name => [name, form.elements.namedItem(name).value])),
      rows: JSON.stringify(definition.columns.length ? window.TicketboxWeb.readReviewRows(form, definition.columns) : []),
      return_context: JSON.stringify(Object.fromEntries([...form.elements].filter(input => input.name.startsWith("return_")).map(input => [input.name, input.value])))};
  }
  function href(family, record, scope, form) {
    const values = record?.values || read(form, definitions[family]);
    const next = new URL("/web/expenses/" + values.expense_id + "/edit", window.location.href);
    next.search = new URLSearchParams({ledger_id: scope.ledgerId, ...JSON.parse(values.return_context), confirmation_task: "1"});
    if (record) next.hash = family + "-edit-" + record.clientRef;
    else { next.searchParams.set("new_" + family, "1"); next.hash = "expense-" + (definitions[family].kind === "splits" ? "splits" : "items"); }
    return next.href;
  }
  function restore(form, saved, definition) {
    scalars.forEach(name => window.TicketboxWeb.putReviewField(form.elements.namedItem(name), saved[name]));
    for (const input of [...form.elements].filter(input => input.name.startsWith("return_"))) input.remove();
    for (const [name, value] of Object.entries(JSON.parse(saved.return_context))) {
      const input = document.createElement("input"); input.type = "hidden"; input.name = name; input.value = value; form.append(input);
    }
    if (definition.columns.length) window.TicketboxWeb.restoreReviewRows(form, definition.columns, saved.rows);
  }
  function mount(form, family, definition) {
    const continuity = window.TicketboxPlanEntry.mount(form, {
      family, label: definition.label, list: "/web/pending", create: names, edit: names,
      idField: "expense_id", titleField: "expense_id", commandKeyField: "idempotency_key", draftRefField: "draft_ref",
      multiple: true, repeated: definition.columns, reviewRequiresRejection: true, reviewWhileEditing: true,
      submitSelector: "[data-subtask-submit]", pendingLabel: "核实这次分项结果",
      inactiveMessage: "账单已离开待确认状态。原分项输入仍保留，已发出的提交可核实原结果。",
      read: current => read(current, definition), restore: (current, saved) => restore(current, saved, definition),
      href: (record, scope, current) => href(family, record, scope, current), present: () => {},
      body(body, saved) {
        scalars.forEach(name => body.set(name, saved[name]));
        for (const [name, value] of Object.entries(JSON.parse(saved.return_context))) body.set(name, value);
        JSON.parse(saved.rows).forEach(row => Object.entries(row).forEach(([name, value]) => body.append(name, value)));
      },
      receiptMatches: (receipt, saved) => receipt?.expense_id === Number(saved.expense_id) &&
        receipt.row_version === Number(saved.expected_row_version) + 1 &&
        Array.isArray(receipt[definition.kind === "splits" ? "splits" : "items"]),
      acceptsDestination: (next, saved) => next.pathname === "/web/expenses/" + saved.expense_id + "/edit",
      updatePresentation(current, state) {
        const pending = state.phase !== "editing";
        if (definition.kind === "ack") current.hidden = !state.retained && (!state.editable || current.dataset.expenseackArchived === "true");
        current.querySelector("[data-subtask-original]").hidden = !pending;
        const status = current.querySelector("[data-" + family + "-draft-status]");
        status.classList.toggle("product-feedback", pending);
        status.classList.toggle("product-feedback--warning", pending);
        const changed = current.dataset[family + "RowVersion"] !== current.elements.expected_row_version.value;
        if (!changed && !state.rejected) {
          current.querySelector("[data-" + family + "-review]").hidden = true;
          current.querySelector("[data-" + family + "-review-note]").hidden = true;
        }
        const itemTask = document.querySelector("[data-expenseitems-draft-phase]");
        const ack = document.querySelector("[data-expenseack-draft-phase]");
        const itemPending = itemTask && itemTask.dataset.expenseitemsDraftPhase !== "editing";
        if (itemPending && ack?.dataset.expenseackDraftPhase === "editing") ack.hidden = true;
        const mismatch = document.querySelector("[data-items-mismatch]");
        if (mismatch) mismatch.hidden = !!itemPending;
        const values = read(current, definition), link = current.querySelector("[data-subtask-current]");
        const next = new URL(href(family, {clientRef: values.draft_ref, values}, {ledgerId: values.ledger_id}));
        next.searchParams.delete("confirmation_task"); next.hash = "";
        next.searchParams.set("return_review_ref", values.draft_ref);
        next.searchParams.set("return_review_expense_id", values.expense_id);
        next.searchParams.set("return_review_family", family);
        link.href = next.href; link.hidden = !pending;
        const actions = current.querySelector("[data-subtask-actions]");
        actions.hidden = [...actions.children].every(action => action.hidden);
      },
    });
    // The existing departure guard asks only about input which the draft owner could not retain.
    form.expenseReviewContinuity = continuity;
  }
  function appendShelf(scope, list) {
    for (const [family, definition] of Object.entries(definitions)) {
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-edit-draft:v1:",
        fields: [...names, "amount_placeholder", "amount_inputmode"], validRef});
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(family, record, scope);
        link.textContent = definition.label + " · 账单 " + record.values.expense_id + " · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "原结果待核对");
        item.append(link); list.append(item);
      }
    }
  }
  window.TicketboxExpenseSubtasks = {appendShelf};
  for (const [family, definition] of Object.entries(definitions)) {
    document.querySelectorAll("form[data-" + family + "-draft-scope]").forEach(form => mount(form, family, definition));
  }
})(window, document);
