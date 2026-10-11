/* Manual rates use the existing identity-bound draft and first-receipt protocol. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "currency_code", "home_currency_code", "rate_date", "rate_to_cny", "expected_row_version", "return_href"];
  const names = [...fields, "return_context"];
  function read(form) {
    return {...Object.fromEntries(fields.map(name => [name, form.elements.namedItem(name).value])),
      return_context: JSON.stringify(Object.fromEntries([...form.querySelectorAll("[data-rate-task]")].map(input => [input.name, input.value])))};
  }
  function present(form, saved) {
    form.querySelectorAll("[data-rate-original]").forEach(label => { label.textContent = saved.currency_code || "单位原币种"; });
    form.querySelectorAll("[data-rate-target]").forEach(label => { label.textContent = saved.home_currency_code; });
  }
  function href(record, scope, form) {
    const saved = record?.values || read(form), next = new URL("/web/budget-advise/rates", window.location.href);
    Object.entries(JSON.parse(saved.return_context)).forEach(([name, value]) => next.searchParams.set(name, value));
    for (const name of ["currency_code", "home_currency_code", "rate_date"]) next.searchParams.set(name, saved[name]);
    next.searchParams.set("ledger_id", scope.ledgerId);
    if (record) next.hash = "rate-create-" + record.clientRef;
    return next.href;
  }
  function canonicalRate(value) { return String(value).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, ""); }
  function receiptMatches(receipt, saved) {
    return receipt?.public_id && receipt.currency_code === saved.currency_code && receipt.home_currency_code === saved.home_currency_code &&
      receipt.rate_date === saved.rate_date && canonicalRate(receipt.rate_to_cny) === canonicalRate(saved.rate_to_cny) &&
      Number.isSafeInteger(receipt.row_version) && receipt.row_version === Number(saved.expected_row_version) + 1;
  }
  function acceptsDestination(next, saved) {
    const expected = new URL(saved.return_href, window.location.href);
    return next.pathname === expected.pathname && [...expected.searchParams].every(([name, value]) => next.searchParams.get(name) === value);
  }
  const definition = {family: "rate", label: "人工汇率", creationLabel: "人工汇率", list: "/web/budget-advise/rates",
    create: names, edit: names, titleField: "currency_code", multiple: true, reviewName: "review_latest",
    reviewRequiresRejection: true, submitSelector: "[data-rate-submit]", read, present, href, receiptMatches, acceptsDestination,
    restore(form, saved) {
      const values = {...JSON.parse(saved.return_context), ...Object.fromEntries(fields.map(name => [name, saved[name]]))};
      for (const [name, value] of Object.entries(values)) {
        const input = form.elements.namedItem(name);
        if (input.tagName === "SELECT" && ![...input.options].some(option => option.value === value)) input.add(new Option(value, value));
        input.value = value;
      }
    },
    body(body, saved) {
      Object.entries(JSON.parse(saved.return_context)).forEach(([name, value]) => body.set(name, value));
      fields.filter(name => name !== "return_href").forEach(name => body.set(name, saved[name]));
    },
  };
  document.querySelectorAll("form[data-rate-draft-scope]").forEach(form => {
    form.dataset.rateNewDraft = String(!window.location.hash.startsWith("#rate-create-"));
    window.TicketboxPlanEntry.mount(form, definition);
    form.addEventListener("change", () => present(form, read(form)));
  });
})(window, document);
