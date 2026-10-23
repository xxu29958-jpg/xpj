(async function () {
  "use strict";
  const saved = () => JSON.parse(sessionStorage.getItem("recognition-probe") || "null");
  const keep = value => sessionStorage.setItem("recognition-probe", JSON.stringify(value));
  const wait = async (read, description) => {
    const until = Date.now() + 8000;
    while (Date.now() < until) { const found = read(); if (found) return found; await new Promise(resolve => setTimeout(resolve, 25)); }
    throw Error("Timed out: " + description);
  };
  const fields = form => Object.fromEntries([...new FormData(form)].filter(([name]) => name !== "csrf_token")
    .map(([name, value]) => [name, name === "draft_scope" ? JSON.stringify(JSON.parse(value)) : value]));
  const input = (field, value) => { field.value = value; field.dispatchEvent(new Event("input", {bubbles: true})); };
  const familyFor = kind => ["image", "region"].includes(kind) ? "expenseocr" : "expensetext";
  async function openTask() {
    const kind = new URL(location.href).searchParams.get("recognition_probe");
    if (!kind) return;
    const form = await wait(() => document.querySelector("form[data-expensereview-draft-scope]"), "financial form");
    await wait(() => form.expenseReviewContinuity, "financial draft owner");
    await wait(() => !form.elements.merchant.readOnly, "financial lease");
    input(form.elements.merchant, "主核对未保存商家");
    keep({kind, phase: "open", financial: fields(form), requests: []});
    const suffix = familyFor(kind) === "expenseocr" ? "ocr/retry" : "recognize-text";
    document.querySelector('a[href*="/42/' + suffix + '"]').click();
  }
  async function prepareOriginal(form, state) {
    if (state.phase !== "open") return false;
    if (state.kind === "text") {
      input(form.elements.raw_text, "便利店\n合计 JPY 2850\n原粘贴文字");
      for (const modifier of ["ctrlKey", "metaKey"]) {
        const event = new KeyboardEvent("keydown", {key: "Enter", [modifier]: true, bubbles: true, cancelable: true});
        form.elements.raw_text.dispatchEvent(event);
        if (event.defaultPrevented) throw Error("Recognition text triggered the bill confirmation shortcut");
      }
    }
    if (state.kind === "region") {
      form.querySelector("[data-ocr-region] summary").click();
      const image = form.querySelector("[data-ocr-region-image]");
      await wait(() => image.complete && image.naturalWidth, "original image");
      form.querySelector('[data-ocr-region-zoom="2"]').click();
      const move = form.querySelector("[data-ocr-region-move]");
      move.click();
      if (!image.style.touchAction.includes("pan-y")) throw Error("Long source cannot be scrolled on touch");
      image.dispatchEvent(new PointerEvent("pointerdown", {bubbles: true, clientX: 1, clientY: 1}));
      image.dispatchEvent(new PointerEvent("pointerup", {bubbles: true, clientX: 60, clientY: 60}));
      if (form.elements.ocr_region.value) throw Error("Moving the source changed the crop");
      move.click();
      image.scrollIntoView({block: "center", behavior: "instant"});
      const viewport = image.parentElement.parentElement;
      viewport.scrollTo({left: image.getBoundingClientRect().width / 2 - 50, behavior: "instant"});
      const bounds = image.getBoundingClientRect();
      const visible = viewport.getBoundingClientRect();
      const endpoint = bounds.left + 110 * bounds.width / image.naturalWidth;
      if (endpoint < visible.left || endpoint > Math.min(visible.right, innerWidth)) throw Error("Crop gesture is outside the visible source");
      const dispatch = (name, x, y) => image.dispatchEvent(new PointerEvent(name, {bubbles: true, pointerId: 1,
        clientX: bounds.left + x * bounds.width / image.naturalWidth,
        clientY: bounds.top + y * bounds.height / image.naturalHeight}));
      dispatch("pointerdown", 60, 25); dispatch("pointermove", 110, 50); dispatch("pointerup", 110, 50);
      const selected = JSON.parse(form.elements.ocr_region.value);
      if (JSON.stringify(selected.box) !== "[60,25,110,50]") throw Error("Source crop coordinates changed: " + JSON.stringify({selected,
        before: bounds.toJSON(), after: image.getBoundingClientRect().toJSON()}));
    }
    state.original = fields(form); state.phase = "send"; keep(state);
    if (state.kind === "text") { location.reload(); return true; }
    return false;
  }
  try {
    let state = saved();
    if (!state) { await openTask(); return; }
    if (state.phase === "returned") {
      const form = await wait(() => document.querySelector("form[data-expensereview-draft-scope]"), "returned financial form");
      await wait(() => form.elements.merchant.value === "主核对未保存商家", "financial draft restore");
      const after = fields(form);
      const prefix = "ticketbox:" + familyFor(state.kind) + "-edit-draft:v1:";
      window.__expenseReviewResult = {...state,
        financial_retained: ["merchant", "idempotency_key", "expected_row_version", "draft_ref"].every(name => after[name] === state.financial[name]),
        recognition_removed: !Object.keys(localStorage).some(key => key.startsWith(prefix))};
      return;
    }
    const family = familyFor(state.kind);
    const form = await wait(() => document.querySelector("form[data-recognition-form]"), "recognition form");
    await wait(() => form.expenseReviewContinuity, "recognition draft owner");
    const submit = form.querySelector("[data-recognition-submit]");
    await wait(() => !submit.disabled, "recognition lease");
    if (state.kind === "storage") {
      const setItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (key.startsWith("ticketbox:expensetext-edit-draft:v1:")) throw new DOMException("fixture quota", "QuotaExceededError");
        return setItem.call(this, key, value);
      };
      input(form.elements.raw_text, "还没有保留的原文字");
      const leaving = new Event("beforeunload", {cancelable: true});
      window.dispatchEvent(leaving);
      window.__expenseReviewResult = {leaving_prevented: leaving.defaultPrevented,
        retained_in_page: form.elements.raw_text.value === "还没有保留的原文字",
        warning: form.querySelector('[role="status"]').textContent};
      return;
    }
    if (await prepareOriginal(form, state)) return;
    const restored = fields(form);
    if (!Object.keys(state.original).every(name => restored[name] === state.original[name])) throw Error("Original recognition changed after reload");
    state.restored = true; keep(state);
    const realFetch = window.fetch.bind(window);
    window.fetch = async (url, options) => {
      const isCommand = new URL(url, location.href).pathname === new URL(form.action).pathname && options?.method === "POST";
      if (isCommand) { state.requests.push(Object.fromEntries([...options.body].filter(([name]) => name !== "csrf_token"))); keep(state); }
      const response = await realFetch(url, options);
      if (isCommand && state.phase === "send" && response.ok) {
        await realFetch("/recognition-later-fact", {method: "POST"});
        state.phase = "lost"; keep(state); throw TypeError("fixture: accepted reply lost");
      }
      if (isCommand && response.ok) { state.phase = "returned"; keep(state); }
      return response;
    };
    if (state.phase === "send") {
      submit.click();
      await wait(() => saved().phase === "lost" && !submit.disabled, "unknown submission retained");
      state = saved(); state.phase = "replay"; keep(state); location.reload(); return;
    }
    if (state.phase === "replay") {
      if (form.dataset[family + "DraftPhase"] === "editing") throw Error("Unknown submission became editable");
      if (state.kind === "text" && !form.elements.raw_text.readOnly) throw Error("Original text became editable");
      submit.click();
    }
  } catch (error) { window.__expenseReviewResult = {error: String(error), state: saved(), href: location.href}; }
})();
