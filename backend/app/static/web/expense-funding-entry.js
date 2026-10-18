(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "expense_id", "currency_code", "expected_row_version", "funding_json", "reason", "idempotency_key"];
  const definition = {family: "funding", label: "付款来源", list: "/web/expenses", idField: "expense_id", titleField: "reason",
    create: fields, edit: fields, commandKeyField: "idempotency_key", reviewName: "review_latest",
    reviewRequiresRejection: true, reviewWhileEditing: true, submitSelector: "[data-funding-submit]",
    href: (record, scope) => `/web/expenses/${record.values.expense_id}/funding?ledger_id=${encodeURIComponent(scope.ledgerId)}#funding-edit-${record.clientRef}`,
    receiptMatches: (receipt, saved) => String(receipt?.expense_id) === saved.expense_id && receipt.currency_code === saved.currency_code,
    acceptsDestination: next => /^\/web\/expenses\/\d+\/edit$/.test(next.pathname),
    updatePresentation: form => form.dispatchEvent(new Event("ticketbox:funding-state")),
  };
  const form = document.querySelector("[data-funding-form]");
  if (form) window.TicketboxPlanEntry.mount(form, definition);
})(window, document);
