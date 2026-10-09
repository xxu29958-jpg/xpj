(async function () {
  const state = JSON.parse(sessionStorage.getItem("manual-original-journey") || "null") || {stage: "new"};
  const assert = (value, message) => { if (!value) throw Error(message); };
  const save = stage => { state.stage = stage; sessionStorage.setItem("manual-original-journey", JSON.stringify(state)); };
  async function wait(condition) {
    const until = performance.now() + 5000;
    while (!condition()) {
      if (performance.now() >= until) throw Error("Manual original stalled: " + state.stage);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  }
  // A real IndexedDB transaction refusal must leave both the bill draft and its file recoverable.
  if (state.stage === "lost-create" && location.pathname.endsWith("/result")) {
    const put = IDBObjectStore.prototype.put;
    IDBObjectStore.prototype.put = function (value, key) {
      if (String(key).startsWith("ticketbox:attachment-draft:")) throw Error("controlled disk failure");
      return put.call(this, value, key);
    };
  }
  async function continueFromReceipt() {
    await wait(() => window.TicketboxManualDrafts && !document.querySelector("[data-manual-draft-ack-status]").hidden);
    if (state.stage === "lost-create") {
      assert(window.TicketboxManualDrafts.read(state.ref).values.original_file === state.meta, "Failed handoff discarded the original");
      assert(!window.TicketboxAttachmentDrafts.store.read(state.ref), "Failed handoff published a task without its file");
      save("transfer-retry");
      document.querySelector("[data-manual-original-continue]").click();
      return;
    }
    await wait(() => !document.querySelector("[data-manual-original-continue]").hidden);
    assert(!window.TicketboxManualDrafts.read(state.ref), "Only the receipt and durable transfer may collect the manual draft");
    const task = window.TicketboxAttachmentDrafts.store.read(state.ref);
    assert(task.phase === "editing" && task.values.file_sha256 === JSON.parse(state.meta).file_sha256, "Transfer changed the original file");
    assert(new URL(task.values.action).searchParams.get("expected_row_version") === "4", "Attachment must keep the first receipt basis");
    if (state.stage === "transfer-retry") {
      save("transferred");
      location.reload();
      return;
    }
    state.transfer_retried = true;
    save("original");
    document.querySelector("[data-manual-original-continue]").click();
    return;
  }
  try {
    if (location.pathname === "/web/expenses/new") {
      const form = document.querySelector("[data-manual-draft-scope]");
      await wait(() => ["editing", "submitted"].includes(form.dataset.manualDraftState));
      const file = form.querySelector("[data-manual-original-file]");
      assert(file, "Manual creation has no optional original consumer");
      const drafts = window.TicketboxManualDrafts;
      const fill = (name, value) => {
        form.elements.namedItem(name).value = value;
        form.elements.namedItem(name).dispatchEvent(new Event("input", {bubbles: true}));
      };
      if (state.stage === "new") {
        state.ref = form.elements.namedItem("client_ref").value;
        fill("amount_major", "wrong");
        fill("merchant", "原稿商家");
        const transfer = new DataTransfer();
        transfer.items.add(new File([Uint8Array.from(atob(window.__originalSample), c => c.charCodeAt(0))], "manual-original.jpg", {type: "image/jpeg"}));
        file.files = transfer.files;
        file.dispatchEvent(new Event("change", {bubbles: true}));
        await wait(() => drafts.read(state.ref)?.values.original_file && !form.querySelector("[data-manual-submit]").disabled);
        state.meta = drafts.read(state.ref).values.original_file;
        save("rejected");
        form.requestSubmit();
        return;
      }
      const record = drafts.read(state.ref);
      assert(record.values.original_file === state.meta, "Native rejection/reload changed the original selection");
      assert(form.elements.namedItem("client_ref").value === state.ref, "Manual ref changed");
      await wait(() => !form.querySelector("[data-attachment-selected-image]").hidden);
      if (state.stage === "rejected") {
        assert(form.dataset.manualDraftResult === "rejected" && form.elements.namedItem("amount_major").value === "wrong", "Expected the actual native validation refusal");
        fill("amount_major", "12.34");
        state.rejected_preserved = true;
        save("restored");
        location.reload();
      } else if (state.stage === "restored") {
        form.addEventListener("submit", async event => {
          event.preventDefault();
          const response = await fetch(form.action, {method: "POST", body: new FormData(form), redirect: "manual"});
          assert(response.type === "opaqueredirect", "The native creation must succeed before dropping its reply");
          save("lost-create");
          location.reload();
        }, {once: true});
        form.requestSubmit();
      } else {
        assert(record.phase === "submitted" && file.disabled, "Unknown creation result must fix the original selection");
        document.querySelector("[data-manual-result]").click();
      }
      return;
    }
    if (location.pathname.endsWith("/result")) { await continueFromReceipt(); return; }
    const form = document.querySelector('form[action*="/original/attach?"]');
    await wait(() => form.dataset.attachmentPhase === "editing" && !form.querySelector("[data-attachment-selected-image]").hidden);
    const check = form.querySelector("[data-attachment-selected-check]");
    const button = form.querySelector('[type="submit"]');
    assert(!check.checked && button.disabled, "Transferred file must still require explicit confirmation");
    const nativeFetch = window.fetch.bind(window);
    let receipt;
    window.fetch = async (url, options) => {
      const response = await nativeFetch(url, options);
      if (options?.method === "POST") { receipt = await response.json(); throw new TypeError("controlled lost original reply"); }
      return response;
    };
    check.click();
    form.requestSubmit();
    await wait(() => receipt && !button.disabled);
    assert(receipt.receipt.operation === "attach_original", "The real original command was not accepted");
    assert(window.TicketboxAttachmentDrafts.store.read(state.ref).phase === "submitted", "Unknown original reply lost its task");
    window.__expenseReviewResult = {...state, explicit_original_confirmation: true};
  } catch (error) { window.__expenseReviewResult = {error: String(error), stage: state.stage}; }
})();
