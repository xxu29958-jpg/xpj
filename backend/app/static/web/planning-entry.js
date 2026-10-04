/* Field adapters for the existing planning draft/receipt owner. */
(function (window, document) {
  "use strict";
  const monthly = ["ledger_id", "month", "home_currency_code", "expected_row_version"];
  const repeated = ["excluded_category", "category_budget_category", "category_budget_amount_yuan", "category_budget_remove"];
  const definitions = {
    budget: {label: "月度预算", list: "/web/budgets", amount: "total_amount_yuan", idField: "month", titleField: "month",
      names: [...monthly, "return_category", "return_month", "total_amount_yuan", "rollover_amount_yuan",
        "non_monthly_amount_yuan", "excluded_categories", "excluded_values", "category_rows", "input_step", "input_hint"], repeated},
    arrangement: {label: "本月安排", list: "/web/budget-advise", amount: "savings_target_yuan", idField: "month", titleField: "month",
      names: [...monthly, "arrangement_currency_code", "savings_target_yuan", "reserved_buffer_yuan"],
      action: "/web/budget-advise/save"},
    recurring: {label: "固定支出", list: "/web/recurring", amount: "baseline_amount_yuan", titleField: "merchant", multiple: true,
      names: ["ledger_id", "public_id", "home_currency_code", "expected_row_version", "merchant", "baseline_amount_yuan", "next_expected_date"]},
  };
  function field(form, name) { return form.elements.namedItem(name); }
  function writeFields(form, saved, names) {
    names.forEach(name => {
      const input = field(form, name);
      if (!input) return;
      if (input.tagName === "SELECT" && ![...input.options].some(option => option.value === saved[name])) {
        input.add(new Option(saved[name], saved[name]));
      }
      input.value = saved[name];
    });
  }
  function budgetRows(form) {
    return [...form.querySelectorAll('[name="category_budget_category"]')].map(input => {
      const row = input.closest("tr, [data-budget-add-row]");
      const remove = row.querySelector('[name="category_budget_remove"]');
      return {category: input.value, amount: row.querySelector('[name="category_budget_amount_yuan"]').value,
        savedCategory: row.dataset.savedCategory || "", removeValue: remove?.value ?? null, removed: !!remove?.checked};
    });
  }
  function restoreBudget(form, saved, prototype) {
    const editor = form.closest("#budget-editor");
    if (editor) editor.open = true;
    const excluded = JSON.parse(saved.excluded_values);
    let chips = form.querySelector('[aria-label="可排除的分类"]');
    if (!chips) {
      chips = document.createElement("div"); chips.className = "budget-chip-grid";
      chips.setAttribute("role", "group"); chips.setAttribute("aria-label", "可排除的分类");
      form.querySelector(".budget-excluded .product-field").before(chips);
    }
    excluded.forEach(value => {
      if ([...form.querySelectorAll('[name="excluded_category"]')].some(input => input.value === value)) return;
      const label = document.createElement("label"), input = document.createElement("input");
      label.className = "budget-chip"; input.type = "checkbox"; input.name = "excluded_category"; input.value = value;
      label.append(input, document.createTextNode(value)); chips.append(label);
    });
    form.querySelectorAll('[name="excluded_category"]').forEach(input => { input.checked = excluded.includes(input.value); });
    const selectedLabels = excluded.map(value => [...chips.querySelectorAll('[name="excluded_category"]')]
      .find(input => input.value === value).closest("label"));
    chips.prepend(...selectedLabels);
    // Current execution stays attached to its saved category. Original inputs get
    // their own rows, never re-labelled as the refreshed server's current facts.
    form.querySelectorAll(".budget-table input").forEach(input => {
      const span = document.createElement("span");
      span.textContent = input.type === "checkbox" ? "已保存" : input.value;
      if (input.type === "checkbox") input.closest("label").replaceWith(span);
      else input.replaceWith(span);
    });
    const lastHeading = form.querySelector(".budget-table thead th:last-child");
    if (lastHeading) lastHeading.textContent = "当前配置";
    const rows = form.querySelector(".budget-add-rows");
    rows.replaceChildren();
    JSON.parse(saved.category_rows).forEach(row => {
      const node = prototype.cloneNode(true);
      node.dataset.savedCategory = row.savedCategory;
      node.querySelector('[name="category_budget_category"]').value = row.category;
      node.querySelector('[name="category_budget_amount_yuan"]').value = row.amount;
      if (row.removeValue !== null) {
        const label = document.createElement("label"), input = document.createElement("input");
        label.className = "budget-remove"; input.type = "checkbox"; input.name = "category_budget_remove";
        input.value = row.removeValue; input.checked = row.removed;
        label.append(input, document.createTextNode("移除 · 原稿分类：" + row.savedCategory)); node.append(label);
      }
      rows.append(node);
    });
    form.querySelector(".budget-add-title").textContent = "原稿中的分类预算（" + saved.home_currency_code + "）";
    form.querySelectorAll('input[type="number"]').forEach(input => {
      input.step = saved.input_step; input.inputMode = saved.amount_inputmode;
    });
  }
  Object.entries(definitions).forEach(([family, definition]) => {
    document.querySelectorAll("[data-" + family + "-draft-scope]").forEach(form => {
      const names = definition.names;
      const prototype = family === "budget" ? form.querySelector("[data-budget-add-row]").cloneNode(true) : null;
      const href = (record, scope, currentForm) => {
        const values = record?.values || Object.fromEntries(names.map(name => [name, field(currentForm, name)?.value || ""]));
        const next = new URL(definition.list, window.location.href);
        next.searchParams.set("ledger_id", scope.ledgerId);
        for (const name of ["month", "return_category", "return_month"]) if (values[name]) next.searchParams.set(name, values[name]);
        if (values.public_id) next.searchParams.set("edit", values.public_id);
        if (record) next.hash = family + (values[definition.idField || "public_id"] ? "-edit-" : "-create-") + record.clientRef;
        else next.searchParams.set("new_" + family, "1");
        return next.href;
      };
      window.TicketboxPlanEntry.mount(form, {...definition, family, href, create: names, edit: names,
        reviewRequiresRejection: true,
        reviewName: "review_latest", submitSelector: "[data-" + family + "-submit]",
        validRef: /^[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}$/i,
        read: current => {
          const values = Object.fromEntries(names.map(name => [name, field(current, name)?.value || ""]));
          if (family === "budget") {
            values.excluded_values = JSON.stringify([...current.querySelectorAll('[name="excluded_category"]')].filter(input => input.checked).map(input => input.value));
            values.category_rows = JSON.stringify(budgetRows(current));
            values.input_step = field(current, definition.amount).step;
            values.input_hint = current.querySelector("[data-plan-amount-hint]").textContent;
          }
          return values;
        },
        restore: (current, saved) => {
          writeFields(current, saved, names);
          if (family === "budget") restoreBudget(current, saved, prototype);
        },
        present: (current, saved) => {
          const currency = saved.arrangement_currency_code || saved.home_currency_code || "币种待确认";
          current.querySelectorAll("[data-plan-currency]").forEach(label => { label.textContent = currency; });
          if (family === "budget") current.querySelector("[data-plan-amount-hint]").textContent = saved.input_hint;
        },
        body: (body, saved) => {
          names.filter(name => !["excluded_values", "category_rows", "input_step", "input_hint"].includes(name)).forEach(name => body.set(name, saved[name]));
          if (family !== "budget") return;
          JSON.parse(saved.excluded_values).forEach(value => body.append("excluded_category", value));
          JSON.parse(saved.category_rows).forEach(row => {
            body.append("category_budget_category", row.category); body.append("category_budget_amount_yuan", row.amount);
            if (row.removed) body.append("category_budget_remove", row.removeValue);
          });
        },
        receiptMatches: (receipt, saved) => family === "recurring" ?
          receipt?.public_id && (!saved.public_id || receipt.public_id === saved.public_id) :
          receipt?.month === saved.month && Number.isInteger(receipt.row_version),
      });
    });
  });
})(window, document);
