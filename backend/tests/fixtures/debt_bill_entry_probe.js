(async function () {
  "use strict";
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async (predicate, label) => {
    for (let attempt = 0; attempt < 240; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("Timed out waiting for " + label);
  };
  try {
    const form = document.querySelector("#debt-creation"), field = name => form.elements.namedItem(name);
    const who = field("counterparty_label"), status = form.querySelector("[data-debtbill-status]");
    await wait(() => !who.readOnly && !who.disabled && !form.querySelector("[data-debtbill-file]").disabled, "an editable form");
    const draft = () => JSON.parse(localStorage.getItem("ticketbox:debtcreation-create-draft:v1:" + field("idempotency_key").value));
    if (window.__legacyDraft) {
      assert(who.value === "旧原稿里的对方" && field("amount_major").value === "88.00", "An older draft lost its inputs");
      assert(!form.querySelector("[data-debtbill]").hidden && !form.querySelector("[data-debtbill-picker]").hidden,
        "An older draft hid the bill entry");
      window.__debtBillResult = {completed: true};
      return;
    }
    // The person's own input stays; the suggestion only completes blanks.
    who.value = "我自己填的对方"; who.dispatchEvent(new Event("input", {bubbles: true}));
    const canvas = document.createElement("canvas"); canvas.width = 120; canvas.height = 80;
    canvas.getContext("2d").fillRect(10, 10, 40, 20);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    const files = new DataTransfer(); files.items.add(new File([blob], "借条.png", {type: "image/png"}));
    const input = form.querySelector("[data-debtbill-file]");
    input.files = files.files; input.dispatchEvent(new Event("change", {bubbles: true}));
    await wait(() => status.textContent.includes("已按原账单建议补全空白项"), "the parse suggestion");
    assert(who.value === "我自己填的对方", "The suggestion overwrote the person's counterparty");
    assert(field("amount_major").value === "1200.00" && field("installment_count").value === "12" &&
      field("installment_period_months").value === "1" && field("debt_kind").value === "installment", "Blank fields were not completed");
    assert(field("bill_source_public_id").value === "source-1" && field("bill_source_row_version").value === "2",
      "The parsed source version was not kept for the debt command");
    const saved = draft().values;
    assert(saved.bill_source_public_id === "source-1" && saved.bill_capture_key === "" && saved.bill_parse_key === "",
      "The draft does not hold the finished source");
    assert(form.querySelector("[data-debtbill-picker]").hidden && !form.querySelector("[data-debtbill-source]").hidden &&
      form.querySelector("[data-debtbill-file-name]").textContent === "借条.png", "The retained bill is not shown");
    window.__debtBillPending = true;
    document.querySelector("[data-debtcreation-submit]").click();
  } catch (error) {
    window.__debtBillResult = {error: String(error && error.stack || error)};
  }
})();
