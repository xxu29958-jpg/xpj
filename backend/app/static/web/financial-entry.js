/* Financial fields adapt the shared draft lease; commands keep their existing owner. */
(function (window, document) {
  "use strict";
  const scalars = ["ledger_id", "expense_id", "expected_row_version", "fact_basis", "idempotency_key", "draft_client_ref", "reason", "amount_yuan",
    "original_currency", "merchant", "category", "note", "tags", "expense_time", "value_score", "regret_score",
    "time_precision", "calendar_revision", "user_local_date", "source_timezone", "source_utc_offset_seconds", "accounting_date",
    "return_to", "return_month", "return_filter", "return_page", "return_tag", "return_query", "return_category", "return_home_currency_code",
    "return_granularity", "return_ranking_metric", "return_merchant_category", "return_recurring_public_id",
    "return_payment_expense_id", "return_import_public_id", "return_import_line_number", "return_import_expense_id",
    "return_receipt_key", "return_receipt_expense_id", "return_review_ref", "return_review_expense_id", "return_review_family", "return_duplicate_expense_id"];
  const itemNames = ["item_public_id", "item_name", "item_kind", "item_quantity", "item_unit_price_yuan", "item_amount_yuan", "item_category"];
  const splitNames = ["split_public_id", "split_member_id", "split_amount_yuan", "split_note"];
  const names = [...scalars, "present_fields", "item_rows", "split_rows"];
  const readRows = window.TicketboxWeb.readReviewRows;
  const put = window.TicketboxWeb.putReviewField;
  const restoreRows = window.TicketboxWeb.restoreReviewRows;
  function renderCorrectionComparison(form) {
    form.querySelectorAll("[data-correction-comparison]").forEach(row => {
      const fields = JSON.parse(row.dataset.fields), current = JSON.parse(row.dataset.current);
      const values = fields.map(name => form.elements.namedItem(name)?.value ?? current[name]);
      row.hidden = !row.querySelector('[type="radio"]') && fields.every((name, index) => values[index] === current[name]);
      let displayed = values;
      if (row.dataset.kind === "expense_time") {
        const time = Object.fromEntries(fields.map((name, index) => [name, values[index]]));
        displayed = time.time_precision === "date_only" ? [time.user_local_date] :
          [time.expense_time?.replace("T", " "), time.source_timezone];
      }
      row.querySelector("[data-correction-proposed]").textContent = displayed.filter(Boolean).join(" · ") || "未填写";
    });
  }
  document.querySelectorAll(".correction-form").forEach(form => {
    form.addEventListener("input", () => renderCorrectionComparison(form));
    form.addEventListener("change", () => renderCorrectionComparison(form));
    const preview = form.querySelector("[data-correction-show-preview]");
    if (preview) {
      preview.hidden = false;
      preview.addEventListener("click", () => {
        renderCorrectionComparison(form);
        form.querySelector("[data-correction-fields]").open = false;
        form.querySelector("[data-correction-comparisons]").scrollIntoView({block: "start"});
      });
    }
  });
  document.querySelectorAll("[data-correction-draft-scope]").forEach(form => {
    let present = [...new FormData(form).keys()].filter(name => scalars.includes(name));
    const currentVersion = form.dataset.correctionCurrentVersion;
    const field = name => form.elements.namedItem(name);
    window.TicketboxPlanEntry.mount(form, {family: "correction", label: "账单更正", list: "/web/confirmed",
      idField: "expense_id", titleField: "merchant", amount: "amount_yuan", create: names, edit: names,
      legacyMissing: ["return_receipt_key", "return_receipt_expense_id", "return_review_ref", "return_review_expense_id", "return_review_family", "return_duplicate_expense_id"],
      draftRefField: "draft_client_ref", commandKeyField: "idempotency_key",
      repeated: [...itemNames, ...splitNames], reviewName: "review_latest", reviewRequiresRejection: true,
      reviewWhileEditing: true, submitSelector: "[data-correction-submit]",
      relatedAction: submitter => submitter?.getAttribute("formaction") === "/web/expenses/" + field("expense_id").value + "/correction-rate",
      href: (record, scope) => {
        const saved = record?.values;
        const next = new URL("/web/expenses/" + encodeURIComponent(saved?.expense_id || field("expense_id").value) + "/correct", window.location.href);
        next.searchParams.set("ledger_id", scope.ledgerId);
        scalars.filter(name => name.startsWith("return_")).forEach(name => {
          const value = saved ? saved[name] : field(name)?.value;
          if (value) next.searchParams.set(name, value);
        });
        if (record) next.hash = "correction-edit-" + record.clientRef;
        else next.searchParams.set("new_correction", "1");
        return next.href;
      },
      read: current => {
        return {...Object.fromEntries(scalars.map(name => [name, field(name)?.value || ""])),
          present_fields: JSON.stringify(present),
          item_rows: JSON.stringify(readRows(current, itemNames)), split_rows: JSON.stringify(readRows(current, splitNames))};
      },
      restore: (current, saved) => {
        present = JSON.parse(saved.present_fields);
        scalars.forEach(name => { const input = field(name); if (input) put(input, saved[name]); });
        restoreRows(current, itemNames, saved.item_rows); restoreRows(current, splitNames, saved.split_rows);
        renderCorrectionComparison(current);
      },
      present: (_, saved) => {
        const note = form.querySelector("[data-correction-basis-note]");
        note.textContent = "原稿依据版本 " + saved.expected_row_version + "，金额币种 " + saved.original_currency +
          "；当前账单版本 " + currentVersion + "。" + (saved.expected_row_version === currentVersion ? "" : "请核对当前账单后再调整原稿。");
      },
      body: (body, saved) => {
        JSON.parse(saved.present_fields).forEach(name => body.set(name, saved[name]));
        for (const rows of [saved.item_rows, saved.split_rows]) JSON.parse(rows).forEach(row => {
          Object.entries(row).forEach(([name, value]) => body.append(name, value));
        });
      },
      receiptMatches: (receipt, saved) => String(receipt?.expense_id) === saved.expense_id && receipt?.change_kind === "correction",
      acceptsDestination: (next, saved) => next.pathname === "/web/expenses/" + saved.expense_id + "/edit",
    });
  });
  function updateOffsetPreview(form) {
    const panel = form.querySelector("[data-offset-preview]");
    if (!panel) return;
    panel.hidden = true;
    const field = name => form.elements.namedItem(name);
    if (field("original_amount").readOnly || field("expected_row_version").value !== panel.dataset.previewVersion ||
        field("original_currency_code").value !== panel.dataset.previewCurrency) return;
    const after = window.TicketboxWeb.remainingMoneyPreview(field("original_amount").value,
      panel.dataset.previewMinor, Number(panel.dataset.previewDigits));
    if (after === null) return;
    panel.querySelector("[data-offset-net]").textContent = panel.dataset.previewSymbol + after;
    panel.querySelector("[data-offset-preview-input]").textContent = panel.dataset.previewSymbol + field("original_amount").value;
    panel.hidden = false;
  }
  document.querySelectorAll(".offset-form").forEach(form => {
    form.addEventListener("input", () => updateOffsetPreview(form));
    form.addEventListener("change", () => updateOffsetPreview(form));
    form.addEventListener("submit", () => {
      const panel = form.querySelector("[data-offset-preview]");
      if (panel) panel.hidden = true;
    });
    updateOffsetPreview(form);
  });
  document.querySelectorAll("[data-offset-draft-scope]").forEach(form => {
    const fields = ["ledger_id", "expense_id", "task_id", "target_public_id", "kind", "original_amount", "original_currency_code",
      "accounting_date", "reason", "void_reason", "expected_row_version", "idempotency_key", "draft_client_ref",
      ...scalars.filter(name => name.startsWith("return_"))];
    const field = name => form.elements.namedItem(name);
    window.TicketboxPlanEntry.mount(form, {family: "offset", label: "退回与冲销", list: "/web/confirmed", multiple: true,
      idField: "task_id", titleField: "reason", amount: "original_amount", create: fields, edit: fields,
      legacyMissing: ["return_duplicate_expense_id"],
      draftRefField: "draft_client_ref", commandKeyField: "idempotency_key", reviewName: "review_latest",
      reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-offset-submit]",
      updatePresentation: updateOffsetPreview,
      inactiveMessage: "当前事实不允许追加这项记录。原输入仍保留，可核实已提交的请求或放弃本地原稿。",
      relatedAction: submitter => submitter?.getAttribute("formaction") === "/web/expenses/" + field("expense_id").value + "/offset-rate",
      href: (record, scope) => {
        const saved = record?.values;
        const next = new URL("/web/expenses/" + (saved?.expense_id || field("expense_id").value) + "/edit", window.location.href);
        next.searchParams.set("ledger_id", scope.ledgerId);
        fields.filter(name => name.startsWith("return_")).forEach(name => {
          const value = saved ? saved[name] : field(name)?.value;
          if (value) next.searchParams.set(name, value);
        });
        if (saved?.target_public_id) next.searchParams.set("continue_offset_id", saved.target_public_id);
        if (record) next.hash = "offset-edit-" + record.clientRef;
        else next.searchParams.set("new_offset", "1");
        return next.href;
      },
      restore: (_, saved) => fields.forEach(name => {
        let input = field(name);
        if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = name; form.append(input); }
        put(input, saved[name] ?? "");
      }),
      present: (_, saved) => {
        if (!document.querySelector(".fact-task[data-active]") || window.location.hash === "#offset-edit-" + saved.draft_client_ref) {
          document.querySelectorAll(".fact-task[data-active]").forEach(task => task.removeAttribute("data-active"));
          form.closest(".fact-task")?.setAttribute("data-active", "");
        }
        const note = form.querySelector("[data-offset-basis-note]");
        note.hidden = false;
        note.textContent = "原输入依据版本 " + saved.expected_row_version +
          "，原币 " + saved.original_currency_code + "；当前事实显示在上方，核对后才采用新的依据。";
        const label = form.querySelector('label[for="offset-amount"]');
        if (label) label.textContent = "退回金额（" + saved.original_currency_code + "）";
        const panel = form.querySelector("[data-offset-preview]");
        if (panel) panel.hidden = true;
      },
      body: (body, saved) => fields.forEach(name => body.set(name, saved[name])),
      receiptMatches: (receipt, saved) => String(receipt?.expense_id) === saved.expense_id &&
        receipt?.change_kind === (saved.kind === "void" ? "offset_void" : "offset_create") &&
        (!saved.target_public_id || receipt.target_public_id === saved.target_public_id),
      acceptsDestination: (next, saved) => next.pathname === "/web/expenses/" + saved.expense_id + "/edit",
    });
  });
})(window, document);
