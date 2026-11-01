/* Actual full-page and dynamically mounted drawer choices retain their manual intent. */
(async function () {
  "use strict";
  const key = "category-choices-probe";
  const stage = sessionStorage.getItem(key);
  const assert = (ok, message) => { if (!ok) throw Error(message); };
  const wait = async predicate => {
    for (let i = 0; i < 200; i += 1) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("category choice did not become ready");
  };
  const drawer = location.pathname === "/web/pending";
  const form = () => document.querySelector(drawer ? "#drawer [data-drawer-form]" : "[data-review-form]");
  const ready = () => form()?.dataset.expensereviewDraftPhase === "editing";
  try {
    if (drawer) {
      await wait(() => window.TicketboxWeb?.drawerApi);
      document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
    }
    await wait(ready);
    const current = form(), input = current.elements.category;
    if (stage === "saved") {
      assert(input.value === "交通", "server readback lost picked category");
      window.__expenseReviewResult = {saved: true}; return;
    }
    if (!stage) {
      const group = current.querySelector("[data-category-choices]");
      const button = group.querySelector('[data-category-pick="交通"]');
      assert(!group.hidden, "category choices stayed hidden");
      for (const lock of ["readOnly", "disabled"]) {
        input[lock] = true;
        await wait(() => button.disabled);
        input[lock] = false;
        await wait(() => !button.disabled);
      }
      input.closest("details").open = true;
      for (const [name, value] of [["category_choice", "suggestion"], ["category_decision_public_id", "old-suggestion"]]) {
        let field = current.elements.namedItem(name);
        if (!field) { field = document.createElement("input"); field.type = "hidden"; field.name = name; current.append(field); }
        field.value = value;
      }
      button.click();
      assert(input.value === "交通" && button.getAttribute("aria-pressed") === "true", "pick did not update category");
      assert(current.elements.category_choice.value === "manual", "pick retained suggestion provenance");
      assert(!current.elements.category_decision_public_id.value, "pick retained the old suggestion identifier");
      sessionStorage.setItem(key, "reload"); location.reload(); return;
    }
    assert(input.value === "交通" && current.elements.category_choice.value === "manual", "reload lost original manual choice");
    const version = current.elements.expected_row_version.value;
    const submit = [...current.querySelectorAll('button[type="submit"]')].find(button => button.textContent.trim() === "保存草稿");
    assert(submit && !submit.disabled, "save is unavailable after recovery");
    sessionStorage.setItem(key, "saved"); current.requestSubmit(submit);
    await wait(() => ready() && form().elements.expected_row_version.value !== version);
    assert(form().elements.category.value === "交通", "saved category was not read back");
    window.__expenseReviewResult = {saved: true};
  } catch (error) { window.__expenseReviewResult = {error: error.stack || String(error)}; }
})();
