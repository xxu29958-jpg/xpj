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
  function mountCreation(form) {
    const kind = form.dataset.merchantCreate, family = kind + "creation", names = fields(kind);
    if (!form.dataset[family + "DraftScope"]) return;
    window.TicketboxPlanEntry.mount(form, {family, label: kind === "catalog" ? "商家添加任务" : "别名添加任务",
      list: "/web/merchants", create: names, edit: names, validRef: uuid,
      titleField: kind === "catalog" ? "display_name" : "alias", pendingLabel: "核实原添加", reviewRequiresRejection: true,
      href: (record, scope, current) => href(kind, scope, record?.values || Object.fromEntries(
        names.map(name => [name, current.elements.namedItem(name).value])), record),
      receiptMatches: receipt => uuid.test(receipt?.public_id) && receipt.row_version === 1 &&
        typeof receipt[kind === "catalog" ? "display_name" : "canonical_merchant"] === "string",
    });
  }
  function renderCreationShelf(shelf) {
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
  const commandFields = kind => ["ledger_id", "merchant", "search", "status", "source_name", "target_name",
    "expected_row_version", "idempotency_key", "draft_ref", ...(kind === "rename" ? ["display_name"] :
      kind === "merge" ? ["target", "alias_policy"] : kind === "toggle" ? ["next_status"] : [])];
  function commandHref(kind, scope, saved, record) {
    const next = new URL("/web/merchants", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    next.searchParams.set("view", "merchant"); next.searchParams.set("command", kind);
    for (const name of ["merchant", "search", "status"]) if (saved[name]) next.searchParams.set(name, saved[name]);
    if (record) next.hash = "catalog" + kind + "-edit-" + record.clientRef;
    else next.searchParams.set("new_catalog" + kind, "1");
    return next.href;
  }
  function matchesCommand(kind, receipt, saved) {
    const source = kind === "merge" ? receipt?.source : receipt;
    if (source?.public_id !== saved.merchant || source.row_version !== Number(saved.expected_row_version) + 1) return false;
    if (kind === "merge") {
      const [target, version] = saved.target.split(":");
      return source.status === "merged" && source.merged_into_public_id === target && receipt.target?.public_id === target &&
        receipt.target.row_version === Number(version) + 1 && !!receipt.created_alias_public_id === (saved.alias_policy === "create_source_alias");
    }
    return kind === "delete" ? !!source.deleted_at : kind !== "toggle" || source.status === saved.next_status;
  }
  function mountCommand(form) {
    const kind = form.dataset.merchantCommand, family = "catalog" + kind, names = commandFields(kind);
    if (!form.dataset[family + "DraftScope"]) return;
    const read = current => {
      const saved = Object.fromEntries(names.map(name => [name, current.elements.namedItem(name)?.value || ""]));
      if (kind === "merge" && saved.target) saved.target_name = current.elements.target.selectedOptions[0].textContent;
      return saved;
    };
    window.TicketboxPlanEntry.mount(form, {family, label: "商家操作", list: "/web/merchants", create: names, edit: names,
      idField: "merchant", titleField: "source_name", commandKeyField: "idempotency_key", draftRefField: "draft_ref",
      pendingLabel: "核实原提交", reviewRequiresRejection: true, reviewWhileEditing: true, read,
      inactiveMessage: "原商家当前不可修改，原输入仍保留。已发出的提交可继续核实原结果。",
      href: (record, scope, current) => commandHref(kind, scope, record?.values || read(current), record),
      receiptMatches: (receipt, saved) => matchesCommand(kind, receipt, saved),
      present: (current, saved) => {
        current.querySelector("[data-command-source]").textContent = "原商家：" + saved.source_name;
        if (kind === "merge" && saved.target) current.elements.target.selectedOptions[0].textContent = saved.target_name || "原目标，请核对";
        if (kind === "toggle") current.querySelector("[data-command-status]").textContent =
          (saved.next_status === "hidden" ? "隐藏商家" : "显示商家") + "：只影响目录和后续选择，仍保留历史关联。";
      },
    });
  }
  function renderCommandShelf(shelf) {
    const kind = shelf.dataset.merchantCommandShelf;
    if (document.querySelector('form[data-merchant-command="' + kind + '"]')) return;
    try {
      const scope = JSON.parse(shelf.dataset.merchantScope);
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:catalog" + kind + "-edit-draft:v1:",
        fields: [...commandFields(kind), "amount_placeholder", "amount_inputmode"], validRef: uuid});
      const list = shelf.querySelector("ul");
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = commandHref(kind, scope, record.values, record);
        link.textContent = (record.values.source_name || "原商家") + " · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "原提交待核对");
        item.append(link); list.append(item);
      }
      shelf.hidden = !list.childElementCount;
    } catch (_) { /* Retained commands remain in their existing store when storage is unavailable. */ }
  }
  document.querySelectorAll("form[data-merchant-create]").forEach(mountCreation);
  document.querySelectorAll("[data-merchant-shelf-kind]").forEach(renderCreationShelf);
  document.querySelectorAll("form[data-merchant-command]").forEach(mountCommand);
  document.querySelectorAll("[data-merchant-command-shelf]").forEach(renderCommandShelf);
})(window, document);
