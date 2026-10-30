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
  async function completeCurrencyRace(form, field, submit) {
    const heldPath = scenario === "currency-capture" ? "/web/debt-bills" : "/web/debt-bills/source-1/parse";
    const calls = [], originalFetch = window.fetch;
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    window.fetch = (url, options) => {
      const path = new URL(url, location.href).pathname;
      if (options?.method === "POST") calls.push(path);
      return path === heldPath ? pending.then(() => originalFetch(url, options)) : originalFetch(url, options);
    };
    field("counterparty_label").value = "切换币种保留的对方";
    field("amount_major").value = "66.00";
    field("amount_major").dispatchEvent(new Event("input", {bubbles: true}));
    const canvas = document.createElement("canvas"); canvas.width = 120; canvas.height = 80;
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    const files = new DataTransfer(); files.items.add(new File([blob], "借条.png", {type: "image/png"}));
    const input = form.querySelector("[data-debtbill-file]");
    input.files = files.files; input.dispatchEvent(new Event("change", {bubbles: true}));
    await wait(() => calls.includes(heldPath), "the active operation before its reply");
    const retainedKey = field(scenario === "currency-capture" ? "bill_capture_key" : "bill_parse_key");
    const attempt = retainedKey.value;
    for (const currency of ["JPY", "CNY"]) {
      field("currency_code").value = currency;
      field("currency_code").dispatchEvent(new Event("change", {bubbles: true}));
    }
    await pause(300);
    assert(attempt && retainedKey.value === attempt, "Changing currency released the still-active operation key");
    assert(calls.filter(path => path === heldPath).length === 1, "Changing currency started the same operation again");
    assert(submit.disabled, "Changing currency released the debt command before its bill settled");
    submit.click(); form.requestSubmit();
    assert(!calls.includes("/web/debts"), "A debt was sent before the selected original settled");
    release();
    await wait(() => field("bill_source_row_version").value === "2" && !field("bill_parse_key").value && !submit.disabled,
      "the original operation to settle");
    assert(field("amount_major").value === "66.00" && field("counterparty_label").value === "切换币种保留的对方",
      "The currency round trip lost manual fields");
    submit.click();
  }
  async function completeRestoredDraft(form, field, submit) {
    if (scenario.startsWith("currency-")) {
      await completeCurrencyRace(form, field, submit);
      return true;
    }
    if (window.__staleKeyDraft) {
      // Saved before the single adopt write: a source beside the capture key it already resolved.
      await wait(() => !field("bill_capture_key").value && field("bill_source_public_id").value === "source-1", "the stale key to clear");
      await wait(() => !submit.disabled, "submission to reopen for a known source");
      submit.click();
      return true;
    }
    if (window.__parseReplayDraft) {
      // Reopened with a parse attempt whose outcome never arrived: replayed once, not once per wake-up.
      if (scenario === "parse-replay-unknown") {
        await wait(() => form.querySelector("[data-debtbill-status]").textContent.includes("暂时无法确认识别结果"), "the unanswered replay");
        await pause(1500); // A queued recovery must not turn an unknown reply into an automatic retry.
        assert(field("bill_parse_key").value && field("bill_source_row_version").value === "1", "An unknown reply was replayed again without the person asking");
        const retry = form.querySelector("[data-debtbill-parse]");
        assert(!retry.hidden && !retry.disabled, "The retained attempt cannot be explicitly resumed");
        retry.click();
      }
      await wait(() => form.querySelector("[data-debtbill-status]").textContent.includes("已按原账单建议补全空白项"), "the replayed parse");
      await wait(() => !submit.disabled, "submission after the replayed parse");
      submit.click();
      return true;
    }
    if (!window.__legacyDraft) return false;
    assert(field("counterparty_label").value === "旧原稿里的对方" && field("amount_major").value === "88.00", "An older draft lost its inputs");
    assert(!form.querySelector("[data-debtbill]").hidden && !form.querySelector("[data-debtbill-picker]").hidden,
      "An older draft hid the bill entry");
    window.__debtBillResult = {completed: true};
    return true;
  }
  try {
    const form = document.querySelector("#debt-creation"), field = name => form.elements.namedItem(name);
    const who = field("counterparty_label"), status = form.querySelector("[data-debtbill-status]");
    const submit = document.querySelector("[data-debtcreation-submit]");
    await wait(() => !who.readOnly && !who.disabled, "an editable form");
    if (await completeRestoredDraft(form, field, submit)) return;
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
      if (filled && scenario === "revolving") {
        assert(field("amount_major").value === "1200.00" && field("debt_kind").value === "revolving" &&
          !field("installment_count").value && !field("installment_period_months").value &&
          status.textContent.includes("未填入期数"), "An installment suggestion overrode the chosen revolving kind");
      } else if (filled) {
        assert(field("amount_major").value === "1200.00" && field("installment_count").value === "12" &&
          field("installment_period_months").value === "1" && field("debt_kind").value === "installment", "Blanks were not completed");
      }
      await wait(() => !submit.disabled, "submission to reopen once the bill settled");
      submit.click();
    }
    if (stage === "reloaded") { await finish(true); return; }
    who.value = "我自己填的对方"; who.dispatchEvent(new Event("input", {bubbles: true}));
    if (scenario === "revolving") {
      field("debt_kind").value = "revolving"; field("debt_kind").dispatchEvent(new Event("change", {bubbles: true}));
    }
    if (scenario === "parse-failed") {
      const amount = field("amount_major"); amount.value = "66.00"; amount.dispatchEvent(new Event("input", {bubbles: true}));
    }
    const setItem = Storage.prototype.setItem;
    // "storage" refuses every write naming the source; "storage-release" only the write that names it
    // and releases the capture key, which is where a two-step adopt left the draft stuck.
    const refused = {storage: value => value.includes('"bill_source_public_id":"source-1"'),
      "storage-release": value => value.includes('"bill_source_public_id":"source-1"') && value.includes('"bill_capture_key":""')}[scenario];
    if (refused) {
      Storage.prototype.setItem = function (name, value) {
        if (refused(String(value))) throw Error("QuotaExceededError");
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
    } else if (scenario === "storage" || scenario === "storage-release") {
      await wait(() => status.textContent.includes("本机原稿未能记下它"), "the unretained source");
      assert(field("bill_source_public_id").value === "" && field("bill_capture_key").value, "The page shows more than the draft holds");
      await tryToSubmitEarly("the draft could not keep the source");
      Storage.prototype.setItem = setItem;
      sessionStorage.setItem(key, "reloaded"); location.reload();
    } else await finish(scenario !== "parse-failed");
  } catch (error) {
    window.__debtBillResult = {error: String(error && error.stack || error), stage};
  }
})();
