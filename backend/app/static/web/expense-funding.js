(function (window, document) {
  "use strict";
  function mount(root) {
  root.querySelectorAll("[data-funding-editor]").forEach(editor => {
    if (editor.dataset.fundingMounted) return;
    editor.dataset.fundingMounted = "true";
    const form = editor.closest("form"), raw = form.elements.namedItem("funding_json");
    const accounts = JSON.parse(editor.dataset.accounts), holder = editor.querySelector("[data-funding-rows]");
    const refund = editor.dataset.refund === "true";
    const currency = () => (form.elements.namedItem("currency_code") || form.elements.namedItem("original_currency_code") || form.elements.namedItem("original_currency")).value;
    let parts = [];
    let renderedRaw = null;
    const save = () => { raw.value = JSON.stringify(parts); renderedRaw = raw.value; raw.dispatchEvent(new Event("input", {bubbles: true})); };
    function render() {
      holder.replaceChildren();
      parts.forEach(part => {
        const row = document.createElement("div"); row.className = "product-form-grid";
        const label = (text, input) => {
          const field = document.createElement("label"); field.className = "product-field";
          field.append(document.createTextNode(text), input); row.append(field); input.className = "product-input";
        };
        const choice = document.createElement("select"); choice.add(new Option(refund ? "选择实际退入账户" : "选择实际付款账户", ""));
        accounts.filter(account => refund || account.credit_kind !== "one_off").forEach(account => choice.add(new Option(account.name + " · " + account.currency_code, account.public_id)));
        if (part.account_public_id && !accounts.some(a => a.public_id === part.account_public_id)) {
          choice.add(new Option((part.account_name || "原账户") + " · 当前不可用，原输入保留", part.account_public_id));
        }
        choice.value = part.account_public_id || "";
        choice.addEventListener("change", () => {
          const selected = accounts.find(a => a.public_id === choice.value);
          Object.assign(part, {account_public_id: choice.value, account_row_version: selected?.row_version || 0,
            account_currency: selected?.currency_code || "", account_name: selected?.name || "", expense_currency: currency()});
          if (part.account_currency === part.expense_currency) part.account_amount = part.expense_amount;
          save(); render();
        });
        label(refund ? "退款去向" : "付款账户", choice);
        for (const [key, text] of [["expense_amount", (refund ? "原币退款组成（" : "抵付消费金额（") + part.expense_currency + "）"],
          ["account_amount", (refund ? "实际退入 / 抵扣（" : "实际扣款 / 信用使用（") + (part.account_currency || "先选账户") + "）"]]) {
          if (key === "account_amount" && part.account_currency === part.expense_currency) continue;
          const input = document.createElement("input"); input.type = "text"; input.inputMode = "decimal"; input.value = part[key] || "";
          input.addEventListener("input", () => {
            part[key] = input.value;
            if (key === "expense_amount" && part.account_currency === part.expense_currency) part.account_amount = input.value;
            save();
          }); label(text, input);
        }
        if (!refund) {
          const included = document.createElement("input"); included.type = "checkbox"; included.checked = part.included_in_opening === true;
          included.onchange = () => { part.included_in_opening = included.checked; save(); };
          label("这笔旧消费已纳入该账户期初，不再扣款", included);
        }
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "product-button product-button--quiet";
        remove.textContent = refund ? "移除这个去向" : "移除这项付款"; remove.onclick = () => { parts = parts.filter(p => p !== part); save(); render(); };
        row.append(remove); holder.append(row);
      });
      disabled();
    }
    function disabled() {
      const locked = raw.readOnly || raw.disabled || raw.closest("fieldset:disabled") ||
        (form.dataset.offsetDraftPhase && form.dataset.offsetDraftPhase !== "editing") ||
        (form.dataset.expensereviewDraftPhase && form.dataset.expensereviewDraftPhase !== "editing");
      editor.querySelector("[data-funding-add]").disabled = locked || parts.length >= 8;
      holder.querySelectorAll("input, select, button").forEach(control => { control.disabled = locked; });
    }
    function restore() {
      if (renderedRaw !== raw.value) { parts = JSON.parse(raw.value || "[]"); renderedRaw = raw.value; render(); }
      else disabled();
    }
    editor.querySelector("[data-funding-add]").onclick = () => {
      parts.push({component_id: crypto.randomUUID(), account_public_id: "", account_row_version: 0,
        expense_currency: currency(), expense_amount: "", account_currency: "", account_amount: ""}); save(); render();
    };
    form.addEventListener("ticketbox:manual-restored", restore);
    form.addEventListener("ticketbox:funding-state", restore);
    restore();
  });
  }
  window.TicketboxExpenseFunding = {mount};
  mount(document);
})(window, document);
