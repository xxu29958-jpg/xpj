(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "mode", "account_id", "task_id", "name", "kind", "currency_code", "visibility",
    "institution", "tail", "opening_amount", "opening_source", "occurred_on", "expected_row_version", "archived",
    "calendar_revision", "payer_public_id", "payer_row_version", "payer_currency_code", "principal_amount", "payer_amount", "note", "idempotency_key",
    "activity_amount", "other_amount", "apply_adjustment", "loan_name", "loan_currency_code", "loan_principal_amount", "new_fee", "fee_note",
    "draw_ids_json", "periods_json", "supersedes_public_id", "allocation_json", "overpayment", "repayment_public_id",
    "credit_limit", "available_credit", "credit_observed_on", "credit_source", "statement_day", "payment_due_day", "existing_debt",
    "source_repayment_draft_id", "source_amount_basis", "source_review_reason"];
  const definition = {family: "funds", label: "资金任务", list: "/web/funds", idField: "task_id", titleField: "name",
    editLabel: "继续资金任务", creationLabel: "继续资金任务",
    create: fields, edit: fields, commandKeyField: "idempotency_key", reviewName: "review_latest",
    legacyMissing: ["source_repayment_draft_id", "source_amount_basis", "source_review_reason"],
    reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-funds-submit]",
    href: (record, scope) => {
      const next = new URL("/web/funds", window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      next.searchParams.set("task", record?.values.mode || "create");
      if (record?.values.account_id) next.searchParams.set("account_id", record.values.account_id);
      if (record?.values.source_repayment_draft_id) next.searchParams.set("source_repayment_draft_id", record.values.source_repayment_draft_id);
      if (record?.values.repayment_public_id) next.searchParams.set("repayment_id", record.values.repayment_public_id);
      if (record) next.hash = "funds-" + (record.values.task_id ? "edit-" : "create-") + record.clientRef;
      return next.href;
    },
    receiptMatches: (receipt, saved) => typeof receipt?.public_id === "string" &&
      (!saved.account_id || receipt.public_id === saved.account_id) && receipt.currency_code === saved.currency_code,
    acceptsDestination: next => next.pathname === "/web/funds",
    updatePresentation: (form, state) => {
      const choice = form.querySelector("[data-funds-choice]");
      if (choice) choice.disabled = !state.editable;
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
  const creditPanel = form.querySelector("[data-credit-terms]");
  function showCreditTerms() {
    const originalDebt = field("existing_debt")?.selectedOptions?.[0];
    if (originalDebt?.value && originalDebt.text === originalDebt.value) originalDebt.text = "保留原欠款选择，请重新核对";
    if (creditPanel) creditPanel.hidden = field("kind")?.value !== "credit";
  }
  field("kind")?.addEventListener("change", showCreditTerms);
  form.addEventListener("ticketbox:funds-state", showCreditTerms);
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
  const payer = field("payer_public_id");
  if (payer?.tagName === "SELECT") payer.addEventListener("change", () => {
    const selected = payer.selectedOptions[0];
    field("payer_row_version").value = selected.dataset.version || "";
    field("payer_currency_code").value = selected.dataset.currency || "";
    form.querySelectorAll("[data-funds-payer-currency]").forEach(label => { label.textContent = selected.dataset.currency || ""; });
  });
  window.TicketboxPlanEntry.mount(form, definition);
})(window, document);
