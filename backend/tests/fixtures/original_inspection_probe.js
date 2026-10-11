(async function () {
  let stage = sessionStorage.getItem("inspection-stage") || "first-page";
  const assert = (value, message) => { if (!value) throw Error(message); };
  const wait = async condition => {
    const deadline = performance.now() + 5000;
    while (!condition()) {
      if (performance.now() >= deadline) throw Error("Inspection stalled: " + stage);
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  };
  const save = value => sessionStorage.setItem("inspection-stage", value);
  const returnLink = () => [...document.querySelectorAll("a")].find(link => {
    const url = new URL(link.href);
    return url.pathname === "/web/originals" && url.searchParams.get("after") === "25";
  });
  try {
    await wait(() => document.readyState === "complete");
    if (stage === "first-page") {
      await wait(() => document.querySelector("[data-original-scan]"));
      const scan = document.querySelector("[data-original-scan]");
      const bounds = scan.getBoundingClientRect();
      assert(bounds.top >= 0 && bounds.bottom <= innerHeight, "The current-page check must be reachable without scrolling past 25 bills");
      assert(document.querySelectorAll("[data-original-row]").length === 25, "Inspection must retain its bounded page");
      save("inspect-second-page");
      returnLink().click();
      return;
    }
    if (stage === "inspect-second-page") {
      const read = window.fetch.bind(window);
      window.fetch = (url, options) => String(url).includes("/44/original/health") ?
        Promise.resolve(new Response("Unavailable", {status: 503})) : read(url, options);
      const scan = document.querySelector("[data-original-scan]");
      scan.click();
      await wait(() => !scan.disabled && document.querySelector('[data-expense-id="43"]').dataset.originalState);
      assert(document.querySelector('[data-expense-id="43"]').dataset.originalState === "missing", "The actual missing file needs replenishment");
      assert(document.querySelector('[data-expense-id="44"]').dataset.originalState === "unreadable", "One failed read must remain actionable");
      assert(document.querySelector('[data-expense-id="42"]').dataset.originalState === "verified", "A partial failure must preserve the other observations");
      save("replenish");
      document.querySelector("[data-original-next]").click();
      return;
    }
    if (stage === "replenish") {
      assert(returnLink(), "The original task must offer a return to the same inspection page");
      const form = document.querySelector('form[action*="/original/replenish?"]');
      const file = form.elements.namedItem("file");
      const review = form.querySelector("[data-attachment-selected-check]");
      await wait(() => form.dataset.attachmentPhase === "editing" && !file.disabled);
      const source = Uint8Array.from(atob(window.__originalSample), value => value.charCodeAt(0));
      const transfer = new DataTransfer();
      transfer.items.add(new File([source], "retained-original.jpg", {type: "image/jpeg"}));
      file.files = transfer.files;
      file.dispatchEvent(new Event("change", {bubbles: true}));
      await wait(() => !review.disabled && !form.querySelector("[data-attachment-selected-image]").hidden);
      review.click();
      assert(!form.querySelector('[type="submit"]').disabled, "A displayed and confirmed original can be replenished");
      save("accepted");
      form.requestSubmit();
      return;
    }
    if (stage === "accepted") {
      assert(returnLink(), "The accepted command must keep its inspection origin");
      save("returned");
      returnLink().click();
      return;
    }
    if (stage === "returned") {
      assert(new URL(location.href).searchParams.get("after") === "25", "Return must keep the original page cursor");
      await wait(() => !document.querySelector("[data-original-scan]").disabled &&
        document.querySelector('[data-expense-id="43"]').dataset.originalState === "verified");
      assert(document.querySelector('[data-expense-id="44"]').dataset.originalState === "none", "Return must retry the interrupted observation without calling a manual bill missing");
      assert(document.querySelectorAll("[data-original-row]").length === 3, "Return must not expand the checked scope");
      assert(document.querySelector("[data-original-next]").hidden, "A repaired original must leave the needs-attention action");
      window.__expenseReviewResult = {page_retained: true, fresh_result: true, partial_read_failure: true};
    }
  } catch (error) { window.__expenseReviewResult = {error: String(error), stage}; }
})();
