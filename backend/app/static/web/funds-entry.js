(function (window, document) {
  "use strict";
  const fields = ["credit_source_id", "credit_draw_id", "credit_review_id", "credit_source_label", "credit_draw_label", "ledger_id", "mode", "account_id", "task_id", "name", "kind", "currency_code", "visibility", "edit_visibility",
    "institution", "tail", "opening_amount", "opening_source", "occurred_on", "expected_row_version", "archived",
    "calendar_revision", "payer_public_id", "payer_row_version", "payer_currency_code", "principal_amount", "payer_amount", "note", "idempotency_key",
    "activity_amount", "other_amount", "reviewed_debt_amount", "apply_adjustment", "loan_name", "loan_currency_code", "loan_principal_amount", "new_fee", "fee_note", "fee_period_id", "payer_fee_amount",
    "draw_ids_json", "periods_json", "supersedes_public_id", "allocation_json", "overpayment", "repayment_public_id",
    "credit_limit", "available_credit", "credit_observed_on", "credit_source", "statement_day", "payment_due_day", "existing_debt",
    "source_repayment_draft_id", "source_amount_basis", "source_review_reason", "activity_event_id", "activity_parts_json", "activity_summary"];
  const definition = {family: "funds", label: "资金任务", list: "/web/funds", idField: "task_id", titleField: "name",
    editLabel: "继续资金任务", creationLabel: "继续资金任务",
    create: fields, edit: fields, commandKeyField: "idempotency_key", reviewName: "review_latest",
    legacyMissing: ["activity_event_id", "activity_parts_json", "activity_summary", "reviewed_debt_amount", "credit_source_id", "credit_draw_id", "credit_review_id", "credit_source_label", "credit_draw_label", "fee_period_id", "payer_fee_amount","source_repayment_draft_id", "source_amount_basis", "source_review_reason", "edit_visibility"],
    reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-funds-submit]",
    href: (record, scope) => {
      const next = new URL("/web/funds", window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      next.searchParams.set("task", record?.values.mode || "create");
      if (record?.values.account_id) next.searchParams.set("account_id", record.values.account_id);
      if (record?.values.source_repayment_draft_id) next.searchParams.set("source_repayment_draft_id", record.values.source_repayment_draft_id);
      if (record?.values.repayment_public_id) next.searchParams.set("repayment_id", record.values.repayment_public_id);
      if (record?.values.credit_review_id) next.searchParams.set("application_id", record.values.credit_review_id);
      if (record?.values.activity_event_id) next.searchParams.set("event_id", record.values.activity_event_id);
      if (record) next.hash = "funds-" + (record.values.task_id ? "edit-" : "create-") + record.clientRef;
      return next.href;
    },
    receiptMatches: (receipt, saved) => typeof receipt?.public_id === "string" &&
      (!saved.account_id || receipt.public_id === saved.account_id) && receipt.currency_code === saved.currency_code,
    acceptsDestination: next => next.pathname === "/web/funds",
    updatePresentation: (form, state) => {
      const choice = form.querySelector("[data-funds-choice]");
      if (choice) choice.disabled = !state.editable;
      const summary = form.querySelector("[data-funds-activity-summary]");
      if (summary) summary.textContent = form.elements.namedItem("activity_summary").value;
      form.dispatchEvent(new Event("ticketbox:funds-state"));
    },
  };
  const form = document.querySelector("[data-funds-form]");
  if (!form) {
    const shelf = document.querySelector("[data-funds-draft-shelf]");
    if (shelf) window.TicketboxPlanEntry.mountShelf(shelf, definition, JSON.parse(shelf.dataset.draftScope));
    return;
  }
  const field = name => form.elements.namedItem(name);
  const value = name => (field(name)?.value || "").trim();
  function showCreditTerms() {
    const originalDebt = field("existing_debt")?.selectedOptions?.[0];
    if (originalDebt?.value && originalDebt.text === originalDebt.value) originalDebt.text = "保留原欠款选择，请重新核对";
    // Credit-only parts follow the chosen type; on an existing account the type is fixed by the page.
    const credit = (field("kind")?.value || form.dataset.fundsAccountKind) === "credit";
    form.querySelectorAll("[data-credit-terms], [data-credit-only]").forEach(part => { part.hidden = !credit; });
  }

  // Optional sections: their summary line shows what is filled in; they start folded unless the
  // server asked for them open, and open by themselves when one of their fields is invalid.
  const options = [...form.querySelectorAll("[data-funds-options]")];
  function summarizeOptions() {
    options.forEach(details => {
      const target = details.querySelector("[data-options-summary]");
      if (!target) return;
      const filled = target.dataset.optionsFields.split(" ").map(name => {
        const input = field(name);
        if (!input || !input.value) return "";
        return input.tagName === "SELECT" ? input.selectedOptions[0]?.textContent.trim() || "" : input.value.trim();
      }).filter(Boolean);
      target.textContent = filled.length ? filled.join(" · ") : target.dataset.optionsEmpty;
    });
  }
  options.forEach(details => { details.open = details.dataset.startExpanded === "true"; });
  form.addEventListener("invalid", event => {
    const details = event.target.closest("[data-funds-options]");
    if (details) details.open = true;
  }, true);

  // Same currency mirrors the principal; an existing dated rate suggests the foreign deduction.
  const payerAmount = form.querySelector("[data-funds-payer-amount]");
  function mirrorPayerAmount() {
    if (!payerAmount || !field("payer_amount")) return;
    const same = value("payer_currency_code") && value("payer_currency_code") === form.dataset.fundsAccountCurrency;
    payerAmount.hidden = Boolean(same);
    if (same && !field("payer_amount").readOnly && field("payer_amount").value !== field("principal_amount").value) {
      field("payer_amount").value = field("principal_amount").value;
      field("payer_amount").dispatchEvent(new Event("input", {bubbles: true}));
    }
  }

  let quoteController = null, suggestedPayerAmount = null;
  const quoteBasis = () => JSON.stringify([value("ledger_id"), value("draft_scope"), value("payer_public_id"),
    value("payer_currency_code"), value("principal_amount"), value("occurred_on")]);
  async function quotePayerAmount() {
    quoteController?.abort();
    suggestedPayerAmount = null;
    const paid = field("payer_amount");
    if (value("mode") !== "repay" || !paid || paid.readOnly) return;
    if (value("payer_currency_code") === form.dataset.fundsAccountCurrency) { mirrorPayerAmount(); return; }
    paid.value = "";
    paid.dispatchEvent(new Event("input", {bubbles: true}));
    if (!value("payer_currency_code") || !value("principal_amount") || !value("occurred_on")) return;
    const basis = quoteBasis(), controller = new AbortController();
    quoteController = controller;
    const query = new URLSearchParams({ledger_id: value("ledger_id"), currency_code: form.dataset.fundsAccountCurrency,
      home_currency_code: value("payer_currency_code"), amount: value("principal_amount"), rate_date: value("occurred_on")});
    try {
      const response = await fetch("/web/funds/conversion?" + query, {signal: controller.signal, cache: "no-store"});
      const result = await response.json();
      if (controller.signal.aborted || basis !== quoteBasis() || paid.readOnly || paid.value !== "") return;
      if (!response.ok || result.converted_amount === null) throw Error("rate_unavailable");
      suggestedPayerAmount = result.converted_amount;
      paid.value = result.converted_amount;
      paid.dispatchEvent(new Event("input", {bubbles: true}));
    } catch (_) {
      if (controller.signal.aborted || basis !== quoteBasis() || paid.readOnly || paid.value !== "") return;
      const status = form.querySelector("[data-funds-draft-status]");
      if (status) { status.hidden = false; status.textContent = "暂时无法读取或获取参考汇率。原操作已保留，可重试；持续失败时请在本机管理检查来源。"; }
    }
  }
  for (const name of ["principal_amount", "occurred_on"]) field(name)?.addEventListener("input", () => {
    if (!value("payer_amount") || value("payer_amount") === suggestedPayerAmount) quotePayerAmount();
  });
  field("payer_amount")?.addEventListener("input", () => {
    if (value("payer_amount") && value("payer_amount") !== suggestedPayerAmount) quoteController?.abort();
  });
  window.addEventListener("pagehide", () => quoteController?.abort());

  // What confirming will change, in the user's own numbers; the server still decides the result.
  const summary = form.querySelector("[data-funds-summary]");
  const kinds = {cash: "现金账户", bank: "银行卡", wallet: "余额账户", credit: "信用账户"};
  const optionText = name => field(name)?.selectedOptions?.[0]?.textContent.trim() || "";
  const amount = (number, currency) => number + " " + currency;
  const sentences = {
    create: () => {
      if (!value("name")) return "";
      const credit = value("kind") === "credit";
      const opening = value("opening_amount") === "" ? "期初待核对，不按零计算"
        : (credit ? "期初欠款 " : "期初余额 ") + amount(value("opening_amount"), value("currency_code")) + "（" + value("occurred_on") + "）";
      return "将添加" + kinds[value("kind")] + "「" + value("name") + "」，" + value("currency_code") + "，" + opening + "，" + optionText("visibility") + "可见。";
    },
    income: () => value("activity_amount") && "「" + form.dataset.fundsAccountName + "」将增加 " + amount(value("activity_amount"), form.dataset.fundsAccountCurrency) + "。实际收入不算消费，也不改变收入计划。",
    loan: () => value("activity_amount") && value("loan_principal_amount") && "「" + form.dataset.fundsAccountName + "」将收到 " + amount(value("activity_amount"), form.dataset.fundsAccountCurrency) +
      "，同时新增负债「" + (value("loan_name") || "贷款") + "」本金 " + amount(value("loan_principal_amount"), value("loan_currency_code")) + "。贷款本金不算收入。",
    transfer: () => value("activity_amount") && value("payer_public_id") && "从「" + form.dataset.fundsAccountName + "」转出 " + amount(value("activity_amount"), form.dataset.fundsAccountCurrency) +
      "，「" + optionText("payer_public_id").split(" · ")[0] + "」到账 " + amount(value("other_amount") || "—", value("payer_currency_code")) + "。不算收入或消费。",
    reconciliation: () => value("activity_amount") && (value("apply_adjustment") === "true"
      ? "按外部余额 " + amount(value("activity_amount"), form.dataset.fundsAccountCurrency) + " 记一笔差额更正，作为新的余额基准；原记录保留。"
      : "只保存外部余额快照 " + amount(value("activity_amount"), form.dataset.fundsAccountCurrency) + "，账户余额不变，差异留待解释。"),
    installments: () => {
      const draws = JSON.parse(value("draw_ids_json") || "[]").length;
      const periods = JSON.parse(value("periods_json") || "[]").length;
      return value("name") && periods ? "将记录合约「" + value("name") + "」：纳入 " + draws + " 笔未偿本金，按 " + periods +
        " 期安排。只重排已有欠款，不新增消费或贷款；未来费用实际发生时才记。" : "";
    },
    repay: () => {
      if (!value("payer_public_id") || !value("principal_amount")) return "";
      const payer = optionText("payer_public_id").split(" · ")[0], currency = value("payer_currency_code");
      const paid = value("payer_amount") || (currency === form.dataset.fundsAccountCurrency ? value("principal_amount") : "—");
      const parts = ["本金 " + amount(paid, currency)];
      if (value("new_fee")) parts.push("新费用 " + amount(value("new_fee"), currency));
      if (value("payer_fee_amount")) parts.push("已记费用 " + amount(value("payer_fee_amount"), currency));
      return "从「" + payer + "」扣款：" + parts.join("，") + "。「" + form.dataset.fundsAccountName + "」欠款减少 " +
        amount(value("principal_amount"), form.dataset.fundsAccountCurrency) + (value("overpayment") ? "，其中溢缴款 " + amount(value("overpayment"), form.dataset.fundsAccountCurrency) : "") +
        "。本金不再计一次消费" + (value("new_fee") ? "；新费用记为一笔消费" : "") + "。";
    },
  };
  // A single open purchase settles without choosing; an overpayment makes the allocation explicit.
  const allocation = form.querySelector("[data-allocation-block]");
  function showAllocation() {
    if (allocation) allocation.hidden = allocation.dataset.allocationRequired !== "true" && !value("overpayment");
  }
  function describe() {
    summarizeOptions();
    mirrorPayerAmount();
    showAllocation();
    if (!summary) return;
    const text = (sentences[value("mode")] || (() => ""))() || "";
    summary.textContent = text;
    summary.hidden = !text;
  }
  field("kind")?.addEventListener("change", showCreditTerms);
  form.addEventListener("ticketbox:funds-state", () => { showCreditTerms(); describe(); });
  form.addEventListener("input", describe);
  form.addEventListener("change", describe);
  const choice = form.querySelector("[data-funds-choice]");
  choice?.addEventListener("change", () => {
    const selected = choice.selectedOptions[0];
    if (!selected.dataset.kind) return;
    for (const name of ["kind", "name", "institution"]) {
      field(name).value = selected.dataset[name];
      field(name).dispatchEvent(new Event("input", {bubbles: true}));
    }
    showCreditTerms();
  });
  form.querySelectorAll("[data-credit-application-choice]").forEach(select => {
    const label = select.name === "credit_source_id" ? "credit_source_label" : "credit_draw_label";
    select.addEventListener("change", () => {
      field(label).value = select.selectedOptions[0]?.textContent || "";
      field(label).dispatchEvent(new Event("input", {bubbles: true}));
    });
    form.addEventListener("ticketbox:funds-state", () => {
      const option = select.selectedOptions[0];
      if (option?.value && option.textContent === option.value) option.textContent =
        (field(label).value || "保留原选择") + " · 当前不可选，请核对";
    });
  });
  const payer = field("payer_public_id");
  if (payer?.tagName === "SELECT") payer.addEventListener("change", () => {
    const selected = payer.selectedOptions[0];
    const nextCurrency = selected.dataset.currency || "";
    const currencyChanged = value("payer_currency_code") !== nextCurrency;
    field("payer_row_version").value = selected.dataset.version || "";
    field("payer_currency_code").value = nextCurrency;
    if (value("mode") === "repay" && (currencyChanged || !value("payer_amount"))) {
      quotePayerAmount();
    }
    form.querySelectorAll("[data-funds-payer-currency]").forEach(label => { label.textContent = selected.dataset.currency || ""; });
    describe();
  });
  showCreditTerms();
  window.TicketboxPlanEntry.mount(form, definition);
  describe();
})(window, document);
