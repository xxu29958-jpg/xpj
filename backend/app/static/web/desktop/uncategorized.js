/* A selected batch uses the existing bound draft/lease owner and its original command receipt. */
(function (window, document) {
  "use strict";
  const fields = ["ledger_id", "filter", "category", "idempotency_key", "draft_ref", "origin_receipt", "selected_rows"];
  function boxes(form) { return [...form.querySelectorAll('input[name="expense_snapshot"]')]; }
  function read(form) {
    const selected = boxes(form).filter(box => box.checked).map(box => ({snapshot: box.value,
      label: box.closest("[data-category-row]").querySelector("strong").textContent}));
    form.elements.selected_rows.value = JSON.stringify(selected);
    return Object.fromEntries(fields.map(name => [name, form.elements.namedItem(name)?.value || ""]));
  }
  function href(record, scope, form) {
    const saved = record?.values;
    const next = new URL("/web/categories/uncategorized", window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    const filter = saved?.filter || form?.elements.filter.value;
    if (filter) next.searchParams.set("filter", filter);
    if (saved?.origin_receipt) next.searchParams.set("receipt", saved.origin_receipt);
    if (record) next.hash = "categorybatch-create-" + record.clientRef;
    else next.searchParams.set("new_categorybatch", "1");
    return next.href;
  }
  function detailHref(form, identity) {
    const next = new URL("/web/expenses/" + identity + "/edit", window.location.href);
    next.searchParams.set("ledger_id", form.elements.ledger_id.value);
    next.searchParams.set("return_to", "uncategorized");
    next.searchParams.set("return_filter", form.elements.filter.value);
    next.searchParams.set("return_category_draft_ref", form.elements.draft_ref.value);
    if (form.elements.origin_receipt.value) next.searchParams.set("return_category_receipt_key", form.elements.origin_receipt.value);
    return next.href;
  }
  function continueBatch(saved, receipt) {
    const successful = new Set(receipt.result.success_ids);
    const remaining = JSON.parse(saved.selected_rows).filter(row => !successful.has(Number(row.snapshot.split(":")[0])));
    return remaining.length ? {...saved, selected_rows: JSON.stringify(remaining), origin_receipt: saved.idempotency_key,
      idempotency_key: window.crypto.randomUUID()} : undefined;
  }
  function restore(form, saved) {
    for (const name of fields.filter(name => name !== "category")) form.elements.namedItem(name).value = saved[name];
    boxes(form).forEach(box => { box.checked = false; });
    for (const selected of JSON.parse(saved.selected_rows)) {
      if (!/^[1-9]\d*:[1-9]\d*$/.test(selected.snapshot) || typeof selected.label !== "string") throw Error("invalid_original_selection");
      const identity = selected.snapshot.split(":")[0];
      let row = form.querySelector('[data-category-row="' + identity + '"]');
      if (!row) {
        row = form.querySelector("[data-category-row-template]").content.firstElementChild.cloneNode(true);
        row.dataset.categoryRow = identity;
        form.querySelector(".uncategorized-list").append(row);
      }
      const box = row.querySelector("input");
      row.querySelector("label").setAttribute("aria-label", "选择 " + selected.label);
      row.querySelector("[data-category-retained]").hidden = box.value === selected.snapshot;
      box.value = selected.snapshot; box.checked = true;
      row.querySelector("strong").textContent = selected.label;
      row.querySelector("a").href = detailHref(form, identity);
    }
    let chosen = [...form.querySelectorAll('[name="category"]')].find(input => input.value === saved.category);
    if (saved.category && !chosen) {
      const label = document.createElement("label"); label.className = "uncategorized-choice";
      chosen = document.createElement("input"); chosen.type = "radio"; chosen.name = "category"; chosen.value = saved.category; chosen.required = true;
      const title = document.createElement("strong"); title.textContent = saved.category;
      label.append(chosen, title); form.querySelector(".uncategorized-choices").append(label);
    }
    form.querySelectorAll('[name="category"]').forEach(input => { input.checked = input === chosen; });
  }
  function init() {
    const form = document.querySelector(".uncategorized-form");
    if (!form) return;
    const all = form.querySelector("#select-all"), button = form.querySelector("[data-category-apply]");
    const resultLink = form.querySelector("[data-category-result]");
    const review = form.querySelector("[data-categorybatch-review]"), reviewNote = form.querySelector("[data-categorybatch-review-note]");
    if (review) {
      review.textContent = "已核对，采用当前内容";
      reviewNote.textContent = "如账单已在其他端修改，请先打开核对，再采用当前内容。分类选择仍保留，应用时需再次确认。";
    }
    let state = {phase: "editing", editable: form.dataset.categorybatchCanWrite === "true", busy: false};
    let continuity = null;
    function refresh() {
      const items = boxes(form), count = items.filter(box => box.checked).length;
      all.closest("label").hidden = !items.length || form.dataset.categorybatchCanWrite !== "true";
      all.disabled = !state.editable || state.busy;
      all.checked = items.length > 0 && count === items.length;
      all.indeterminate = count > 0 && count < items.length;
      form.querySelector(".uncategorized-category-field").hidden = !items.length;
      form.querySelector(".uncategorized-explanation").hidden = !items.length;
      document.querySelector("[data-category-count]").textContent = items.length;
      document.querySelector("[data-category-empty]").hidden = items.length > 0;
      resultLink.hidden = !form.elements.origin_receipt.value;
      const resultHref = new URL("/web/categories/uncategorized", window.location.href);
      resultHref.searchParams.set("ledger_id", form.elements.ledger_id.value);
      resultHref.searchParams.set("receipt", form.elements.origin_receipt.value);
      resultHref.hash = "categorybatch-create-" + form.elements.draft_ref.value;
      resultLink.href = resultHref.href;
      if (state.phase === "editing") {
        button.hidden = form.dataset.categorybatchCanWrite !== "true" || !items.length;
        button.textContent = count ? "应用到 " + count + " 笔" : "先选择账单";
        button.disabled = !state.editable || state.busy || count === 0;
        if (review && !count) { review.hidden = true; reviewNote.hidden = true; }
      }
      for (const row of form.querySelectorAll("[data-category-row]")) row.querySelector("a").href = detailHref(form, row.dataset.categoryRow);
    }
    all.addEventListener("change", () => { boxes(form).forEach(box => { if (!box.disabled) box.checked = all.checked; }); refresh(); });
    form.addEventListener("change", refresh);
    form.addEventListener("click", event => {
      if (!event.target.closest("[data-category-detail], [data-category-result]")) return;
      form.dispatchEvent(new Event("change", {bubbles: true}));
      if (continuity?.hasUnretainedInput()) { event.preventDefault(); return; }
      if (event.target.closest("[data-category-result]") && resultLink.href === window.location.href) {
        event.preventDefault(); window.location.reload();
      }
    });
    if (form.dataset.categorybatchDraftScope && window.TicketboxPlanEntry) {
      const location = new URL(window.location.href);
      if (location.searchParams.get("draft_ref") && !location.hash) {
        location.hash = "categorybatch-create-" + location.searchParams.get("draft_ref");
        window.history.replaceState(window.history.state, "", location.href);
      }
      continuity = window.TicketboxPlanEntry.mount(form, {family: "categorybatch", label: "分类任务", creationLabel: "补分类", list: "/web/categories/uncategorized",
        create: fields, edit: fields, repeated: ["expense_snapshot"], titleField: "category",
        commandKeyField: "idempotency_key", draftRefField: "draft_ref", pendingLabel: "核实本次分类结果",
        reviewName: "review_latest", reviewWhileEditing: true, reviewRequiresRejection: true, href, read, restore, present: () => {},
        continueAfterAcceptance: continueBatch,
        body(body, saved) {
          for (const name of fields.filter(name => name !== "selected_rows")) body.set(name, saved[name]);
          for (const selected of JSON.parse(saved.selected_rows)) body.append("expense_snapshot", selected.snapshot);
        },
        updatePresentation(current, value) { state = value; refresh(); },
        receiptMatches(receipt, saved) {
          const selected = Object.fromEntries(JSON.parse(saved.selected_rows).map(row => row.snapshot.split(":").map(Number)));
          return receipt?.command_key === saved.idempotency_key && receipt.category === saved.category.trim() && receipt.filter === saved.filter &&
            Object.keys(receipt.selected_versions || {}).length === Object.keys(selected).length &&
            Object.entries(selected).every(([id, version]) => receipt.selected_versions[id] === version);
        },
        acceptsDestination: (next, saved) => next.pathname === "/web/categories/uncategorized" && next.searchParams.get("receipt") === saved.idempotency_key,
      });
    }
    window.addEventListener("pageshow", refresh);
    refresh();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})(window, document);
