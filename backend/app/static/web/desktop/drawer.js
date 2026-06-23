/* Pending expense edit drawer.
 *
 * 批10: the drawer is the /web review pipeline. On top of opening the edit
 * fragment, the drawer form's save / 确认 / 标为非重复 submit are upgraded to
 * fetch-mutations (progressive enhancement):
 *   - 确认 success → remove the row, decrement the filter count, auto-open the
 *     next pending row's drawer (= 确认并下一笔).
 *   - save / 标为非重复 success → re-fetch the row fragment (fresh OCC token /
 *     cleared duplicate flag) so the open drawer stays usable.
 *   - any failure → swap the drawer fragment carrying the inline error back in,
 *     so the reviewer never loses their place.
 *   - fetch rejected (offline) → fall through to a native full-page submit
 *     (the hidden return_to=pending field still lands a save back on the queue).
 *
 * 删除草稿 keeps its data-confirm dialog and is intentionally left on the native
 * full-page path: that preserves the ADR-0038 5s 撤销 banner (which the fetch
 * path would silently drop) and avoids forking confirm-modal's dialog.
 */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  // Action kind derived from the POST target so success handling can branch
  // without coupling to exact element ids.
  function actionKind(url) {
    if (/\/confirm$/.test(url)) return "confirm";
    if (/\/reject$/.test(url)) return "reject";
    if (/\/duplicates\/\d+\/keep$/.test(url)) return "keep";
    return "save";
  }

  app.initDrawer = function initDrawer() {
    const drawer = document.getElementById("drawer");
    const scrim = document.getElementById("drawer-scrim");
    if (!drawer || !scrim) return;

    let currentRow = null;
    let restoreFocusTo = null;

    function close() {
      drawer.classList.remove("on");
      scrim.classList.remove("on");
      drawer.innerHTML = "";
      currentRow = null;
      restoreFocus();
    }

    function rememberFocus(row) {
      if (drawer.classList.contains("on")) return;
      const active = document.activeElement;
      restoreFocusTo =
        active && active !== document.body && document.contains(active)
          ? active
          : row;
    }

    function restoreFocus() {
      const target = restoreFocusTo;
      restoreFocusTo = null;
      if (target && document.contains(target) && typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
    }

    function focusDrawer() {
      const target = drawer.querySelector(
        "[data-drawer-close], input:not([type=hidden]):not([disabled]), " +
        "textarea:not([disabled]), select:not([disabled]), button:not([disabled]), a[href]"
      ) || drawer;
      if (target && typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
    }

    function bindFragment() {
      if (typeof app.initReceiptSkeletons === "function") app.initReceiptSkeletons(drawer);
      drawer.querySelectorAll("[data-drawer-close]").forEach(function (b) {
        b.addEventListener("click", close);
      });
      bindDrawerForm();
    }

    // Fetch the edit fragment for a row and swap it into the open drawer. On a
    // fetch error fall back to the row's full-page edit link (unchanged
    // behaviour for the open action).
    function openRow(row) {
      if (!row) return;
      const url = row.getAttribute("data-fragment-url");
      if (!url) return;
      rememberFocus(row);
      currentRow = row;
      fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
        .then(function (res) { return res.text(); })
        .then(function (html) {
          drawer.innerHTML = html;
          drawer.classList.add("on");
          scrim.classList.add("on");
          markSelected(row);
          bindFragment();
          focusDrawer();
        })
        .catch(function () {
          window.location.href = row.getAttribute("href");
        });
    }

    // Re-fetch the current row's fragment in place (after save / keep success)
    // so the form picks up a fresh OCC token and cleared flags.
    function refetchCurrent() {
      if (!currentRow) { close(); return; }
      const url = currentRow.getAttribute("data-fragment-url");
      fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
        .then(function (res) { return res.text(); })
        .then(function (html) { drawer.innerHTML = html; bindFragment(); focusDrawer(); })
        .catch(function () { /* leave the drawer as-is; the row is unchanged */ });
    }

    function markSelected(row) {
      document.querySelectorAll('.exp-row[aria-selected="true"]').forEach(function (r) {
        if (r !== row) r.setAttribute("aria-selected", "false");
      });
      if (row) row.setAttribute("aria-selected", "true");
    }

    // 批10: confirm/忽略 removes the row from the table; decrement the visible
    // pending counts (active filter + 全部) — short-lived drift on the other
    // filters is acceptable and self-heals on the next page load.
    function removeCurrentRow() {
      if (!currentRow) return null;
      const next = nextRow(currentRow);
      if (currentRow.parentNode) currentRow.parentNode.removeChild(currentRow);
      decrementCounts();
      currentRow = null;
      return next;
    }

    function nextRow(row) {
      let el = row.nextElementSibling;
      while (el && !el.classList.contains("exp-row")) el = el.nextElementSibling;
      if (el) return el;
      // No following row: fall back to the previous one so the reviewer keeps
      // moving instead of dead-ending.
      el = row.previousElementSibling;
      while (el && !el.classList.contains("exp-row")) el = el.previousElementSibling;
      return el;
    }

    function decrementCounts() {
      const seen = [];
      const active = document.querySelector(".filter-tab.is-active .count");
      const total = document.querySelector(".filter-tab .count"); // 全部 is first
      [active, total].forEach(function (node) {
        if (!node || seen.indexOf(node) !== -1) return;
        seen.push(node);
        const n = parseInt(node.textContent, 10);
        if (!isNaN(n) && n > 0) node.textContent = String(n - 1);
      });
    }

    function advanceAfterRemoval(next) {
      if (next) {
        openRow(next);
      } else {
        close();
      }
    }

    // --- drawer form fetch-mutation ---------------------------------------

    function bindDrawerForm() {
      const form = drawer.querySelector("[data-drawer-form]");
      if (!form || form.getAttribute("data-fetch-bound") === "1") return;
      form.setAttribute("data-fetch-bound", "1");
      form.addEventListener("submit", function (e) {
        // Offline-fallback re-entry guard: requestSubmit() below re-fires this
        // listener; let the native submit through instead of looping.
        if (form.getAttribute("data-native-fallback") === "1") return;
        const submitter = e.submitter || document.activeElement;
        // 删除草稿 (data-confirm) stays on the native path: confirm-modal owns
        // the dialog and the full-page submit preserves the 撤销 banner.
        if (submitter && submitter.closest && submitter.closest("[data-confirm]")) return;
        const actionUrl =
          (submitter && submitter.getAttribute && submitter.getAttribute("formaction")) ||
          form.getAttribute("action");
        if (!actionUrl) return;
        e.preventDefault();
        submitDrawer(form, actionUrl);
      });
    }

    function submitDrawer(form, actionUrl) {
      const kind = actionKind(actionUrl);
      const body = new FormData(form);
      body.append("fragment", "1"); // server returns a 200 marker / error fragment
      setDrawerBusy(form, true);
      // window.fetch is wrapped by csrf.js → adds the X-CSRF-Token header for
      // same-origin requests; FormData also carries the csrf_token field when
      // present. Same-origin source + token satisfies the /web CSRF gate.
      fetch(actionUrl, { method: "POST", credentials: "same-origin", body: body })
        .then(function (res) {
          if (res.ok) {
            onMutationOk(kind);
            return undefined;
          }
          // Error: server returns the drawer fragment with the inline error.
          return res.text().then(function (html) {
            drawer.innerHTML = html;
            bindFragment();
            focusDrawer();
          });
        })
        .catch(function () {
          // Offline / network failure → native full-page submit. No fragment
          // field is on the form itself, so the server redirects normally;
          // return_to=pending keeps a save on the queue. requestSubmit (not
          // .submit()) on purpose: it fires the real submit event so csrf.js's
          // capture listener injects the csrf_token field — the programmatic
          // .submit() skips the event and the native POST would 403.
          form.setAttribute("action", actionUrl);
          form.setAttribute("data-native-fallback", "1");
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            HTMLFormElement.prototype.submit.call(form);
          }
        });
    }

    function onMutationOk(kind) {
      if (kind === "confirm" || kind === "reject") {
        advanceAfterRemoval(removeCurrentRow());
      } else {
        // save / keep: the row stays; refresh the drawer for a fresh token.
        refetchCurrent();
      }
    }

    function setDrawerBusy(form, busy) {
      form.querySelectorAll("button[type=submit]").forEach(function (b) {
        b.disabled = busy;
      });
    }

    // --- wiring ------------------------------------------------------------

    scrim.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && drawer.classList.contains("on")) close();
    });

    document.querySelectorAll(".exp-row[data-fragment-url]").forEach(function (row) {
      row.addEventListener("click", function (e) {
        // 点 checkbox / 表单元素时不打开抽屉
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "button") return;
        if (e.target.closest && e.target.closest("[data-stop=true]")) return;
        e.preventDefault();
        openRow(row);
      });
    });

    // Exposed for review-hotkeys.js (J/K navigation + Ctrl+Enter confirm).
    app.drawerApi = {
      open: openRow,
      close: close,
      isOpen: function () { return drawer.classList.contains("on"); },
      currentRow: function () { return currentRow; },
      submitConfirm: function () {
        const form = drawer.querySelector("[data-drawer-form]");
        if (!form) return false;
        const btn = form.querySelector('button[formaction$="/confirm"]');
        if (!btn || btn.disabled) return false;
        btn.click(); // routes through the form submit → fetch pipeline above
        return true;
      }
    };
  };
})(window, document);
