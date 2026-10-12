/* Acceptance keeps its original target; the invitation is the command identity. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "public_id", "target_ledger_id", "target_ledger_name", "title", "amount_cents", "home_currency_code"];
  const field = (form, name) => form.elements.namedItem(name);
  const definition = {family: "splitaccept", label: "接受任务", editLabel: "接受", list: "/web/bill-splits/inbox",
    create: names, edit: names, titleField: "title", commandRefField: "public_id", commandKeyField: "public_id",
    draftRefField: "draft_ref", multiple: true, embedded: true, reviewRequiresRejection: true,
    submitSelector: "[data-splitaccept-submit]", pendingLabel: "核实原接受结果",
    inactiveMessage: "这份邀请当前不能重新接受。原选择仍保留；结果待确认的提交可以继续核实。",
    href(record, scope) {
      const next = new URL(record ? "/web/bill-splits/" + encodeURIComponent(record.values.public_id) + "/accept" :
        "/web/bill-splits/inbox", window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      if (record) { next.searchParams.set("original_only", "true"); next.hash = "splitaccept-edit-" + record.clientRef; }
      return next.href;
    },
    read(form) {
      const values = Object.fromEntries(names.map(name => [name, field(form, name).value]));
      values.target_ledger_name = field(form, "target_ledger_id").selectedOptions[0]?.textContent || values.target_ledger_name;
      return values;
    },
    restore(form, saved) {
      const target = field(form, "target_ledger_id");
      if (![...target.options].some(option => option.value === saved.target_ledger_id)) {
        target.add(new Option(saved.target_ledger_name || "原选择账本（当前不可写）", saved.target_ledger_id));
      }
      names.forEach(name => { field(form, name).value = saved[name]; });
      // Keep the recorded name too: a later rename must not change an unknown command snapshot.
      target.selectedOptions[0].textContent = saved.target_ledger_name;
    },
    body(body, saved) { names.forEach(name => body.set(name, saved[name])); },
    updatePresentation(form, {phase, editable}) {
      const note = form.querySelector("[data-splitaccept-target-note]");
      note.hidden = phase === "editing" && editable;
      note.textContent = "原选择账本：" + (field(form, "target_ledger_name").value || "未选择");
    },
    receiptMatches: (receipt, saved) => receipt?.public_id === saved.public_id && receipt.status === "accepted" &&
      receipt.target_ledger_id === saved.target_ledger_id && String(receipt.amount_cents) === saved.amount_cents &&
      receipt.home_currency_code === saved.home_currency_code,
    acceptsDestination: (next, saved) => next.pathname === "/web/bill-splits/inbox" && next.searchParams.get("accepted") === saved.public_id,
  };
  const forms = document.querySelectorAll("form[data-splitaccept-draft-scope]");
  forms.forEach(form => window.TicketboxPlanEntry.mount(form, definition));
  const shelf = document.querySelector("[data-splitaccept-draft-shelf][data-draft-scope]");
  if (!forms.length && shelf) window.TicketboxPlanEntry.mountShelf(shelf, definition, JSON.parse(shelf.dataset.draftScope));
})(window, document);
