/* Debt creation consumes the existing draft store, lease and first receipt. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "home_currency_code", "currency_code", "currency_minor_digits", "amount_major",
    "direction", "counterparty_label", "event_time", "calendar_revision", "debt_kind", "installment_count",
    "installment_period_months", "note"];
  const field = (form, name) => form.elements.namedItem(name);
  const validRef = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  function matchesAmount(receipt, saved) {
    const parts = /^(\d+)(?:\.(\d+))?$/.exec(saved.amount_major.trim());
    const digits = Number(saved.currency_minor_digits), minor = receipt.original_amount_minor ?? receipt.principal_amount_cents;
    if (!parts || !Number.isInteger(digits) || digits < 0 || digits > 20 || !Number.isSafeInteger(minor)) return false;
    const fraction = parts[2] || "";
    return !/[^0]/.test(fraction.slice(digits)) &&
      BigInt(parts[1]) * 10n ** BigInt(digits) + BigInt(fraction.slice(0, digits).padEnd(digits, "0") || "0") === BigInt(minor);
  }
  function receiptMatches(receipt, saved) {
    if (!receipt?.public_id) return false;
    const time = receipt?.accounting_time;
    const count = saved.installment_count ? Number(saved.installment_count) : null;
    const expected = {ledger_id: saved.ledger_id, counterparty_type: "external", direction: saved.direction,
      counterparty_label: saved.counterparty_label.trim(), home_currency_code: saved.home_currency_code,
      original_currency_code: saved.currency_code, debt_kind: saved.debt_kind, installment_count: count,
      installment_period_months: count ? Number(saved.installment_period_months || "1") : null,
      note: saved.note.replace(/\r\n?/g, "\n").trim()};
    const actual = {...receipt, original_currency_code: receipt.original_currency_code || receipt.home_currency_code,
      note: receipt.note || "", installment_period_months: receipt.installment_period_months ?? null};
    return Object.entries(expected).every(([name, value]) => actual[name] === value) && matchesAmount(receipt, saved) &&
      time?.precision === "date_only" && time.user_local_date === saved.event_time &&
      time.calendar_revision === Number(saved.calendar_revision);
  }
  const definition = {family: "debtcreation", label: "往来", list: "/web/debts", titleField: "counterparty_label",
    create: names, edit: names, validRef, amount: "amount_major", receiptMatches, reviewRequiresRejection: true,
    // Opening the form selects nothing yet: a draft starts with the first input, and the rate
    // lookup round trip retains the form itself (relatedAction).
    submitSelector: "[data-debtcreation-submit]", pendingLabel: "核实这笔往来",
    href(record, scope) {
      const next = new URL("/web/debts/new", window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      if (record) next.hash = "debtcreation-create-" + record.clientRef;
      else next.searchParams.set("new_debtcreation", "1");
      return next.href;
    },
    body(body, saved) { names.forEach(name => body.set(name, saved[name])); },
    present(form, saved) {
      form.querySelector('[for="debt-new-amount"]').textContent = "金额（" + saved.currency_code + "）";
      form.querySelector("[data-debtcreation-currency-note]").textContent = "保留原币金额，按发生日折算为 " + saved.home_currency_code + "。";
    },
    acceptsDestination: (next, _saved, receipt) => next.pathname === "/web/debts/" + encodeURIComponent(receipt.public_id),
    relatedAction: submitter => submitter?.getAttribute("formaction") === "/web/debts/rate",
    updatePresentation(form, {phase}) {
      form.querySelector("[data-debtcreation-draft-status]").className = phase === "editing" ? "hint" : "product-feedback";
      const submit = [...form.elements].find(input => input.matches("[data-debtcreation-submit]"));
      form.querySelectorAll('[formaction="/web/debts/rate"]').forEach(button => { button.disabled = submit.disabled; });
    },
  };
  const accepted = document.querySelector("[data-debtcreation-accepted]");
  if (accepted) {
    Promise.resolve().then(async () => {
      const result = JSON.parse(accepted.dataset.debtcreationAccepted);
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:debtcreation-create-draft:v1:",
        fields: [...names, "amount_placeholder", "amount_inputmode"], validRef});
      await window.navigator.locks.request(store.key(result.clientRef), async () => {
        const record = store.read(result.clientRef);
        if (!record) return;
        if (!store.matches(record.scope, result.scope) || !receiptMatches(result.receipt, record.values) ||
            !store.acknowledge(result)) throw Error("original_not_acknowledged");
      });
    }).catch(() => {
      accepted.querySelector("[role=status]").textContent = "这笔往来已保存。浏览器原稿尚未收起，请保留浏览器数据并在原记录核对。";
    });
    return;
  }
  const forms = document.querySelectorAll("form[data-debtcreation-draft-scope]");
  forms.forEach(form => {
    field(form, "currency_code").addEventListener("change", () => {
      field(form, "currency_minor_digits").value = field(form, "currency_code").selectedOptions[0].dataset.minorDigits;
      definition.present(form, Object.fromEntries(names.map(name => [name, field(form, name)?.value || ""])));
    });
    window.TicketboxPlanEntry.mount(form, definition);
  });
  const shelf = document.querySelector("[data-debtcreation-draft-shelf][data-draft-scope]");
  if (!forms.length && shelf) window.TicketboxPlanEntry.mountShelf(shelf, definition, JSON.parse(shelf.dataset.draftScope));
})(window, document);
