/* Debt selection adapter; leases, drafts and receipt acceptance belong to PlanEntry. */
(function (window, document) {
  "use strict";
  const names = ["ledger_id", "public_id", "task_id", "task", "name", "expected_row_version", "target_date", "selected_debts"];
  const field = (form, name) => form.elements.namedItem(name);
  const href = (record, scope, form) => {
    const saved = record?.values || Object.fromEntries(names.map(name => [name, field(form, name)?.value || ""]));
    const next = new URL("/web/debt-goals/" + (saved.public_id ? encodeURIComponent(saved.public_id) + "/" + saved.task : "new"), window.location.href);
    next.searchParams.set("ledger_id", scope.ledgerId);
    if (record) next.hash = "debtgoal-" + (saved.public_id ? "edit-" : "create-") + record.clientRef;
    else next.searchParams.set("new_debtgoal", "1");
    return next.href;
  };
  const definition = {family: "debtgoal", label: "还债目标", list: "/web/debt-goals", titleField: "name", idField: "task_id",
    create: names, edit: names, repeated: ["debt_public_ids"], href, reviewName: "review_latest",
    reviewRequiresRejection: true,
    read(form) {
      return {...Object.fromEntries(names.filter(name => name !== "selected_debts").map(name => [name, field(form, name)?.value || ""])),
        selected_debts: JSON.stringify([...form.querySelectorAll('[name="debt_public_ids"]:checked')].map(input => ({
          id: input.value, name: input.closest("label").querySelector(".plan-choice-name").textContent,
        })))};
    },
    restore(form, saved) {
      names.filter(name => name !== "selected_debts").forEach(name => { if (field(form, name)) field(form, name).value = saved[name]; });
      const selected = JSON.parse(saved.selected_debts);
      const set = form.querySelector(".plan-choice-set");
      selected.forEach(debt => {
        if ([...form.querySelectorAll('[name="debt_public_ids"]')].some(input => input.value === debt.id)) return;
        const label = document.createElement("label"), input = document.createElement("input"), name = document.createElement("span"), meta = document.createElement("span");
        label.className = "plan-choice"; input.type = "checkbox"; input.name = "debt_public_ids"; input.value = debt.id;
        name.className = "plan-choice-name"; name.textContent = debt.name;
        meta.className = "plan-choice-meta"; meta.textContent = "原稿中的选择，当前不可关联；请核对后继续。";
        label.append(input, name, meta); set.append(label);
      });
      form.querySelectorAll('[name="debt_public_ids"]').forEach(input => { input.checked = selected.some(debt => debt.id === input.value); });
      if (set) set.querySelector("legend").after(...selected.map(debt => {
        const input = [...form.querySelectorAll('[name="debt_public_ids"]')].find(item => item.value === debt.id);
        input.closest("label").querySelector(".plan-choice-name").textContent = debt.name;
        return input.closest("label");
      }));
    },
    body(body, saved) {
      names.filter(name => name !== "selected_debts").forEach(name => body.set(name, saved[name]));
      JSON.parse(saved.selected_debts).forEach(debt => body.append("debt_public_ids", debt.id));
    },
    receiptMatches: (receipt, saved) => receipt?.public_id && receipt.goal_type === "debt_repayment" &&
      (!saved.public_id || receipt.public_id === saved.public_id),
  };
  const forms = document.querySelectorAll("[data-debtgoal-draft-scope]");
  forms.forEach(form => window.TicketboxPlanEntry.mount(form, definition));
  const shelf = document.querySelector("[data-debtgoal-draft-shelf][data-draft-scope]");
  if (!forms.length && shelf) window.TicketboxPlanEntry.mountShelf(shelf, definition, JSON.parse(shelf.dataset.draftScope));
})(window, document);
