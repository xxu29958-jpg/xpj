/* Real review -> current fact -> original task/receipt -> original filtered queue. */
(async function () {
  "use strict";
  const stateKey = "expense-navigation-probe", prefix = "ticketbox:expensereview-edit-draft:v1:";
  const state = JSON.parse(sessionStorage.getItem(stateKey) || "null") || {
    operation: new URL(location.href).searchParams.get("probe"), stage: "edit", requests: [], first_receipt: false,
  };
  const save = () => sessionStorage.setItem(stateKey, JSON.stringify(state));
  const assert = (condition, message) => { if (!condition) throw Error(message); };
  const wait = async predicate => {
    for (let n = 0; n < 200; n += 1) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw Error("navigation did not reach " + state.stage);
  };
  const go = (link, stage) => { assert(link, "missing return link at " + state.stage); state.stage = stage; save(); link.click(); };
  const links = text => [...document.querySelectorAll("a")].find(link => link.textContent.includes(text));
  const originalFetch = window.fetch;
  window.fetch = async (url, options) => {
    const path = new URL(url, location.href).pathname;
    if (options?.method !== "POST" || !/\/expenses\/42\/(save|confirm)$/.test(path)) return originalFetch(url, options);
    state.requests.push({path, fields: [...options.body].filter(([name]) => name !== "csrf_token")}); save();
    if (state.operation === "pending-current") {
      state.stage = "unknown"; save(); throw Error("request did not reach server");
    }
    const response = await originalFetch(url, options);
    if (state.stage === "edit") {
      assert(response.ok, "original command not accepted");
      assert((await originalFetch("/probe-later-fact", {method: "POST"})).ok, "later fact not prepared");
      state.stage = "unknown"; save();
      throw Error("accepted reply lost");
    }
    return response;
  };
  try {
    if (state.stage === "list") {
      const url = new URL(location.href);
      state.returned_to_filter = url.pathname === "/web/pending" && url.searchParams.get("filter") === "ready";
      window.__expenseReviewResult = state; return;
    }
    if (state.stage === "current" || state.stage === "receipt-current" || (state.stage === "replay" && state.operation === "save")) {
      if (state.operation === "pending-current") {
        await wait(() => document.querySelector("[data-review-current-record], [data-expensereview-draft-phase='submitted']"));
        assert(document.querySelector('[name="merchant"]').value === "首次便利店", "current pending record was replaced by the original draft");
        assert(!document.querySelector("[data-expensereview-draft-scope]") && !document.querySelector('button[type="submit"]:not(:disabled)'), "current inspection opened another command");
      } else assert(document.querySelector(".fact-hero")?.textContent.includes("99.00") && document.querySelector("h1")?.textContent.includes("后来人工更正"), "current fact not shown");
      state.current_fact = true;
      if (state.stage === "current") {
        const link = links("返回原核对任务");
        assert(link && new URL(link.href).hash === "#expensereview-edit-" + state.ref, "current fact lost the original review return");
        if (state.operation !== "pending-current") assert(new URL(link.href).searchParams.get("return_filter") === "ready", "current fact replaced the original filter");
        go(link, "returned");
      } else if (state.stage === "receipt-current") go(links("返回确认回执"), "receipt-returned");
      else {
        state.original_removed = !localStorage.getItem(prefix + state.ref);
        assert(!document.querySelector("[data-expense-confirmation]"), "saved draft became a financial receipt");
        go(links("返回待确认"), "list");
      }
      return;
    }
    const receipt = document.querySelector("[data-expense-confirmation]");
    if (receipt) {
      assert(state.operation === "confirm" && (state.stage === "replay" || state.stage === "receipt-returned"), "unexpected receipt at " + state.stage + " for " + state.operation);
      assert(receipt.textContent.includes("128.60") && receipt.textContent.includes("原任务商家") && !receipt.textContent.includes("后来人工更正"), "first result replaced by current fact");
      state.first_receipt = true; state.original_removed = !localStorage.getItem(prefix + state.ref);
      go(state.stage === "replay" ? links("查看这笔账单") : receipt.querySelector("[data-confirmation-finish]"), state.stage === "replay" ? "receipt-current" : "list");
      return;
    }
    if (location.pathname === "/web/pending") {
      await wait(() => window.TicketboxWeb?.drawerApi);
      document.querySelector('.exp-row[data-expense-id="42"] .exp-row-detail').click();
    }
    await wait(() => document.querySelector("form[data-expensereview-draft-phase] [data-expensereview-submit]:not(:disabled)"));
    const form = document.querySelector("form[data-expensereview-plan-id]"), field = name => form.elements.namedItem(name);
    if (state.stage === "edit") {
      field("merchant").value = "原任务商家"; field("merchant").dispatchEvent(new Event("input", {bubbles: true}));
      state.key = field("idempotency_key").value; state.ref = field("draft_ref").value; save();
      const primary = state.operation === "save" ? [...form.querySelectorAll("button")].find(button => button.textContent === "保存草稿") : form.querySelector("[data-expensereview-submit]");
      form.requestSubmit(primary);
      await wait(() => state.stage === "unknown" && form.querySelector("[data-expensereview-draft-status]").textContent.includes("暂未收到"));
      state.original = JSON.parse(localStorage.getItem(prefix + state.ref));
      if (state.operation === "confirm" && location.pathname.endsWith("/edit")) {
        // Revisit the same object from another list context. The retained task,
        // not the fresh server page, owns its original return destination.
        state.stage = "reentered"; save();
        const next = new URL(location.href); next.searchParams.set("return_filter", "all"); location.assign(next); return;
      }
      go(form.querySelector("[data-expensereview-links] a"), "current");
    } else if (state.stage === "reentered") {
      go(form.querySelector("[data-expensereview-links] a"), "current");
    } else if (state.stage === "returned") {
      state.original_preserved = field("merchant").value === "原任务商家" && field("idempotency_key").value === state.key && field("expected_row_version").value === "4" &&
        JSON.stringify(JSON.parse(localStorage.getItem(prefix + state.ref)).values) === JSON.stringify(state.original.values);
      assert(state.original_preserved && form.dataset.expensereviewDraftPhase === "submitted", "original submission changed during fact inspection");
      if (state.operation === "pending-current") { window.__expenseReviewResult = state; return; }
      state.stage = "replay"; save(); form.requestSubmit(form.querySelector("[data-expensereview-submit]"));
    }
  } catch (error) { window.__expenseReviewResult = {...state, error: String(error)}; }
})();
