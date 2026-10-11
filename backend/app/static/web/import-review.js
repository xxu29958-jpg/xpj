/* Saved CSV events use the existing bound draft and canonical CSV receipt owners. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "public_id", "line_number", "task_id", "expense_id", "expected_row_version",
    "reason", "acknowledge_incomplete_lineage", "manual_exchange_rate", "exchange_rate_date", "draft_client_ref"];
  document.querySelectorAll("[data-csvreview-draft-scope]").forEach(form => {
    const field = name => form.elements.namedItem(name);
    const workspace = form.closest("[data-import-review]");
    const title = workspace.querySelector("[data-import-review-title]");
    const inputs = form.querySelector("[data-import-review-inputs]");
    let previousPhase = "editing";
    const taskPath = saved => "/web/import/" + encodeURIComponent(saved.public_id) + "/rows/" + saved.line_number + "/review";
    window.TicketboxPlanEntry.mount(form, {family: "csvreview", label: "导入复核", list: "/web/import",
      create: names, edit: names, idField: "task_id", titleField: "reason",
      draftRefField: "draft_client_ref", commandKeyField: "draft_client_ref", reviewName: "review_latest",
      reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-csvreview-submit]",
      pendingLabel: "查看是否已登记", inactiveMessage: "本行已有处理结果。原输入仍保留，可沿原提交核实登记结果。",
      href: (record, scope) => {
        const saved = record?.values || Object.fromEntries(names.map(name => [name, field(name)?.value || ""]));
        const next = new URL(taskPath(saved), window.location.href);
        next.searchParams.set("ledger_id", scope.ledgerId);
        if (saved.expense_id) next.searchParams.set("expense_id", saved.expense_id);
        if (record) next.hash = "csvreview-edit-" + record.clientRef;
        return next.href;
      },
      read: () => Object.fromEntries(names.map(name => {
        const input = field(name);
        return [name, input?.type === "checkbox" ? (input.checked ? "true" : "") : input?.value || ""];
      })),
      restore: (_, saved) => names.forEach(name => {
        let input = field(name);
        if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = name; form.append(input); }
        if (input.type === "checkbox") input.checked = saved[name] === "true";
        else {
          input.value = saved[name];
          if (input.value !== saved[name]) { input.type = "text"; input.value = saved[name]; }
        }
      }),
      present: () => {},
      updatePresentation: (_, state) => {
        const pending = state.phase !== "editing";
        const status = form.querySelector("[data-csvreview-draft-status]");
        status.classList.toggle("product-feedback", pending);
        status.classList.toggle("product-feedback--warning", pending);
        form.querySelector("[data-import-source-hero]").hidden = pending;
        form.querySelector("[data-import-source-row]").hidden = !pending;
        const rootTitle = form.querySelector("[data-import-root-title]");
        if (rootTitle) rootTitle.hidden = pending;
        title.textContent = pending ? (state.rejected ? "核对后继续这次登记" : "正在确认登记结果") : title.dataset.editingTitle;
        inputs.querySelector("summary").hidden = !pending;
        if (state.phase !== previousPhase) {
          inputs.open = !pending;
          if (previousPhase === "editing" && pending) workspace.scrollIntoView({block: "start"});
        }
        previousPhase = state.phase;
        workspace.querySelectorAll("[data-import-select]").forEach(button => { button.hidden = pending; });
        const preview = form.querySelector("[data-import-net-preview]");
        if (preview) preview.hidden = pending || field("expense_id").value !== preview.dataset.rootId ||
          field("expected_row_version").value !== preview.dataset.rootVersion;
        const submit = form.querySelector("[data-csvreview-submit]");
        if (!pending && (form.dataset.csvreviewReady !== "true" || form.dataset.csvreviewCanWrite === "false")) submit.hidden = true;
      },
      receiptMatches: (receipt, saved) => receipt?.public_id === saved.public_id &&
        String(receipt.line_number) === saved.line_number && ["applied", "matched"].includes(receipt.status) &&
        (!saved.expense_id || String(receipt.expense_id) === saved.expense_id),
      acceptsDestination: (next, saved) => next.pathname === taskPath(saved),
    });
  });
})(window, document);
