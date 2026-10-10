/* One period command uses the shared draft lease and stable receipt owner. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "public_id", "task_id", "month", "payment_month", "q", "payment_id",
    "action", "expense_public_id", "expected_expense_row_version", "expected_row_version",
    "expected_series_row_version", "series_label", "payment_label"];
  function read(form) {
    return Object.fromEntries(names.map(name => [name, form.elements.namedItem(name).value]));
  }
  function href(record, scope, form) {
    const saved = record?.values || read(form);
    const next = new URL("/web/recurring/" + encodeURIComponent(saved.public_id) + "/occurrence", window.location.href);
    for (const name of ["ledger_id", "month", "payment_month", "q", "payment_id"]) next.searchParams.set(name, saved[name]);
    if (record) {
      next.searchParams.set("resume_occurrence", "1");
      next.hash = "occurrence-edit-" + record.clientRef;
    }
    return next.href;
  }
  function present(form, saved) {
    form.querySelector("[data-occurrence-summary]").textContent = saved.series_label + " · " + saved.month + " · " + saved.payment_label;
    form.querySelector("[data-occurrence-submit]").textContent = saved.action === "clear" ? "解除本期付款关联" : "用这笔付款确认本期已付";
  }
  const definition = {family: "occurrence", label: "付款关联", list: "/web/recurring", idField: "task_id",
    titleField: "series_label", create: names, edit: names, href, read, present, retainSelection: true,
    submitSelector: "[data-occurrence-submit]", pendingLabel: "重试原提交", reviewRequiresRejection: true,
    validRef: /^[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}$/i,
    action: saved => "/web/recurring/" + encodeURIComponent(saved.public_id) + "/occurrence",
    receiptMatches: (receipt, saved) => receipt?.series_public_id === saved.public_id && receipt.period === saved.month &&
      receipt.row_version === Number(saved.expected_row_version) + 1 &&
      receipt.expense_public_id === (saved.action === "clear" ? null : saved.expense_public_id),
    acceptsDestination: (next, saved) => next.pathname === "/web/recurring/" + saved.public_id + "/occurrence" &&
      next.searchParams.get("month") === saved.month,
  };
  const form = document.querySelector("form[data-occurrence-draft-scope]");
  const shelf = document.querySelector("[data-occurrence-draft-shelf]");
  if (form) window.TicketboxPlanEntry.mount(form, definition);
  else if (shelf) window.TicketboxPlanEntry.mountShelf(shelf, definition, JSON.parse(shelf.dataset.draftScope));
})(window, document);
