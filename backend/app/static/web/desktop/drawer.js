/* Pending review uses the shared durable task; the drawer owns queue navigation and presentation.
 * Ignore keeps its confirmation dialog, original command and undo result. FX actions retain their existing owner. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  // Action kind derived from the POST target so success handling can branch
  // without coupling to exact element ids.
  function actionKind(url) {
    if (/\/fx(?:-status)?$/.test(url)) return "fx";
    if (/\/confirm$/.test(url)) return "confirm";
    if (/\/reject$/.test(url)) return "reject";
    if (/\/duplicates\/\d+\/keep$/.test(url)) return "keep";
    return "save";
  }

  function preserveReviewOnLeave(hasUnsubmittedInput) {
    window.addEventListener("beforeunload", function (event) {
      if (hasUnsubmittedInput()) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  function bindReviewSubtasks() {
    const related = document.querySelector("[data-review-subtasks]");
    if (!related) return;
    if (related.dataset.reviewError && !window.location.hash) {
      window.history.replaceState(null, "", "#expense-" + related.dataset.reviewError);
    }
    const forms = [...document.querySelectorAll("[data-review-form]")];
    let submittingForm = null;
    forms.forEach(form => {
      form.addEventListener("input", () => { form.dataset.edited = "true"; });
      form.addEventListener("submit", event => {
        submittingForm = form;
        queueMicrotask(() => { if (event.defaultPrevented) submittingForm = null; });
      });
    });
    preserveReviewOnLeave(() => {
      const submitted = submittingForm;
      submittingForm = null;
      return forms.some(form => form.dataset.edited && form !== submitted);
    });
    let showingRelated = null;
    function showReviewStage() {
      const target = window.location.hash;
      const next = target === "#expense-items" || target === "#expense-splits";
      document.querySelectorAll("[data-review-stage]").forEach(node => {
        node.hidden = (node.dataset.reviewStage === "details") !== next;
      });
      if (next) related.querySelectorAll(":scope > details").forEach(node => { node.open = true; });
      related.querySelectorAll(".product-segments a").forEach(link => {
        if (link.hash === target) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
      if (showingRelated !== next && (next || showingRelated !== null)) {
        document.getElementById(next ? "review-breakdown" : "review").focus({preventScroll: true});
        window.scrollTo(0, 0);
      }
      showingRelated = next;
    }
    window.addEventListener("hashchange", showReviewStage);
    showReviewStage();
  }

  app.initDrawer = function initDrawer() {
    bindReviewSubtasks();
    const drawer = document.getElementById("drawer");
    const scrim = document.getElementById("drawer-scrim");
    if (!drawer || !scrim) return;

    const focusableSelector = [
      'a[href]:not([tabindex="-1"]):not([hidden])',
      'button:not([disabled]):not([tabindex="-1"]):not([hidden])',
      'input:not([type="hidden"]):not([disabled]):not([tabindex="-1"]):not([hidden])',
      'select:not([disabled]):not([tabindex="-1"]):not([hidden])',
      'textarea:not([disabled]):not([tabindex="-1"]):not([hidden])',
      'summary',
      '[contenteditable="true"]:not([tabindex="-1"]):not([hidden])',
      '[tabindex]:not([tabindex="-1"]):not([hidden])'
    ].join(", ");
    let currentRow = null;
    let restoreFocusTo = null;
    let backgroundState = [];
    const wideReview = window.matchMedia("(min-width: 80rem)");
    let reviewController = null, continuation = null;
    let opening = 0;
    let submitting = false;
    let activeExpenseId = "";
    const batchKey = window.location.pathname + window.location.search;
    const previousBatch = window.history.state?.expenseReviewBatch;
    const batchIds = previousBatch?.key === batchKey ? previousBatch.ids :
      [...document.querySelectorAll(".exp-row[data-expense-id]")].map(row => row.dataset.expenseId);
    window.history.replaceState({...window.history.state, expenseReviewBatch: {key: batchKey, ids: batchIds}}, "");

    function releaseCurrent() {
      const released = reviewController?.dispose(); reviewController = null;
      window.clearTimeout(continuation); continuation = null;
      window.TicketboxExpenseReview?.refreshShelf();
      return released;
    }
    function clearTaskAnchor() {
      if (window.location.hash.startsWith("#expensereview-edit-")) {
        const next = new URL(window.location.href); next.hash = "";
        window.history.replaceState(window.history.state, "", next);
      }
    }

    function syncReviewLayout() {
      const open = drawer.classList.contains("on");
      drawer.setAttribute("aria-modal", String(!wideReview.matches));
      if (open && !wideReview.matches) lockBackground();
      else unlockBackground();
    }
    wideReview.addEventListener("change", syncReviewLayout);
    preserveReviewOnLeave(() => !submitting && (reviewController ? reviewController.hasUnretainedInput() : drawer.querySelector('[data-drawer-form][data-edited="true"]')));

    function close() {
      if (submitting || reviewController?.hasUnretainedInput()) return;
      opening += 1;
      releaseCurrent();
      clearTaskAnchor();
      drawer.classList.remove("on");
      scrim.classList.remove("on");
      drawer.setAttribute("aria-hidden", "true");
      markCurrent(null);
      if (currentRow) currentRow.setAttribute("aria-expanded", "false");
      drawer.innerHTML = "";
      drawer.inert = false;
      currentRow = null;
      unlockBackground();
      restoreFocus();
      if (!document.querySelector(".exp-row[data-expense-id]")) window.location.assign(window.location.href);
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
          element.checkVisibility() &&
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
      app.bindReviewFields(drawer);
      drawer.querySelectorAll("[data-review-position]").forEach(function (position) {
        const index = batchIds.indexOf(activeExpenseId);
        position.textContent = index < 0 ? "原核对任务" : "第 " + (index + 1) + " / " + batchIds.length + " 张";
      });
      const image = drawer.querySelector(".product-drawer-receipt img");
      if (image) app.bindReceiptControls(drawer, image);
      if (typeof app.initReceiptSkeletons === "function") app.initReceiptSkeletons(drawer);
      drawer.querySelectorAll("[data-drawer-close]").forEach(function (b) {
        b.onclick = close;
      });
      // K3: 冲突横幅的「放弃修改，载入现值」在抽屉内原地重取 fragment
      // (fresh OCC token + 权威字段值), 不把用户踢出队列。
      drawer.querySelectorAll("[data-drawer-reload]").forEach(function (link) {
        link.onclick = function (e) {
          e.preventDefault();
          refetchCurrent();
        };
      });
      bindDrawerForm();
    }

    // Fetch the edit fragment for a row and swap it into the open drawer. On a
    // fetch error fall back to the row's full-page edit link (unchanged
    // behaviour for the open action).
    function openRow(row, resume = false) {
      if (!row || submitting || reviewController?.hasUnretainedInput()) return;
      if (row === currentRow && drawer.classList.contains("on")) return;
      // 防御守卫（无当前生产者：批选不再挂 aria-disabled）：行链接被显式
      // 禁用时，程序化入口（review-keyboard 的 drawerApi.open）同样让路。
      if (row.getAttribute("aria-disabled") === "true") return;
      const url = row.getAttribute("data-fragment-url");
      if (!url) return;
      rememberFocus(row);
      releaseCurrent();
      if (!resume) clearTaskAnchor();
      drawer.inert = true;
      if (currentRow) currentRow.setAttribute("aria-expanded", "false");
      currentRow = row;
      activeExpenseId = row.closest(".exp-row")?.dataset.expenseId || row.dataset.expenseId;
      const generation = ++opening;
      function showFragment(html) {
        if (generation !== opening) return;
        if (typeof html === "string") drawer.innerHTML = html;
        else drawer.replaceChildren(html);
        drawer.inert = false;
        drawer.classList.add("on");
        scrim.classList.add("on");
        drawer.setAttribute("aria-hidden", "false");
        syncReviewLayout();
        markCurrent(row);
        row.setAttribute("aria-expanded", "true");
        bindFragment();
        focusDrawer();
      }
      fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
        .then(function (res) { return res.text(); })
        .then(showFragment)
        .catch(function () {
          if (generation !== opening) return;
          close();
          window.location.href = row.getAttribute("href");
        });
    }

    // Re-fetch the current row's fragment in place (after save / keep success)
    // so the form picks up a fresh OCC token and cleared flags.
    function refetchCurrent() {
      if (!currentRow) { close(); return; }
      const url = currentRow.getAttribute("data-fragment-url");
      const generation = opening;
      return fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
        .then(function (res) { return res.text(); })
        .then(async function (html) {
          if (generation !== opening) return;
          await releaseCurrent();
          if (generation !== opening) return;
          clearTaskAnchor();
          drawer.innerHTML = html;
          bindFragment();
          resyncRowConsumers();
          focusDrawer();
          return syncSavedRow(generation);
        })
        .catch(function () {
          if (generation !== opening) return;
          const form = drawer.querySelector("[data-drawer-form]");
          if (form) setDrawerBusy(form, false);
        });
    }

    // save/keep 的 refetch 带回新 expected_row_version：同一新 OCC token 必须
    // 同步给该行全部消费者 —— checkbox 的 data-row-version 与 value
    // （id:version）、行内 quick-confirm 的 expense_snapshot；bulk form 的
    // hidden token 由 bulk-bar 按 checkbox 现状重建（checked 与计数天然保留）。
    function resyncRowConsumers() {
      if (!currentRow) return;
      const fresh = drawer.querySelector('[data-drawer-form] input[name="expected_row_version"]');
      const version = fresh && fresh.value;
      if (!version) return;
      const container = currentRow.closest(".exp-row");
      const expenseId = container && container.getAttribute("data-expense-id");
      if (!expenseId) return;
      const snapshot = expenseId + ":" + version;
      const checkbox = container.querySelector(".row-check");
      if (checkbox) {
        checkbox.setAttribute("data-row-version", version);
        checkbox.value = snapshot;
      }
      container.querySelectorAll('form input[type="hidden"][name="expense_snapshot"]').forEach(function (node) {
        node.value = snapshot;
      });
      if (typeof app.refreshBulkBar === "function") app.refreshBulkBar();
    }

    // 焦点合同下不再有第二套「选中」态标记：drawer 打开时只标
    // is-current（与 bulk-bar 同族的容器高亮，inbox.css），行高亮交给 :focus-within。
    function markCurrent(row) {
      document.querySelectorAll(".exp-row.is-current").forEach(function (r) {
        r.classList.remove("is-current");
      });
      if (row) {
        const container = row.closest(".exp-row");
        if (container) container.classList.add("is-current");
      }
    }

    // 批10: confirm/忽略 removes the row from the table; decrement the visible
    // pending counts (active filter + 全部) — short-lived drift on the other
    // filters is acceptable and self-heals on the next page load.
    // 行结构 (#218/S4-R1): drawer 操作的是行链接 (a.exp-row-detail), 移除/找
    // 下一行都要落到外层行容器 .exp-row 上, 否则残留孤立的 checkbox 单元格。
    function removeCurrentRow() {
      if (!currentRow) return null;
      const next = nextRow(currentRow);
      const container = currentRow.closest(".exp-row");
      if (container) { container.remove(); decrementCounts(); }
      currentRow = null;
      app.refreshBulkBar?.();
      return next;
    }

    function rowLink(container) {
      return container.querySelector(".exp-row-detail[data-fragment-url]");
    }

    function nextRow(row) {
      const rows = [...document.querySelectorAll(".exp-row[data-expense-id]")].filter(container => rowLink(container) !== row);
      const current = batchIds.indexOf(activeExpenseId);
      const next = rows.find(container => batchIds.indexOf(container.dataset.expenseId) > current) || rows[0];
      return next ? rowLink(next) : null;
    }

    function decrementCounts() {
      const seen = [];
      const active = document.querySelector(".filter-tab.is-active .count");
      const total = document.querySelector(".filter-tab .count"); // 全部 is first
      [active, total, ...document.querySelectorAll('[data-pending-count], [data-filtered-count], a[href^="/web/pending"] > .nav-badge')].forEach(function (node) {
        if (!node || seen.indexOf(node) !== -1) return;
        seen.push(node);
        const n = parseInt(node.textContent, 10);
        if (!isNaN(n) && n > 0) node.textContent = String(n - 1);
      });
      if (!document.querySelector(".exp-row[data-expense-id]")) {
        document.querySelectorAll(".inbox-review-start, [data-bulk-select]").forEach(node => { node.hidden = true; });
      }
    }

    // --- drawer form fetch-mutation ---------------------------------------

    function bindDrawerForm() {
      const form = drawer.querySelector("[data-drawer-form]");
      if (!form || form.getAttribute("data-fetch-bound") === "1") return;
      form.setAttribute("data-fetch-bound", "1");
      reviewController = window.TicketboxExpenseReview?.mount(form, {embedded: true, onAccepted: showAccepted});
      form.addEventListener("input", function () { form.dataset.edited = "true"; });
      form.addEventListener("submit", function (e) {
        if (e.defaultPrevented) return;
        const submitter = e.submitter || document.activeElement;
        const actionUrl =
          (submitter && submitter.getAttribute && submitter.getAttribute("formaction")) ||
          form.getAttribute("action");
        if (!actionUrl) return;
        // Save/confirm/keep/reject belong to the shared durable task. Without enhancement,
        // their original native form is submitted exactly once.
        if (["save", "confirm", "keep", "reject"].includes(actionKind(actionUrl)) || submitter?.name === "review_latest") return;
        e.preventDefault();
        submitDrawer(form, actionUrl);
      });
    }

    async function showAccepted({next, values}) {
      if (values.command_action === "reject") {
        await releaseCurrent(); clearTaskAnchor(); window.location.assign(next.href); return;
      }
      const generation = opening;
      const confirmation = !["save", "keep"].includes(values.command_action);
      const following = confirmation ? removeCurrentRow() : null;
      const url = new URL(next); url.searchParams.set("fragment", "1");
      try {
        const response = await fetch(url, {credentials: "same-origin", headers: {Accept: "text/html"}});
        if (!response.ok) throw Error("accepted_view_unavailable");
        const html = await response.text();
        if (generation !== opening) return;
        // A recovered save may now belong to a confirmed bill. Its current
        // read-only detail remains the native consumer, not another edit form.
        if (!confirmation && !new DOMParser().parseFromString(html, "text/html").querySelector("[data-drawer-form]")) {
          window.location.assign(next.href); return;
        }
        await releaseCurrent();
        if (generation !== opening) return;
        clearTaskAnchor();
        drawer.innerHTML = html; bindFragment(); resyncRowConsumers(); focusDrawer();
        if (!confirmation) {
          await refreshAcceptedRow(generation, values.command_action);
          return;
        }
        const button = drawer.querySelector("[data-confirmation-next]");
        if (!following || !button) return;
        button.hidden = false; button.onclick = () => openRow(following);
        const note = drawer.querySelector("[data-confirmation-next-note]");
        note.hidden = false; note.textContent = "这张已入账，接着核对下一张。";
        drawer.querySelector("[data-confirmation-finish]").classList.replace("product-button--primary", "product-button--quiet");
        continuation = window.setTimeout(() => {
          if (generation === opening) openRow(following);
        }, 1500);
        const receipt = drawer.querySelector("[data-expense-confirmation]");
        for (const event of ["pointerdown", "keydown"]) receipt.addEventListener(event, () => window.clearTimeout(continuation));
      } catch (_) {
        if (generation !== opening) return;
        releaseCurrent(); clearTaskAnchor();
        const panel = document.createElement("section"), title = document.createElement("h2"), notice = document.createElement("p"), link = document.createElement("a"), back = document.createElement("button");
        panel.className = "product-panel product-panel--padded";
        title.textContent = {keep: "这次非重复决定已保存", save: "这次草稿已保存"}[values.command_action] || "这次确认已入账";
        notice.textContent = "展示结果暂时未能读取。可重新打开结果，无需再次提交。";
        link.href = next.href; link.textContent = "重新打开结果"; link.className = "product-button product-button--primary";
        back.type = "button"; back.textContent = "返回收件箱"; back.className = "product-button product-button--quiet"; back.onclick = close;
        panel.append(title, notice, link, back); drawer.replaceChildren(panel); focusDrawer();
      }
    }

    async function refreshAcceptedRow(generation, action) {
      try { await syncSavedRow(generation); }
      catch (_) {
        if (generation === opening) {
          const notice = document.createElement("p"); notice.className = "product-feedback product-feedback--warning";
          notice.setAttribute("role", "status"); notice.textContent = action === "keep"
            ? "非重复决定已保存，收件列表暂未刷新。原填写仍保留，返回列表后可重新读取。"
            : "草稿已保存，收件列表暂未刷新。当前填写仍可继续，返回列表后可重新读取。";
          drawer.querySelector(".product-drawer-form").prepend(notice);
        }
      }
    }

    async function syncSavedRow(generation) {
      const row = currentRow;
      if (!row) return;
      const response = await fetch(window.location.href, {credentials: "same-origin", headers: {Accept: "text/html"}});
      if (!response.ok) throw Error("saved_list_unavailable");
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      if (generation !== opening) return;
      const container = row.closest(".exp-row");
      if (!container) return;
      const fresh = page.querySelector('.exp-row[data-expense-id="' + activeExpenseId + '"]');
      if (!fresh) container.remove();
      else {
        row.innerHTML = fresh.querySelector(".exp-row-detail").innerHTML;
        const check = container.querySelector(".row-check"), latest = fresh.querySelector(".row-check");
        if (check && latest) { check.value = latest.value; check.dataset.rowVersion = latest.dataset.rowVersion; }
        container.querySelector(".exp-flags").innerHTML = fresh.querySelector(".exp-flags").innerHTML;
      }
      document.querySelectorAll(".filter-tab").forEach(tab => {
        const freshTab = [...page.querySelectorAll(".filter-tab")].find(item => item.getAttribute("href") === tab.getAttribute("href"));
        if (freshTab) tab.querySelector(".count").textContent = freshTab.querySelector(".count").textContent;
      });
      document.querySelectorAll("[data-filtered-count]").forEach(count => {
        count.textContent = String(page.querySelectorAll(".exp-row[data-expense-id]").length);
      });
      const navSelector = ':is(.nav-primary, .nav-subnav, .mobile-primary-nav, .mobile-plan-nav) > a:is([href^="/web/pending"], [href^="/web/duplicates"])';
      const freshLinks = [...page.querySelectorAll(navSelector)];
      document.querySelectorAll(navSelector).forEach(link => {
        const freshLink = freshLinks.find(item => item.getAttribute("href") === link.getAttribute("href"));
        if (!freshLink) return;
        const badge = freshLink.querySelector(":scope > .nav-badge");
        link.querySelector(":scope > .nav-badge")?.remove();
        if (badge) link.append(badge.cloneNode(true));
      });
      app.refreshBulkBar?.();
    }

    function submitDrawer(form, actionUrl) {
      if (submitting) return;
      submitting = true;
      const body = new FormData(form);
      body.append("fragment", "1"); // server returns a 200 marker / error fragment
      setDrawerBusy(form, true);
      // window.fetch is wrapped by csrf.js → adds the X-CSRF-Token header for
      // same-origin requests; FormData also carries the csrf_token field when
      // present. Same-origin source + token satisfies the /web CSRF gate.
      fetch(actionUrl, { method: "POST", credentials: "same-origin", body: body })
        .then(function (res) {
          // FX status/retry returns the original form and OCC with saved-bill
          // status alongside it. Only explicit reload may replace that draft.
          // Errors likewise return the fragment with its inline message.
          return res.text().then(async function (html) {
            await releaseCurrent();
            drawer.innerHTML = html;
            const edited = drawer.querySelector("[data-drawer-form]");
            if (edited) edited.dataset.edited = "true";
            bindFragment();
            focusDrawer();
            submitting = false;
          });
        })
        .catch(function () {
          submitting = false;
          setDrawerBusy(form, false);
          const notice = document.createElement("p"); notice.className = "product-feedback product-feedback--warning";
          notice.setAttribute("role", "status");
          notice.textContent = "暂未收到操作结果，填写仍保留。请核对当前账单后继续。";
          notice.tabIndex = -1;
          form.prepend(notice);
          notice.focus();
        });
    }

    function setDrawerBusy(form, busy) {
      form.inert = busy;
      form.querySelectorAll("button[type=submit]").forEach(function (b) {
        b.disabled = busy;
      });
    }

    // --- wiring ------------------------------------------------------------

    scrim.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.defaultPrevented || e.isComposing || !drawer.classList.contains("on") || hasExternalModal()) return;
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "Tab" && !wideReview.matches) {
        trapFocus(e);
      }
    });

    const startReview = document.querySelector("[data-inbox-review-start]");
    if (startReview) startReview.addEventListener("click", function (event) {
      const first = document.querySelector(".exp-row-detail[data-fragment-url]");
      if (!first) return;
      event.preventDefault();
      openRow(first);
    });

    document.querySelectorAll(".exp-row-detail[data-fragment-url]").forEach(function (row) {
      // PE dialog 语义: JS 成立时行链接宣布自身打开 #drawer dialog; 开/关态切 expanded。
      row.setAttribute("aria-haspopup", "dialog");
      row.setAttribute("aria-controls", "drawer");
      row.setAttribute("aria-expanded", "false");
      row.addEventListener("click", function (e) {
        // 纯防御守卫：当前 bulk-bar.js 不生产 aria-disabled；若其他消费者
        // 显式禁用该链接，抽屉也不应绕过它。
        if (row.getAttribute("aria-disabled") === "true") return;
        // 点 checkbox / 表单元素时不打开抽屉
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "button") return;
        if (e.target.closest && e.target.closest("[data-stop=true]")) return;
        e.preventDefault();
        openRow(row);
      });
    });

    // Exposed for review-keyboard.js (Arrow/Home/End focus navigation + Ctrl/⌘+Enter confirm).
    app.drawerApi = {
      open: openRow,
      close: close,
      isOpen: function () { return drawer.classList.contains("on"); },
      currentRow: function () { return currentRow; },
      hasUnsavedChanges: function () {
        return submitting || !!drawer.querySelector('[data-drawer-form][data-edited="true"]') ||
          !!document.querySelector('[data-expensereview-scope] [data-expensereview-ref]');
      },
      submitConfirm: function () {
        const form = drawer.querySelector("[data-drawer-form]");
        if (!form) return false;
        const btn = form.querySelector('[data-expensereview-submit]') || form.querySelector('button[formaction$="/confirm"]');
        if (!btn || btn.disabled) return false;
        btn.click(); // routes through the form submit → fetch pipeline above
        return true;
      }
    };
    const resumeRef = window.location.hash.startsWith("#expensereview-edit-") ? window.location.hash.slice("#expensereview-edit-".length) : "";
    if (resumeRef) {
      const task = [...document.querySelectorAll("[data-expensereview-ref]")].find(link => link.dataset.expensereviewRef === resumeRef);
      if (task) openRow(document.querySelector('.exp-row[data-expense-id="' + task.dataset.expenseId + '"] .exp-row-detail') || task, true);
    }
  };
})(window, document);
