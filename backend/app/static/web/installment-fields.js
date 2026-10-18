(function (document) {
  "use strict";
  const form = document.querySelector("[data-funds-form]");
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const save = (name, value) => { field(name).value = JSON.stringify(value); field(name).dispatchEvent(new Event("input", {bubbles: true})); };
  const draws = form.querySelector("[data-installment-draws]");
  if (draws) draws.addEventListener("change", () => save("draw_ids_json", [...draws.querySelectorAll("input:checked")].map(input => input.dataset.drawId)));
  const periods = form.querySelector("[data-installment-periods]");
  let previous = null;
  function renderPeriods() {
    if (!periods || previous === field("periods_json").value) return;
    const values = JSON.parse(field("periods_json").value || "[]"), holder = periods.querySelector("[data-period-rows]");
    previous = field("periods_json").value; holder.replaceChildren();
    values.forEach((value, index) => {
      const row = document.createElement("div"); row.className = "product-form-grid";
      for (const [key, title] of [["due_on", "第 " + (index + 1) + " 期到期日"], ["principal", "该期本金"], ["fee", "计划费用"]]) {
        const label = document.createElement("label"), input = document.createElement("input"); label.className = "product-field";
        input.className = "product-input"; input.type = key === "due_on" ? "date" : "text"; input.value = value[key] || "";
        if (key !== "due_on") input.inputMode = "decimal";
        input.oninput = () => { value[key] = input.value; previous = JSON.stringify(values); save("periods_json", values); };
        label.append(document.createTextNode(title), input); row.append(label);
      }
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "product-button product-button--quiet";
      remove.textContent = "移除这期"; remove.onclick = () => { save("periods_json", values.filter((_, n) => n !== index)); restore(); };
      row.append(remove); holder.append(row);
    });
  }
  if (periods) periods.querySelector("[data-period-add]").onclick = () => {
    save("periods_json", [...JSON.parse(field("periods_json").value || "[]"), {due_on: "", principal: "", fee: ""}]); restore();
  };
  const allocations = [...form.querySelectorAll("[data-allocation-id]")];
  allocations.forEach(row => row.addEventListener("input", () => {
    const values = JSON.parse(field("allocation_json").value || "[]").filter(value => value.public_id !== row.dataset.allocationId);
    values.push({public_id: row.dataset.allocationId, kind: row.dataset.allocationKind,
      principal: row.querySelector("[data-allocation-principal]").value, fee: row.querySelector("[data-allocation-fee]")?.value || ""});
    save("allocation_json", values);
  }));
  function restore() {
    if (draws) {
      const ids = JSON.parse(field("draw_ids_json").value || "[]");
      draws.querySelectorAll("input").forEach(input => { input.checked = ids.includes(input.dataset.drawId); input.disabled = field("draw_ids_json").readOnly; });
    }
    renderPeriods();
    if (periods) periods.querySelectorAll("input, button").forEach(input => { input.disabled = field("periods_json").readOnly; });
    const selected = JSON.parse(field("allocation_json").value || "[]");
    allocations.forEach(row => {
      const value = selected.find(item => item.public_id === row.dataset.allocationId);
      const principal = row.querySelector("[data-allocation-principal]"), fee = row.querySelector("[data-allocation-fee]");
      principal.value = value?.principal || ""; principal.disabled = field("allocation_json").readOnly;
      if (fee) { fee.value = value?.fee || ""; fee.disabled = principal.disabled; }
    });
  }
  form.addEventListener("ticketbox:funds-state", restore);
  restore();
})(document);
