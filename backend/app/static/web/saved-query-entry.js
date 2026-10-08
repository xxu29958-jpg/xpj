/* Saved-query forms use the existing bound draft lease and original receipt lifecycle. */
(function (window, document) {
  "use strict";
  const common = ["ledger_id", "public_id", "name", "expected_row_version", "idempotency_key", "draft_ref"];
  const definitions = {
    savedquery: [...common, "month_mode", "month", "filter", "tag_public_id", "home_currency_code", "query_text", "category"],
    querydelete: common,
  };
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function href(family, record, scope, saved) {
    const next = new URL("/web/saved-views", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    if (saved.public_id) next.searchParams.set(family === "querydelete" ? "delete" : "edit", saved.public_id);
    else next.searchParams.set("create", "true");
    if (record) next.hash = family + (saved.public_id ? "-edit-" : "-create-") + record.clientRef;
    else next.searchParams.set("new_" + family, "1");
    return next.href;
  }
  function mount(form, family, fields) {
    if (!form.dataset[family + "DraftScope"]) return;
    function present() {
      if (family !== "savedquery") return;
      form.querySelector("[data-query-fixed-month]").hidden = form.elements.month_mode.value === "current" || !!form.elements.filter.value;
      const range = form.elements.filter;
      form.querySelector("[data-query-basis]").textContent = range.selectedOptions[0].textContent + " · " + form.elements.home_currency_code.value;
      if (range.value) form.querySelector("[data-query-presentation]").open = true;
    }
    present();
    form.addEventListener("change", present);
    window.TicketboxPlanEntry.mount(form, {family, label: family === "querydelete" ? "查询删除任务" : "常用查询",
      list: "/web/saved-views", create: fields, edit: fields, titleField: "name",
      present,
      commandKeyField: "idempotency_key", draftRefField: "draft_ref", pendingLabel: "核实原提交",
      reviewRequiresRejection: true, reviewWhileEditing: !!form.dataset[family + "PlanId"],
      inactiveMessage: "原查询已不可修改，输入仍保留；已经发出的请求可核实原结果。",
      href: (record, scope, current) => href(family, record, scope, record?.values || {
        public_id: current.elements.public_id.value}),
      receiptMatches: (receipt, saved) => uuid.test(receipt?.public_id || "") &&
        receipt.row_version === (saved.public_id ? Number(saved.expected_row_version) + (family === "querydelete" ? 0 : 1) : 1) &&
        (!saved.public_id || receipt.public_id === saved.public_id) && typeof receipt.name === "string",
    });
  }
  function shelf(shelf, family, fields) {
    if (document.querySelector('form[data-saved-query="' + family + '"]')) return;
    try {
      const scope = JSON.parse(shelf.dataset.queryScope), list = shelf.querySelector("ul");
      for (const kind of ["create", "edit"]) {
        const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + family + "-" + kind + "-draft:v1:",
          fields: [...fields, "amount_placeholder", "amount_inputmode"], validRef: uuid});
        for (const record of store.list(scope)) {
          const item = document.createElement("li"), link = document.createElement("a");
          link.href = href(family, record, scope, record.values);
          link.textContent = (record.values.name || "未命名查询") + " · " + (!store.matches(record.scope, scope) ?
            "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "原提交待核对");
          item.append(link); list.append(item);
        }
      }
      shelf.hidden = !list.childElementCount;
    } catch (_) {
      shelf.hidden = false;
      shelf.querySelector("ul").textContent = "此浏览器的原任务暂时读不到。请恢复浏览器存储后重新打开，原输入不会被移除。";
    }
  }
  for (const [family, fields] of Object.entries(definitions)) {
    document.querySelectorAll('form[data-saved-query="' + family + '"]').forEach(form => mount(form, family, fields));
    document.querySelectorAll("[data-" + family + "-draft-shelf]").forEach(element => shelf(element, family, fields));
  }
})(window, document);
