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

  function responsePath(response) {
    try {
      return new URL(response.url || "", window.location.href).pathname;
    } catch (_error) {
      return "";
    }
  }

  function isSessionResponse(response) {
    return responsePath(response).indexOf("/web/auth/") === 0;
  }

  function sessionLoginUrl(response) {
    try {
      const target = new URL(response.url || "", window.location.href);
      if (target.origin === window.location.origin) return target.href;
    } catch (_error) {
      // Fall through to the fixed same-origin login route.
    }
    return "/web/auth/login";
  }

  function isHtmlResponse(response) {
    const headers = response && response.headers;
    const contentType =
      headers && typeof headers.get === "function"
        ? headers.get("content-type") || ""
        : "";
    return contentType.toLowerCase().indexOf("text/html") === 0;
  }

  function htmlHas(html, selector) {
    const template = document.createElement("template");
    template.innerHTML = html;
    return Boolean(template.content.querySelector(selector));
  }

  app.initDrawer = function initDrawer() {
    const drawer = document.getElementById("drawer");
    const scrim = document.getElementById("drawer-scrim");
    if (!drawer || !scrim) return;

    const focusableSelector = [
      'a[href]:not([tabindex="-1"]):not([hidden])',
      'button:not([disabled]):not([tabindex="-1"]):not([hidden])',
      'input:not([type="hidden"]):not([disabled]):not([tabindex="-1"]):not([hidden])',
      'select:not([disabled]):not([tabindex="-1"]):not([hidden])',
      'textarea:not([disabled]):not([tabindex="-1"]):not([hidden])',
      '[contenteditable="true"]:not([tabindex="-1"]):not([hidden])',
      '[tabindex]:not([tabindex="-1"]):not([hidden])'
    ].join(", ");
    let currentRow = null;
    let restoreFocusTo = null;
    let backgroundState = [];

    function close() {
      drawer.classList.remove("on");
      scrim.classList.remove("on");
      drawer.setAttribute("aria-hidden", "true");
      markCurrent(null);
      drawer.innerHTML = "";
      currentRow = null;
      unlockBackground();
      restoreFocus();
    }

    function rememberFocus(row) {
      if (drawer.classList.contains("on")) {
        if (!restoreFocusTo || !document.contains(restoreFocusTo)) restoreFocusTo = row;
        return;
      }
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

    function focusableElements() {
      return Array.from(drawer.querySelectorAll(focusableSelector)).filter(function (element) {
        return (
          element.getClientRects().length > 0 &&
          !element.closest('[aria-hidden="true"], [inert]')
        );
      });
    }

    function focusDrawer() {
      const elements = focusableElements();
      const target = elements[0] || drawer;
      if (target && typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
    }

    function activateDrawer(row) {
      drawer.classList.add("on");
      scrim.classList.add("on");
      drawer.setAttribute("aria-hidden", "false");
      lockBackground();
      markCurrent(row);
      focusDrawer();
    }

    function renderSessionExpired(response) {
      drawer.replaceChildren();
      const state = document.createElement("section");
      state.className = "product-state";
      state.setAttribute("role", "alert");
      state.setAttribute("data-drawer-session-expired", "true");

      const title = document.createElement("div");
      title.className = "product-state-title";
      title.textContent = "登录已过期";
      const body = document.createElement("div");
      body.className = "product-state-body";
      body.textContent = "当前操作没有提交，重新登录后再继续处理。";
      const login = document.createElement("a");
      login.className = "product-state-action";
      login.href = sessionLoginUrl(response);
      login.textContent = "重新登录";

      state.append(title, body, login);
      drawer.appendChild(state);
      activateDrawer(currentRow);
    }

    function renderUnexpectedResponse(form) {
      if (form) setDrawerBusy(form, false);
      let alert = drawer.querySelector("[data-drawer-response-error]");
      if (!alert) {
        alert = document.createElement("div");
        alert.className = "product-feedback product-feedback--danger";
        alert.setAttribute("role", "alert");
        alert.setAttribute("data-drawer-response-error", "true");
        drawer.prepend(alert);
      }
      alert.textContent = "服务器没有确认这次操作，列表保持不变。请重新登录或刷新后重试。";
      alert.setAttribute("tabindex", "-1");
      alert.focus({ preventScroll: true });
    }

    function trapFocus(event) {
      const elements = focusableElements();
      if (elements.length === 0) {
        event.preventDefault();
        drawer.focus({ preventScroll: true });
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !drawer.contains(active))) {
        event.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!event.shiftKey && (active === last || !drawer.contains(active))) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    }

    function hasExternalModal() {
      return Array.from(document.querySelectorAll("dialog[open]")).some(function (dialog) {
        return !drawer.contains(dialog);
      });
    }

    function lockBackground() {
      if (backgroundState.length > 0) return;
      const host = drawer.closest(".drawer-host");
      if (!host) return;
      let branch = host;
      while (branch && branch !== document.body) {
        const parent = branch.parentElement;
        if (!parent) break;
        Array.from(parent.children).forEach(function (element) {
          // Native dialogs may be opened from a drawer action. Keep them out of
          // the background set so their own modal focus handling remains usable.
          if (element === branch || element.tagName === "DIALOG") return;
          backgroundState.push({
            element: element,
            hadInert: element.hasAttribute("inert"),
            ariaHidden: element.getAttribute("aria-hidden")
          });
          element.setAttribute("inert", "");
          element.setAttribute("aria-hidden", "true");
        });
        branch = parent;
      }
    }

    function unlockBackground() {
      backgroundState.forEach(function (state) {
        if (!state.hadInert) state.element.removeAttribute("inert");
        if (state.ariaHidden === null) {
          state.element.removeAttribute("aria-hidden");
        } else {
          state.element.setAttribute("aria-hidden", state.ariaHidden);
        }
      });
      backgroundState = [];
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
      if (!row || row.getAttribute("aria-disabled") === "true") return;
      const url = row.getAttribute("data-fragment-url");
      if (!url) return;
      rememberFocus(row);
      currentRow = row;
      fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
        .then(function (res) {
          return res.text().then(function (body) {
            return { response: res, body: body };
          });
        })
        .then(function (result) {
          const res = result.response;
          const body = result.body;
          if (isSessionResponse(res)) {
            renderSessionExpired(res);
            return;
          }
          if (
            !res.ok ||
            res.redirected ||
            !isHtmlResponse(res) ||
            !htmlHas(body, '[data-drawer-fragment="expense-edit"]')
          ) {
            throw new Error("invalid drawer response");
          }
          drawer.innerHTML = body;
          activateDrawer(row);
          bindFragment();
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
        .then(function (res) {
          return res.text().then(function (body) {
            return { response: res, body: body };
          });
        })
        .then(function (result) {
          const res = result.response;
          const body = result.body;
          if (isSessionResponse(res)) {
            renderSessionExpired(res);
            return;
          }
          if (
            !res.ok ||
            res.redirected ||
            !isHtmlResponse(res) ||
            !htmlHas(body, '[data-drawer-fragment="expense-edit"]')
          ) {
            renderUnexpectedResponse(null);
            return;
          }
          drawer.innerHTML = body;
          bindFragment();
          focusDrawer();
        })
        .catch(function () { /* leave the drawer as-is; the row is unchanged */ });
    }

    function markCurrent(row) {
      document.querySelectorAll(".exp-row-detail[aria-current]").forEach(function (candidate) {
        if (candidate !== row) candidate.removeAttribute("aria-current");
        const container = candidate.closest(".exp-row");
        if (container && candidate !== row) container.classList.remove("is-current");
      });
      if (row) {
        row.setAttribute("aria-current", "true");
        const container = row.closest(".exp-row");
        if (container) container.classList.add("is-current");
      }
    }

    // 批10: confirm/忽略 removes the row from the table; decrement the visible
    // pending counts (active filter + 全部) — short-lived drift on the other
    // filters is acceptable and self-heals on the next page load.
    function removeCurrentRow() {
      if (!currentRow) return null;
      const next = nextRow(currentRow);
      const container = currentRow.closest(".exp-row");
      if (container && container.parentNode) container.parentNode.removeChild(container);
      decrementCounts();
      currentRow = null;
      return next;
    }

    function nextRow(row) {
      const container = row.closest(".exp-row");
      if (!container) return null;
      let el = container.nextElementSibling;
      while (el && !el.classList.contains("exp-row")) el = el.nextElementSibling;
      if (el) return el.querySelector(".exp-row-detail[data-fragment-url]");
      // No following row: fall back to the previous one so the reviewer keeps
      // moving instead of dead-ending.
      el = container.previousElementSibling;
      while (el && !el.classList.contains("exp-row")) el = el.previousElementSibling;
      return el ? el.querySelector(".exp-row-detail[data-fragment-url]") : null;
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
          return res.text().then(function (html) {
            if (isSessionResponse(res)) {
              renderSessionExpired(res);
              return;
            }
            if (
              res.ok &&
              !res.redirected &&
              isHtmlResponse(res) &&
              htmlHas(html, '[data-drawer-ok="' + kind + '"]')
            ) {
              onMutationOk(kind);
              return;
            }
            // Error: server returns the drawer fragment with the inline error.
            if (
              !res.ok &&
              !res.redirected &&
              isHtmlResponse(res) &&
              htmlHas(html, '[data-drawer-fragment="expense-edit"]')
            ) {
              drawer.innerHTML = html;
              bindFragment();
              focusDrawer();
              return;
            }
            renderUnexpectedResponse(form);
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
      if (!drawer.classList.contains("on") || hasExternalModal()) return;
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "Tab") {
        trapFocus(e);
      }
    });

    document.querySelectorAll(".exp-row-detail[data-fragment-url]").forEach(function (row) {
      row.addEventListener("click", function (e) {
        if (row.getAttribute("aria-disabled") === "true") {
          e.preventDefault();
          e.stopPropagation();
          return;
        }
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
