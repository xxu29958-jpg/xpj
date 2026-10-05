/* Financial fields adapt the shared draft lease; commands keep their existing owner. */
(function (window, document) {
  "use strict";
  const scalars = ["ledger_id", "expense_id", "expected_row_version", "fact_basis", "idempotency_key", "draft_client_ref", "reason", "amount_yuan",
    "original_currency", "merchant", "category", "note", "tags", "expense_time", "value_score", "regret_score",
    "time_precision", "calendar_revision", "user_local_date", "source_timezone", "source_utc_offset_seconds", "accounting_date",
    "return_to", "return_month", "return_filter", "return_page", "return_tag", "return_query", "return_home_currency_code",
    "return_granularity", "return_ranking_metric", "return_merchant_category", "return_recurring_public_id",
    "return_payment_expense_id", "return_import_public_id", "return_import_line_number", "return_import_expense_id"];
  const itemNames = ["item_public_id", "item_name", "item_kind", "item_quantity", "item_unit_price_yuan", "item_amount_yuan", "item_category"];
  const splitNames = ["split_public_id", "split_member_id", "split_amount_yuan", "split_note"];
  const names = [...scalars, "present_fields", "item_rows", "split_rows"];
  const readRows = (form, columns) => [...form.querySelectorAll('[name="' + columns[0] + '"]')].map(input => {
    const row = input.closest("[data-review-line]");
    return Object.fromEntries(columns.map(name => [name, row.querySelector('[name="' + name + '"]').value]));
  });
  function put(input, value) {
    if (input.tagName === "SELECT" && ![...input.options].some(option => option.value === value)) {
      input.add(new Option(value || "原选择为空", value));
    }
    if (["number", "date", "datetime-local"].includes(input.type)) {
      input.value = value;
      if (input.value !== value) input.type = "text";
    }
    input.value = value;
  }
  function restoreRows(form, columns, encoded) {
    const original = form.querySelector('[name="' + columns[0] + '"]');
    const prototype = original.closest("[data-review-line]").cloneNode(true);
    const parent = original.closest(".expense-lines-editor");
    parent.replaceChildren();
    JSON.parse(encoded).forEach((values, index) => {
      const row = prototype.cloneNode(true);
      row.hidden = false;
      row.open = false;
      row.querySelectorAll("[data-bound]").forEach(node => node.removeAttribute("data-bound"));
      row.querySelectorAll(".field-error, .meta").forEach(node => node.remove());
      row.querySelectorAll("[aria-describedby]").forEach(node => node.removeAttribute("aria-describedby"));
      columns.forEach(name => {
        const input = row.querySelector('[name="' + name + '"]');
        put(input, values[name]);
        if (input.hasAttribute("aria-label")) input.setAttribute("aria-label", input.getAttribute("aria-label").replace(/第 \d+ 行/, "第 " + (index + 1) + " 行"));
      });
      parent.append(row);
    });
    window.TicketboxWeb.bindReviewFields(parent);
  }
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
  document.querySelectorAll("[data-offset-draft-scope]").forEach(form => {
    const fields = ["ledger_id", "expense_id", "task_id", "target_public_id", "kind", "original_amount", "original_currency_code",
      "accounting_date", "reason", "void_reason", "expected_row_version", "idempotency_key", "draft_client_ref",
      ...scalars.filter(name => name.startsWith("return_"))];
    const field = name => form.elements.namedItem(name);
    window.TicketboxPlanEntry.mount(form, {family: "offset", label: "退回与冲销", list: "/web/confirmed", multiple: true,
      idField: "task_id", titleField: "reason", amount: "original_amount", create: fields, edit: fields,
      draftRefField: "draft_client_ref", commandKeyField: "idempotency_key", reviewName: "review_latest",
      reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-offset-submit]",
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
        put(input, saved[name]);
      }),
      present: (_, saved) => {
        form.querySelector("[data-offset-basis-note]").textContent = "原输入依据版本 " + saved.expected_row_version +
          "，原币 " + saved.original_currency_code + "；当前事实显示在上方，核对后才采用新的依据。";
        const label = form.querySelector('label[for="offset-amount"]');
        if (label) label.textContent = "退回金额（" + saved.original_currency_code + "）";
      },
      body: (body, saved) => fields.forEach(name => body.set(name, saved[name])),
      receiptMatches: (receipt, saved) => String(receipt?.expense_id) === saved.expense_id &&
        receipt?.change_kind === (saved.kind === "void" ? "offset_void" : "offset_create") &&
        (!saved.target_public_id || receipt.target_public_id === saved.target_public_id),
      acceptsDestination: (next, saved) => next.pathname === "/web/expenses/" + saved.expense_id + "/edit",
    });
  });
})(window, document);
