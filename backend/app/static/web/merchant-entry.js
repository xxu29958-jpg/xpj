/* Merchant inputs use the existing browser draft, identity and original receipt owner. */
(function (window, document) {
  "use strict";
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const fields = kind => ["ledger_id", "search", "status", "merchant",
    ...(kind === "catalog" ? ["display_name"] : ["canonical_merchant", "alias"])];
  function href(kind, scope, saved, record) {
    const next = new URL("/web/merchants", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    next.searchParams.set("view", kind === "catalog" ? "new" : "aliases");
    for (const name of ["search", "status", "merchant"]) if (saved[name]) next.searchParams.set(name, saved[name]);
    if (record) next.hash = kind + "creation-create-" + record.clientRef;
    else next.searchParams.set("new_" + kind + "creation", "1");
    return next.href;
  }
  for (const form of document.querySelectorAll("form[data-merchant-create]")) {
    const kind = form.dataset.merchantCreate, family = kind + "creation", names = fields(kind);
    if (!form.dataset[family + "DraftScope"]) continue;
    window.TicketboxPlanEntry.mount(form, {family, label: kind === "catalog" ? "商家添加任务" : "别名添加任务",
      list: "/web/merchants", create: names, edit: names, validRef: uuid,
      titleField: kind === "catalog" ? "display_name" : "alias", pendingLabel: "核实原添加", reviewRequiresRejection: true,
      href: (record, scope, current) => href(kind, scope, record?.values || Object.fromEntries(
        names.map(name => [name, current.elements.namedItem(name).value])), record),
      receiptMatches: receipt => uuid.test(receipt?.public_id) && receipt.row_version === 1 &&
        typeof receipt[kind === "catalog" ? "display_name" : "canonical_merchant"] === "string",
    });
  }
  for (const shelf of document.querySelectorAll("[data-merchant-shelf-kind]")) {
    try {
      const kind = shelf.dataset.merchantShelfKind, scope = JSON.parse(shelf.dataset.merchantScope);
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:" + kind + "creation-create-draft:v1:",
        fields: [...fields(kind), "amount_placeholder", "amount_inputmode"], validRef: uuid});
      const list = shelf.querySelector("ul");
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(kind, scope, record.values, record);
        link.textContent = (record.values[kind === "catalog" ? "display_name" : "alias"] || "未命名") + " · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "待核对添加结果");
        item.append(link); list.append(item);
      }
      shelf.hidden = !list.childElementCount;
    } catch (_) { /* The current directory remains readable without browser storage. */ }
  }
})(window, document);
