/* Presentation only: the signed field remains the draft and command value. */
(function (window) {
  "use strict";
  window.TicketboxSplitSettlement = function (form) {
    const raw = form.elements.namedItem("settlement_net_amount_major");
    if (!raw) return null;
    const fallback = form.querySelector("[data-split-settlement-raw]");
    const controls = form.querySelector("[data-split-settlement-controls]");
    const direction = form.querySelector("[data-split-settlement-direction]");
    const amount = form.querySelector("[data-split-settlement-amount]");
    function magnitude(value) { return value.replace(/^(\s*)[+-]/, "$1"); }
    function signed(value, returning) {
      return magnitude(value).replace(/^(\s*)/, returning ? "$1-" : "$1");
    }
    function sync() {
      direction.value = /^\s*-/.test(raw.value) ? "return" : "pay";
      const shown = magnitude(raw.value);
      if (amount.value !== shown) amount.value = shown;
      direction.disabled = raw.readOnly;
      amount.readOnly = raw.readOnly;
    }
    amount.required = raw.required;
    raw.required = false;
    fallback.hidden = true;
    controls.hidden = false;
    sync();
    return {sync, edit(target) {
      if (raw.readOnly) return false;
      if (target === direction) raw.value = signed(raw.value, direction.value === "return");
      else if (target === amount) raw.value = /^\s*[+-]/.test(amount.value) ?
        amount.value : signed(amount.value, direction.value === "return");
      else return false;
      sync();
      return true;
    }};
  };
})(window);
