/* Rule definitions retain input through the existing browser draft and command receipt owner. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "rule_id", "keyword", "category", "priority", "amount_min_yuan", "amount_max_yuan",
    "home_currency_code", "source_contains", "tag_contains", "expected_row_version", "idempotency_key", "draft_ref",
    "return_category", "return_month"];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function href(record, scope, saved) {
    const next = new URL(saved.rule_id ? "/web/rules/" + encodeURIComponent(saved.rule_id) + "/edit" : "/web/rules", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    if (!saved.rule_id) next.searchParams.set("view", "new");
    for (const name of ["return_category", "return_month"]) if (saved[name]) next.searchParams.set(name, saved[name]);
    if (record) next.hash = "ruledefinition-" + (saved.rule_id ? "edit-" : "create-") + record.clientRef;
    else next.searchParams.set("new_ruledefinition", "1");
    return next.href;
  }
  function present(form, saved) {
    form.querySelectorAll("[data-rule-currency]").forEach(label => { label.textContent = saved.home_currency_code || "币种待确认"; });
    for (const name of ["amount_min_yuan", "amount_max_yuan", "source_contains", "tag_contains"]) {
      const input = form.elements.namedItem(name);
      if (saved[name]) input.closest("details").open = true;
    }
    if (saved.amount_inputmode) form.elements.amount_max_yuan.inputMode = saved.amount_inputmode;
  }
  function mount(form) {
    if (!form.dataset.ruledefinitionDraftScope) return;
    window.TicketboxPlanEntry.mount(form, {family: "ruledefinition", label: "规则定义", list: "/web/rules",
      create: fields, edit: fields, idField: "rule_id", titleField: "keyword", amount: "amount_min_yuan",
      commandKeyField: "idempotency_key", draftRefField: "draft_ref", pendingLabel: "核实原提交",
      reviewRequiresRejection: true, reviewWhileEditing: !!form.dataset.ruledefinitionPlanId, present,
      inactiveMessage: "原规则暂不能修改。原输入仍保留；已发出的提交可核实原结果。",
      href: (record, scope, current) => href(record, scope, record?.values || Object.fromEntries(fields.map(name => [name, current.elements.namedItem(name)?.value || ""]))),
      receiptMatches: (receipt, saved) => Number.isSafeInteger(receipt?.id) && receipt.id > 0 &&
        receipt.row_version === (saved.rule_id ? Number(saved.expected_row_version) + 1 : 1) &&
        (!saved.rule_id || receipt.id === Number(saved.rule_id)) && typeof receipt.keyword === "string" && typeof receipt.category === "string",
      acceptsDestination: (next, saved) => next.pathname === "/web/rules" || !!saved.rule_id && !!saved.return_category &&
        next.pathname === "/web/categories" && next.searchParams.get("inspect") === saved.return_category,
    });
  }
  function renderShelf(shelf) {
    if (document.querySelector("form[data-rule-definition]")) return;
    try {
      const scope = JSON.parse(shelf.dataset.ruleScope), list = shelf.querySelector("ul");
      for (const kind of ["create", "edit"]) {
        const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:ruledefinition-" + kind + "-draft:v1:",
          fields: [...fields, "amount_placeholder", "amount_inputmode"], validRef: uuid});
        for (const record of store.list(scope)) {
          const item = document.createElement("li"), link = document.createElement("a");
          link.href = href(record, scope, record.values);
          link.textContent = (record.values.keyword || "未命名规则") + " · " + (!store.matches(record.scope, scope) ?
            "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "原提交待核对");
          item.append(link); list.append(item);
        }
      }
      shelf.hidden = !list.childElementCount;
    } catch (_) { /* The directory remains readable; retained drafts stay in the existing store. */ }
  }
  document.querySelectorAll("form[data-rule-definition]").forEach(mount);
  document.querySelectorAll("[data-ruledefinition-draft-shelf]").forEach(renderShelf);
})(window, document);
