(function (window, document) {
  "use strict";
  const form = document.querySelector("[data-envelope-form]");
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const read = (name, fallback) => {
    try {
      const value = JSON.parse(field(name).value);
      return value && typeof value === "object" && Array.isArray(value) === Array.isArray(fallback) ? value : fallback;
    } catch (_) { return fallback; }
  };
  const fields = ["ledger_id", "month", "home_currency_code", "expected_row_version", "idempotency_key", "note",
    "account_ids_json", "account_versions_json", "allocations_json"];
  const save = (name, value) => {
    field(name).value = JSON.stringify(value);
    field(name).dispatchEvent(new Event("input", {bubbles: true}));
  };
  const sources = [...form.querySelectorAll("[data-envelope-source]")];
  const editableSources = new Set(sources.filter(input => !input.disabled));
  const holder = form.querySelector("[data-envelope-allocations]");
  holder.addEventListener("input", event => {
    if (!event.target.dataset.envelopePurpose) return;
    const values = read("allocations_json", {});
    values[event.target.dataset.envelopePurpose] = event.target.value;
    save("allocations_json", values);
  });
  sources.forEach(input => input.addEventListener("input", () => save("account_ids_json",
    sources.filter(source => source.checked).map(source => source.dataset.envelopeSource))));
  const fillPlan = form.querySelector("[data-envelope-use-plan]");
  const hasPlan = [...holder.querySelectorAll("[data-envelope-purpose]")].some(input => input.dataset.envelopePlanned);
  fillPlan.addEventListener("click", () => {
    const values = read("allocations_json", {});
    holder.querySelectorAll("[data-envelope-purpose]").forEach(input => {
      if (input.dataset.envelopePlanned) {
        input.value = input.dataset.envelopePlanned;
        values[input.dataset.envelopePurpose] = input.value;
      }
    });
    save("allocations_json", values);
  });
  const definition = {family: "envelope", label: "信封安排", list: "/web/envelopes", idField: "month", titleField: "month",
    create: fields, edit: fields, commandKeyField: "idempotency_key", reviewName: "review_latest",
    creationLabel: "继续信封安排", editLabel: "继续信封安排", reviewRequiresRejection: true, reviewWhileEditing: true,
    submitSelector: "[data-envelope-submit]",
    href: (record, scope) => {
      const next = new URL("/web/envelopes", window.location.href);
      next.searchParams.set("ledger_id", scope.ledgerId);
      if (record) { next.searchParams.set("month", record.values.month); next.hash = "envelope-edit-" + record.clientRef; }
      return next.href;
    },
    receiptMatches: (receipt, saved) => receipt?.ledger_id === saved.ledger_id && receipt.month === saved.month &&
      receipt.home_currency_code === saved.home_currency_code && receipt.row_version > 0,
    acceptsDestination: next => next.pathname === "/web/envelopes",
    updatePresentation: (target, state) => {
      const values = read("allocations_json", {});
      fillPlan.hidden = !state.editable || !hasPlan;
      for (const [purpose, value] of Object.entries(values)) {
        let input = [...holder.querySelectorAll("[data-envelope-purpose]")].find(row => row.dataset.envelopePurpose === purpose);
        if (!input) {
          const label = document.createElement("label"); label.className = "product-field";
          label.append(document.createTextNode("保留的用途 · " + purpose.replace("category:", "")));
          input = document.createElement("input"); input.className = "product-input"; input.inputMode = "decimal";
          input.dataset.envelopePurpose = purpose; input.name = "allocation:" + purpose;
          label.append(input); holder.append(label);
        }
        input.value = value; input.readOnly = !state.editable;
      }
      const selected = read("account_ids_json", []);
      sources.forEach(input => {
        input.checked = selected.includes(input.dataset.envelopeSource);
        input.disabled = !state.editable || !editableSources.has(input);
      });
      form.dispatchEvent(new Event("ticketbox:envelope-state"));
    },
  };
  window.TicketboxPlanEntry.mount(form, definition);
})(window, document);

// Sources fold once chosen; the preview restates exactly what saving will record for this month.
(function (document) {
  "use strict";
  const form = document.querySelector("[data-envelope-form]");
  if (!form) return;
  const field = name => form.elements.namedItem(name);
  const sources = [...form.querySelectorAll("[data-envelope-source]")];
  const holder = form.querySelector("[data-envelope-allocations]");
  const options = form.querySelector("[data-envelope-options]");
  if (options) options.open = options.dataset.startExpanded === "true";
  form.addEventListener("invalid", event => { if (options?.contains(event.target)) options.open = true; }, true);
  const sourcesSummary = form.querySelector("[data-envelope-sources-summary]");
  const summary = form.querySelector("[data-envelope-summary]");
  function describe() {
    const chosen = sources.filter(input => input.checked);
    if (sourcesSummary) sourcesSummary.textContent = chosen.length ? "已选 " + chosen.length + " 个账户" : "尚未选择";
    if (!summary) return;
    const parts = [...holder.querySelectorAll("[data-envelope-purpose]")]
      .filter(input => input.value.trim() && Number(input.value) !== 0)
      .map(input => (input.closest(".product-field")?.querySelector("label")?.textContent.split(" · ")[0] || input.dataset.envelopePurpose.replace("category:", "")) + " " + input.value.trim());
    const month = field("month")?.value || "";
    const currency = field("home_currency_code")?.value || "";
    summary.textContent = parts.length
      ? "保存后，" + month + " 的用途分配为：" + parts.join("、") + "（" + currency + "）。钱仍在原账户里。"
      : "保存后，" + month + " 不为任何用途留出现金。";
    summary.hidden = false;
  }
  form.addEventListener("input", describe);
  form.addEventListener("change", describe);
  form.addEventListener("ticketbox:envelope-state", describe);
  describe();
})(document);