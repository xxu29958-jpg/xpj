/* Reference creation reuses the existing bound draft/lease/receipt owner. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "name", "kind", "month", "unused"];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function href(kind, scope, saved, record) {
    const next = new URL("/web/reference/" + kind + "/new", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    for (const name of ["month", "unused"]) if (saved[name]) next.searchParams.set(name, saved[name]);
    if (record) next.hash = kind + "creation-create-" + record.clientRef;
    else next.searchParams.set("new_" + kind + "creation", "1");
    return next.href;
  }
  for (const form of document.querySelectorAll("form[data-reference-kind]")) {
    const kind = form.dataset.referenceKind;
    const family = kind + "creation";
    if (!form.dataset[family + "DraftScope"]) continue;
    window.TicketboxPlanEntry.mount(form, {family, label: kind === "tag" ? "标签添加任务" : "分类添加任务",
      list: kind === "tag" ? "/web/tags" : "/web/categories", create: fields, edit: fields, validRef: uuid,
      titleField: "name", pendingLabel: "核实原添加", reviewRequiresRejection: true,
      href: (record, scope, current) => href(kind, scope, record?.values || Object.fromEntries(
        fields.map(name => [name, current.elements.namedItem(name).value])), record),
      receiptMatches: (receipt, saved) => receipt?.kind === saved.kind && uuid.test(receipt.public_id) && receipt.row_version > 0,
    });
  }
  for (const catalog of document.querySelectorAll("[data-reference-catalog]")) {
    try {
      const kind = catalog.dataset.referenceCatalog, scope = JSON.parse(catalog.dataset.referenceScope);
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + kind + "creation-create-draft:v1:",
        fields: [...fields, "amount_placeholder", "amount_inputmode"], validRef: uuid});
      const list = catalog.querySelector("ul");
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(kind, scope, record.values, record);
        link.textContent = (record.values.name || "未命名") + " · " + (!store.matches(record.scope, scope)
          ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "待核对添加结果");
        item.append(link); list.append(item);
      }
      catalog.hidden = !list.childElementCount;
    } catch (_) { /* Live catalogue remains usable when browser storage is unavailable. */ }
  }
})(window, document);
