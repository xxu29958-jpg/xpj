(async function () {
  let stage = "loading";
  const assert = (value, message) => { if (!value) throw Error(message); };
  async function wait(condition) {
    const deadline = performance.now() + 5000;
    while (!condition()) {
      if (performance.now() >= deadline) throw Error("Original selection stalled: " + stage);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  }
  try {
    const form = document.querySelector('form[action*="/original/attach?"]');
    const button = form.querySelector('[type="submit"]');
    const file = form.elements.namedItem("file");
    const image = form.querySelector("[data-attachment-selected-image]");
    const review = form.querySelector("[data-attachment-selected-check]");
    const open = form.querySelector("[data-attachment-selected-open]");
    await wait(() => form.dataset.attachmentPhase === "editing" && !file.disabled);
    assert(image && review, "The actual original page must show and confirm its selected file");
    const api = window.TicketboxAttachmentDrafts;
    const previous = JSON.parse(sessionStorage.getItem("original-selection") || "null");
    function choose(bytes, name) {
      const transfer = new DataTransfer();
      transfer.items.add(new File([bytes], name, {type: "image/jpeg"}));
      file.files = transfer.files;
      file.dispatchEvent(new Event("change", {bubbles: true}));
    }
    if (!previous) {
      stage = "invalid image";
      choose("not a decodable image", "broken.jpg");
      await wait(() => form.querySelector("[data-attachment-selection-status]").textContent.includes("无法打开") && !file.disabled);
      assert(button.disabled && image.hidden, "An unreadable selection must not be admitted");
      stage = "valid selection";
      const bytes = Uint8Array.from(atob(window.__originalSample), c => c.charCodeAt(0));
      choose(bytes, "selected-original.jpg");
      await wait(() => (window.__externalPreview ? !open.hidden : !image.hidden) && !file.disabled);
      if (window.__externalPreview) {
        assert(review.disabled && image.hidden, "Unsupported browser format requires explicit external review");
        open.click();
      } else { assert(image.complete && image.naturalWidth > 0, "Display the selected image"); }
      assert(button.disabled, "Selected original still needs confirmation");
      const ref = location.hash.slice("#attachment-".length);
      const record = api.store.read(ref);
      assert(record.phase === "editing", "Preview must leave the command unsubmitted");
      review.click();
      assert(!button.disabled, "A displayed and explicitly confirmed image can be submitted");
      sessionStorage.setItem("original-selection", JSON.stringify({ref, values: record.values}));
      location.reload();
      return;
    }
    stage = "restored selection";
    await wait(() => (window.__externalPreview ? !open.hidden : !image.hidden) && !file.disabled);
    assert(!review.checked && button.disabled, "A reopened draft must be reviewed again");
    assert(JSON.stringify(api.store.read(previous.ref).values) === JSON.stringify(previous.values), "Restore preserves file, identity, key and OCC");
    const shown = await (await fetch(window.__externalPreview ? open.href : image.src)).arrayBuffer();
    const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", shown))].map(b => b.toString(16).padStart(2, "0")).join("");
    assert(digest === previous.values.file_sha256, "Preview must display the retained original bytes");
    const nativeFetch = window.fetch.bind(window);
    let accepted = null;
    window.fetch = async (url, options) => {
      const response = await nativeFetch(url, options);
      if (options?.method === "POST") {
        assert(response.ok, "Original command must be accepted before losing its reply");
        accepted = await response.json();
        throw new TypeError("Controlled lost response");
      }
      return response;
    };
    stage = "explicit submission";
    form.requestSubmit();
    assert(api.store.read(previous.ref).phase === "editing", "Unconfirmed submit must not publish");
    if (window.__externalPreview) open.click();
    review.click();
    form.requestSubmit();
    await wait(() => accepted && !button.disabled);
    assert(review.checked && review.disabled && file.disabled, "Unknown result keeps the confirmed file fixed");
    assert(api.store.read(previous.ref).phase === "submitted", "Lost reply must retain the original command");
    window.__expenseReviewResult = {decoded: true, restored: true, explicit_confirmation: true, fixed_after_reply_loss: true};
  } catch (error) { window.__expenseReviewResult = {error: String(error), stage}; }
})();
