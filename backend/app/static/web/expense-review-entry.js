/* Receipt review retains its original fields and confirm key in the existing draft owner. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "expense_id", "expected_row_version", "idempotency_key", "keep_idempotency_key", "reject_idempotency_key", "draft_ref", "save_before_confirm", "command_action",
    "amount_yuan", "original_currency", "manual_exchange_rate", "merchant", "category", "note", "tags", "expense_time",
    "time_precision", "calendar_revision", "user_local_date", "source_timezone", "source_utc_offset_seconds", "accounting_date", "value_score", "regret_score"];
  const names = [...fields, "return_context", "present_fields", "reject_row_version", "undo_idempotency_key"];
  function read(form) {
    const values = Object.fromEntries(fields.map(name => [name, form.elements.namedItem(name)?.value || ""]));
    values.present_fields = JSON.stringify(fields.filter(name => form.elements.namedItem(name) &&
      (!["command_action", "keep_idempotency_key", "reject_idempotency_key"].includes(name) || values[name])));
    values.return_context = JSON.stringify(Object.fromEntries([...form.elements].filter(input => input.name.startsWith("return_")).map(input => [input.name, input.value])));
    values.reject_row_version = form.elements.namedItem("reject_row_version")?.value || "";
    values.undo_idempotency_key = form.elements.namedItem("undo_idempotency_key")?.value || "";
    return values;
  }
  function put(form, name, value) {
    let input = form.elements.namedItem(name);
    if (!input) { input = document.createElement("input"); input.type = "hidden"; input.name = name; form.append(input); }
    window.TicketboxWeb.putReviewField(input, value);
    (typeof input.dispatchEvent === "function" ? input : input[0]).dispatchEvent(new Event("input"));
  }
  function restoreScoreAvailability(form, present, originalPhase) {
    // A submitted pre-score original cannot acquire today's controls or score values.
    if (originalPhase === "editing") return;
    for (const name of ["value_score", "regret_score"].filter(name => !present.includes(name))) {
      form.querySelectorAll('[name="' + name + '"]').forEach(input => {
        input.closest("fieldset").hidden = true;
        input.remove();
      });
    }
    const scores = form.querySelector(".score-fields");
    if (scores) scores.closest("details").hidden = !scores.querySelector("input");
  }
  function href(record, scope, form) {
    const values = record?.values || read(form);
    const next = new URL("/web/expenses/" + encodeURIComponent(values.expense_id) + "/edit", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    for (const [key, value] of Object.entries(JSON.parse(values.return_context))) next.searchParams.set(key, value);
    next.searchParams.set("confirmation_task", "1");
    if (record) next.hash = "expensereview-edit-" + record.clientRef;
    else next.searchParams.set("new_expensereview", "1");
    return next.href;
  }
  function rejectionReceiptMatches(receipt, saved) {
    return receipt?.id === Number(saved.expense_id) && receipt.status === "rejected" &&
      Number.isInteger(receipt.row_version) && typeof receipt.undo_idempotency_key === "string";
  }
  function receiptMatches(receipt, saved) {
    return saved.command_action === "reject" ? rejectionReceiptMatches(receipt, saved) : saved.command_action === "keep" ?
        receipt?.operation === "mark_not_duplicate" && receipt.expense_id === Number(saved.expense_id) &&
        receipt.accepted === true && receipt.decision_key === saved.keep_idempotency_key : saved.command_action === "save" ?
        receipt?.operation === "patch_expense" && receipt.expense_id === Number(saved.expense_id) && receipt.accepted === true :
        receipt?.id === Number(saved.expense_id) && receipt.status === "confirmed" &&
        Number.isInteger(receipt.amount_cents) && receipt.amount_cents >= 0 &&
        typeof receipt.home_currency === "string" && typeof receipt.confirmed_at === "string";
  }
  function mount(form, options = {}) {
    if (!form.dataset.expensereviewDraftScope) return;
    form.addEventListener("submit", event => {
      if (form.dataset.expensereviewDraftPhase !== "editing" || event.submitter?.name === "review_latest") return;
      const action = new URL(event.submitter?.getAttribute("formaction") || form.action, window.location.href);
      if (/\/(save|confirm|keep|reject)$/.test(action.pathname)) {
        if (requiresReview(form)) {
          event.preventDefault(); event.stopImmediatePropagation();
          form.querySelector("[data-expensereview-review]").focus(); return;
        }
        form.elements.command_action.value = action.pathname.split("/").pop();
      }
    });
    const continuity = window.TicketboxPlanEntry.mount(form, {
      family: "expensereview", label: "核对任务", list: "/web/pending", create: names, edit: names,
      idField: "expense_id", titleField: "merchant", commandKeyField: saved =>
        ["keep", "reject"].includes(saved.command_action) ? saved.command_action + "_idempotency_key" : "idempotency_key", draftRefField: "draft_ref",
      submitSelector: "[data-expensereview-submit]", pendingLabel: "核实这次结果",
      legacyMissing: ["command_action", "keep_idempotency_key", "reject_idempotency_key", "reject_row_version", "undo_idempotency_key", "value_score", "regret_score"],
      embedded: options.embedded, onAccepted: options.onAccepted, multiple: !options.embedded,
      action: saved => saved.command_action === "keep" ? "/web/duplicates/" + saved.expense_id + "/keep" :
        "/web/expenses/" + saved.expense_id + "/" + (saved.command_action || "confirm"),
      continueAfterAcceptance: (saved, receipt) => saved.command_action === "reject" ?
        {...saved, command_action: "confirm", reject_row_version: String(receipt.row_version), undo_idempotency_key: receipt.undo_idempotency_key} :
        saved.command_action === "keep" ? {...saved, command_action: "confirm"} : undefined,
      reviewRequiresRejection: true, reviewWhileEditing: true,
      inactiveMessage: "账单已离开待确认状态。原输入仍保留；已发出的提交可核实原结果。",
      read, href, present: () => {},
      restore(current, values, originalPhase) {
        const present = JSON.parse(values.present_fields);
        for (const name of present) put(current, name, values[name]);
        restoreScoreAvailability(current, present, originalPhase);
        put(current, "command_action", values.command_action || "");
        for (const name of ["reject_row_version", "undo_idempotency_key"]) put(current, name, values[name] || "");
        // A submitted v1 original cannot acquire this page's newly generated related-command keys.
        for (const name of ["keep_idempotency_key", "reject_idempotency_key"]) {
          if (originalPhase !== "editing") put(current, name, values[name] || "");
        }
        for (const input of [...current.elements].filter(input => input.name.startsWith("return_"))) input.remove();
        for (const [name, value] of Object.entries(JSON.parse(values.return_context))) put(current, name, value);
      },
      body(body, values) {
        for (const name of JSON.parse(values.present_fields)) body.set(name, values[name]);
        for (const [name, value] of Object.entries(JSON.parse(values.return_context))) body.set(name, value);
      },
      relatedAction: submitter => form.dataset.expensereviewDraftPhase === "editing" &&
        submitter?.name !== "review_latest" && submitter?.hasAttribute("formaction") &&
        !/\/(save|confirm|keep|reject)$/.test(new URL(submitter.getAttribute("formaction"), window.location.href).pathname),
      receiptMatches,
      acceptsDestination: (next, saved) => saved.command_action === "reject" ?
        (next.pathname === "/web/pending" || /^\/web\/recurring\/[^/]+\/occurrence$/.test(next.pathname)) && next.searchParams.get("undo") === saved.expense_id : saved.command_action === "keep" ?
        next.pathname === "/web/expenses/" + saved.expense_id + "/edit" && next.hash === "#expensereview-edit-" + saved.draft_ref : saved.command_action === "save" ?
        next.pathname === "/web/expenses/" + saved.expense_id + "/edit" && next.searchParams.get("new_expensereview") === "1" :
        next.pathname === "/web/expenses/" + saved.expense_id + "/confirmation/" + saved.idempotency_key,
      updatePresentation(current, state) {
        const pending = state.phase !== "editing";
        const basisChanged = !pending && requiresReview(current);
        current.classList.toggle("expense-review-needs-review", basisChanged);
        const action = ["save", "keep", "reject"].includes(current.elements.command_action.value) ? current.elements.command_action.value : "confirm";
        const copy = {reject: ["正在核实这次忽略", "核实这次忽略"], keep: ["正在核实这次非重复决定", "核实这次非重复决定"],
          save: ["正在核实这次保存", "核实这次结果"], confirm: ["正在确认这次结果", "核实这次结果"]}[action];
        current.querySelector("[data-expensereview-recovery] h1").textContent = copy[0];
        if (pending) current.querySelector("[data-expensereview-submit]").textContent = copy[1];
        const review = current.querySelector("[data-expensereview-review]");
        if (!basisChanged && !state.rejected) {
          review.hidden = true;
          current.querySelector("[data-expensereview-review-note]").hidden = true;
        }
        review.setAttribute("formaction", action === "keep" ? "/web/duplicates/" + current.elements.expense_id.value + "/keep" :
          "/web/expenses/" + current.elements.expense_id.value + "/" + action);
        review.classList.toggle("product-button--primary", basisChanged);
        (current.closest(".product-drawer-editor") || document.body).classList.toggle("expense-review-pending", pending);
        current.querySelector("[data-expensereview-recovery]").hidden = !pending;
        current.querySelector("[data-expensereview-links]").hidden = !pending;
        current.querySelector("[data-expensereview-later]").hidden = !pending;
        const original = current.querySelector("[data-expensereview-original]");
        if (original.dataset.pending !== String(pending)) original.open = !pending;
        original.dataset.pending = String(pending);
        current.querySelector("[data-expensereview-original-toggle]").hidden = !pending;
        current.querySelector("[data-expensereview-draft-status]").classList.toggle("product-feedback--warning", pending);
        current.querySelector("[data-expensereview-summary]").textContent =
          (current.elements.merchant.value || "未填写商家") + " · 原币 " + current.elements.original_currency.value + " " + current.elements.amount_yuan.value;
        const record = {clientRef: current.elements.draft_ref.value, values: read(current)};
        const scope = {ledgerId: record.values.ledger_id};
        const currentLink = current.querySelector("[data-expensereview-current]");
        const currentHref = new URL(href(record, scope));
        currentHref.searchParams.delete("confirmation_task"); currentHref.hash = "";
        currentHref.searchParams.set("return_review_ref", current.elements.draft_ref.value);
        currentHref.searchParams.set("return_review_expense_id", current.elements.expense_id.value);
        currentLink.href = currentHref.href;
        current.querySelectorAll('button[type="submit"]').forEach(button => {
          if (!button.matches("[data-expensereview-submit], [data-expensereview-review]")) {
            const target = new URL(button.getAttribute("formaction") || current.action, window.location.href);
            button.disabled = pending || !state.editable || state.busy || (basisChanged && /\/(save|confirm|keep|reject)$/.test(target.pathname));
          }
        });
        if (basisChanged) {
          current.querySelector("[data-expensereview-submit]").disabled = true;
          const note = current.querySelector("[data-expensereview-review-note]");
          note.hidden = false;
          note.textContent = "账单状态已更新，原填写仍保留。请先核对当前记录，再继续保存或确认。";
        }
        if (options.embedded) {
          current.closest(".product-drawer-editor").querySelectorAll("[data-review-full]").forEach(link => {
            link.href = href(record, scope);
          });
        }
        const undo = current.querySelector("[data-expensereview-undo]");
        undo.hidden = pending || !record.values.reject_row_version;
        if (!undo.hidden) {
          const target = new URL("/web/expenses/" + record.values.expense_id + "/undo", window.location.href);
          target.search = new URLSearchParams({ledger_id: scope.ledgerId, undo_version: record.values.reject_row_version,
            undo_key: record.values.undo_idempotency_key, ...JSON.parse(record.values.return_context),
            return_review_ref: record.clientRef, return_review_expense_id: record.values.expense_id});
          undo.href = target.href;
        }
      },
    });
    form.expenseReviewContinuity = continuity;
    return continuity;
  }
  function requiresReview(form) {
    return !!form.dataset.expensereviewRowVersion && form.dataset.expensereviewRowVersion !== form.elements.expected_row_version.value;
  }
  function shelf(element) {
    try {
      const scope = JSON.parse(element.dataset.expensereviewScope), list = element.querySelector("ul");
      list.replaceChildren();
      const store = window.TicketboxDraftStore.createStore({prefix: "ticketbox:expensereview-edit-draft:v1:",
        fields: [...names, "amount_placeholder", "amount_inputmode"], legacyMissing: ["command_action", "keep_idempotency_key", "reject_idempotency_key", "reject_row_version", "undo_idempotency_key"],
        validRef: /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i});
      for (const record of store.list(scope)) {
        const item = document.createElement("li"), link = document.createElement("a");
        link.href = href(record, scope);
        link.dataset.expensereviewRef = record.clientRef;
        link.dataset.expenseId = record.values.expense_id;
        const fragment = new URL(link.href); fragment.searchParams.set("fragment", "1");
        link.dataset.fragmentUrl = fragment.href;
        link.textContent = (record.values.merchant || "未填写商家") + " · " + (!store.matches(record.scope, scope) ?
          "原浏览器身份，待核对" : record.phase === "editing" ? "未提交" : record.values.command_action === "reject" ? "原忽略待核实" : record.values.command_action === "keep" ? "原非重复决定待核实" : record.values.command_action === "save" ? "原保存待核实" : "原确认待核实");
        item.append(link); list.append(item);
      }
      window.TicketboxExpenseSubtasks?.appendShelf(scope, list);
      window.TicketboxExpenseRecognition?.appendShelf(scope, list);
      element.hidden = !list.childElementCount;
    } catch (_) {
      element.hidden = false;
      element.querySelector("ul").textContent = "暂时读不到本地核对任务，请恢复浏览器存储后继续。原输入不会被移除。";
    }
  }
  window.TicketboxExpenseReview = {mount, refreshShelf() { document.querySelectorAll("[data-expensereview-scope]").forEach(shelf); }};
  document.querySelectorAll("form[data-expensereview-plan-id]").forEach(form => mount(form));
  document.querySelectorAll("[data-expensereview-scope]").forEach(shelf);
})(window, document);
