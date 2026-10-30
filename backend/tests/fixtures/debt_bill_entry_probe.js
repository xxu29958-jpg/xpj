(async function () {
  "use strict";
  const scenario = window.__scenario, key = "debt-bill-probe:" + scenario;
  const stage = sessionStorage.getItem(key) || "start";
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async (predicate, label) => {
    for (let attempt = 0; attempt < 320; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("Timed out waiting for " + label);
  };
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  try {
    const form = document.querySelector("#debt-creation"), field = name => form.elements.namedItem(name);
    const who = field("counterparty_label"), status = form.querySelector("[data-debtbill-status]");
    const submit = document.querySelector("[data-debtcreation-submit]");
    await wait(() => !who.readOnly && !who.disabled, "an editable form");
    if (window.__legacyDraft) {
      assert(who.value === "旧原稿里的对方" && field("amount_major").value === "88.00", "An older draft lost its inputs");
      assert(!form.querySelector("[data-debtbill]").hidden && !form.querySelector("[data-debtbill-picker]").hidden,
        "An older draft hid the bill entry");
      window.__debtBillResult = {completed: true};
      return;
    }
    let creates = 0;
    const fetchOriginal = window.fetch;
    window.fetch = (url, options) => {
      if (options?.method === "POST" && new URL(url, location.href).pathname === "/web/debts") creates++;
      return fetchOriginal(url, options);
    };
    // Click and implicit (Enter) submission both go through the form's submit event.
    async function tryToSubmitEarly(reason) {
      assert(submit.disabled, "Submit stayed available while " + reason);
      submit.click(); form.requestSubmit();
      await pause(300);
      assert(creates === 0, "A debt was sent while " + reason);
    }
    async function finish(filled) {
      await wait(() => status.textContent.includes(filled ? "已按原账单建议补全空白项" : "建议暂不可用"), "the parse outcome");
      assert(who.value === "我自己填的对方", "The person's counterparty was overwritten");
      assert(field("bill_source_public_id").value === "source-1", "The retained source is missing");
      if (filled) {
        assert(field("amount_major").value === "1200.00" && field("installment_count").value === "12" &&
          field("installment_period_months").value === "1" && field("debt_kind").value === "installment", "Blanks were not completed");
      }
      await wait(() => !submit.disabled, "submission to reopen once the bill settled");
      submit.click();
    }
    if (stage === "reloaded") { await finish(true); return; }
    who.value = "我自己填的对方"; who.dispatchEvent(new Event("input", {bubbles: true}));
    if (scenario === "parse-failed") {
      const amount = field("amount_major"); amount.value = "66.00"; amount.dispatchEvent(new Event("input", {bubbles: true}));
    }
    const setItem = Storage.prototype.setItem;
    if (scenario === "storage") {
      Storage.prototype.setItem = function (name, value) {
        if (String(value).includes('"bill_source_public_id":"source-1"')) throw Error("QuotaExceededError");
        return setItem.call(this, name, value);
      };
    }
    const canvas = document.createElement("canvas"); canvas.width = 120; canvas.height = 80;
    canvas.getContext("2d").fillRect(10, 10, 40, 20);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    const files = new DataTransfer(); files.items.add(new File([blob], "借条.png", {type: "image/png"}));
    const input = form.querySelector("[data-debtbill-file]");
    input.files = files.files; input.dispatchEvent(new Event("change", {bubbles: true}));
    if (scenario === "delayed") {
      await tryToSubmitEarly("the bill was still uploading");
      await finish(true);
    } else if (scenario === "lost") {
      await wait(() => status.textContent.includes("暂时无法确认原账单是否已保存"), "the inconclusive read-back");
      await tryToSubmitEarly("the bill could not be confirmed");
      sessionStorage.setItem(key, "reloaded"); location.reload();
    } else if (scenario === "storage") {
      await wait(() => status.textContent.includes("本机原稿未能记下它"), "the unretained source");
      assert(field("bill_source_public_id").value === "" && field("bill_capture_key").value, "The page shows more than the draft holds");
      await tryToSubmitEarly("the draft could not keep the source");
      Storage.prototype.setItem = setItem;
      sessionStorage.setItem(key, "reloaded"); location.reload();
    } else await finish(false);
  } catch (error) {
    window.__debtBillResult = {error: String(error && error.stack || error), stage};
  }
})();
