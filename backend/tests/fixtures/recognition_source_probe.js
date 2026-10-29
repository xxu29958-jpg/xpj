/* Actual original snapshot and review form; geometry checks do not create labels. */
(async function () {
  "use strict";
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async predicate => {
    for (let n = 0; n < 250; n++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 25)); }
    throw Error("Source review timed out");
  };
  async function verifySourceGeometry(dialog, status, stale) {
    if (stale) {
      assert(status.textContent.includes("无法核对") && dialog.querySelector("svg").children.length === 0, "Stale hash displayed a location");
      return;
    }
    assert(dialog.querySelector("polygon").getAttribute("points").startsWith("10,80"), "Equal amount linked to the wrong original block");
    assert(dialog.querySelector("img").naturalWidth === 400 && dialog.querySelector("img").naturalHeight === 800, "EXIF geometry changed");
    const oldPoints = dialog.querySelector("polygon").getAttribute("points");
    dialog.querySelector('[data-source-zoom="2"]').click();
    assert(dialog.querySelector("polygon").getAttribute("points") === oldPoints, "Zoom changed original coordinates");
    const next = dialog.querySelector("[data-source-next]");
    if (!next.disabled) {
      next.click(); await wait(() => !status.textContent.includes("正在"));
      assert(dialog.querySelector("polygon").getAttribute("points") !== oldPoints, "Next source kept the previous location");
    }
    assert(dialog.scrollWidth <= dialog.clientWidth + 2, "Source review overflows the narrow screen");
    const picture = dialog.querySelector("img").getBoundingClientRect(), overlay = dialog.querySelector("svg").getBoundingClientRect();
    assert(Math.abs(picture.left - overlay.left) < 1 && Math.abs(picture.top - overlay.top) < 1 &&
      Math.abs(picture.height - overlay.height) < 1, "Source overlay does not align with the visible original");
  }
  const key = "recognition-source-probe";
  if (sessionStorage.getItem(key) === "submitted") { window.__expenseReviewResult = {completed: true}; return; }
  try {
    if (document.readyState === "loading") await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once: true}));
    const drawer = location.pathname === "/web/pending", stale = new URL(location.href).searchParams.has("stale");
    if (drawer) {
      document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
      await wait(() => document.querySelector("#drawer [data-drawer-form]"));
    }
    const form = document.querySelector(drawer ? "#drawer [data-drawer-form]" : "form.edit-form");
    await wait(() => form.dataset.expensereviewDraftPhase && !form.querySelector("[data-expensereview-submit]").disabled);
    const amount = form.elements.namedItem("amount_yuan");
    amount.value = "22.00"; amount.dispatchEvent(new Event("input", {bubbles: true}));
    const buttons = [...form.querySelectorAll("[data-recognition-source]")];
    const paid = buttons.find(button => JSON.parse(button.dataset.recognitionSource).role === "payment");
    assert(paid, "Payment has no source action");
    paid.closest("details").open = true; paid.click();
    const dialog = form.querySelector(".recognition-source-dialog"), status = dialog.querySelector("[data-source-status]");
    await wait(() => !status.textContent.includes("正在"));
    await verifySourceGeometry(dialog, status, stale);
    const bounds = dialog.getBoundingClientRect();
    assert(bounds.top >= 0 && bounds.bottom <= innerHeight && getComputedStyle(dialog).backgroundColor !== "rgba(0, 0, 0, 0)",
      "Source dialog is not a readable surface within the viewport");
    window.__sourcePreviewReady = true;
    await wait(() => window.__sourcePreviewCaptured);
    if (drawer) {
      window.__sourceEscapeReady = true;
      await wait(() => window.__sourceEscapeDispatched);
      assert(!dialog.open && form.isConnected, "Escape closed the expense drawer instead of the source review");
    } else dialog.querySelector("[data-source-close]").click();
    assert(amount.value === "22.00" && !form.elements.namedItem("recognition_field_choices")?.value, "Viewing source changed draft or supplied labels");
    const originalFetch = window.fetch;
    window.fetch = async (url, options) => {
      const response = await originalFetch(url, options);
      if (options?.method === "POST") window.__expenseReviewResult = {completed: response.ok, status: response.status,
        refusal: response.ok ? null : await response.clone().text()};
      return response;
    };
    sessionStorage.setItem(key, "submitted");
    form.requestSubmit(form.querySelector("[data-expensereview-submit]"));
  } catch (error) { window.__expenseReviewResult = {error: String(error)}; }
})();
