/* Reference edits use the existing browser draft owner and online OCC. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "public_id", "tag_action", "edit_key", "expected_row_version", "name",
    "target", "target_name", "unused", "source_name", "source_usage_count"];
  const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function href(record, scope, form) {
    const saved = record?.values || Object.fromEntries(names.map(name => [name, form.elements.namedItem(name).value]));
    const next = new URL("/web/tags/" + encodeURIComponent(saved.public_id) + "/edit", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    next.searchParams.set("action", saved.tag_action);
    if (saved.unused === "1") next.searchParams.set("unused", "1");
    if (record) next.hash = "tag-edit-" + record.clientRef;
    else next.searchParams.set("new_tag", "1");
    return next.href;
  }
  function present(form, saved) {
    form.querySelector("[data-tag-original]").textContent = "原整理对象：" + (saved.source_name || "标签") +
      (saved.source_usage_count ? " · " + saved.source_usage_count + " 笔引用" : "");
    const target = form.elements.namedItem("target");
    if (target.tagName === "SELECT" && target.value) {
      target.selectedOptions[0].textContent = saved.target_name || "原合并目标";
    }
  }
  for (const form of document.querySelectorAll("form[data-tag-draft-scope]")) {
    const roleNotice = document.querySelector("[data-tag-role-notice]");
    if (roleNotice) roleNotice.hidden = true;
    window.TicketboxPlanEntry.mount(form, {
      family: "tag", label: "标签整理", list: "/web/tags", create: names, edit: names, validRef: uuid,
      idField: "edit_key", titleField: "source_name", commandRefField: "draft_ref", draftRefField: "draft_ref",
      pendingLabel: "重试原整理", inactiveMessage: "标签已不可用，原稿仍保留；请到回收站核对。",
      reviewWhileEditing: true, reviewRequiresRejection: true, submitSelector: "[data-tag-submit]", href, present,
      read: current => {
        const saved = Object.fromEntries(names.map(name => [name, current.elements.namedItem(name).value]));
        const target = current.elements.namedItem("target");
        if (target.tagName === "SELECT" && target.value) saved.target_name = target.selectedOptions[0].textContent;
        return saved;
      },
      receiptMatches: (receipt, saved) => receipt?.public_id === saved.public_id && receipt?.action === saved.tag_action,
      updatePresentation: (current, state) => {
        current.querySelector("[data-tag-reconnect]").hidden = state.phase === "editing" && current.dataset.tagCanWrite !== "false";
      },
    });
  }
  // Catalogue discovery only reads the same records. All writes and leases stay
  // with TicketboxPlanEntry, including explicit discard and acknowledgement.
  const catalog = document.querySelector("[data-tag-catalog-scope]");
  if (catalog) {
    try {
      const scope = JSON.parse(catalog.dataset.tagCatalogScope);
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:tag-edit-draft:v1:",
        fields: [...names, "amount_placeholder", "amount_inputmode"], validRef: uuid});
      const list = catalog.querySelector("[data-tag-draft-list]");
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(record, scope);
        link.textContent = ({rename: "重命名", merge: "合并", delete: "删除"}[record.values.tag_action] || "整理") +
          " · " + (record.values.source_name || "标签") + " · " +
          (!store.matches(record.scope, scope) ? "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : "待核对结果");
        item.append(link); list.append(item);
      }
      catalog.hidden = !list.childElementCount;
    } catch (_) { /* Storage being unavailable must not hide the live catalogue. */ }
  }
})(window, document);
