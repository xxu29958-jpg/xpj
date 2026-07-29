/* Bulk selection action bar. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initBulkBar = function initBulkBar() {
    const form = document.querySelector("[data-bulk]");
    if (!form) return;
    const counter = form.querySelector("[data-bulk-count]");
    const all = document.getElementById("check-all");
    const checks = Array.from(document.querySelectorAll(".row-check"));
    const clearButton = form.querySelector("[data-bulk-clear]");
    const navigationRows = Array.from(
      document.querySelectorAll(".exp-row-detail[href], .timeline-row-detail[href]")
    );
    let batchModeActive = false;
    let navigationState = [];

    // 218-D S4/R1: 双模式 checkbox。收件新页 (#218 同构: 选择槽与行链接兄弟)
    // 的勾选控件是 div.checkbox[role=checkbox] + .checked class/aria-checked
    // (product/components.css 的 .checkbox 族只认 .checked); confirmed 等旧页
    // 仍是 input[type=checkbox]。两栈共用本文件, 读写统一走这两个助手。
    function isNativeBox(el) {
      return el.tagName === "INPUT";
    }

    function isChecked(el) {
      return isNativeBox(el) ? el.checked : el.classList.contains("checked");
    }

    function setChecked(el, on) {
      if (isNativeBox(el)) {
        el.checked = on;
      } else {
        el.classList.toggle("checked", on);
        el.setAttribute("aria-checked", on ? "true" : "false");
      }
    }

    function attributeState(element, name) {
      return {
        present: element.hasAttribute(name),
        value: element.getAttribute(name)
      };
    }

    function restoreAttribute(element, name, state) {
      if (state.present) {
        element.setAttribute(name, state.value);
      } else {
        element.removeAttribute(name);
      }
    }

    // Product choice: a non-empty selection is an exclusive batch mode for
    // these transaction queues. This is informed by conditional batch-action
    // practice, not treated as a universal table rule. The checkbox stays
    // operable while row-level navigation is suspended.
    function setBatchNavigationMode(active) {
      if (active === batchModeActive) return;
      if (active) {
        navigationState = navigationRows.map(function (row) {
          return {
            row: row,
            tabIndex: attributeState(row, "tabindex"),
            disabled: attributeState(row, "aria-disabled"),
            current: attributeState(row, "aria-current")
          };
        });
        navigationRows.forEach(function (row) {
          row.setAttribute("aria-disabled", "true");
          row.setAttribute("tabindex", "-1");
          row.removeAttribute("aria-current");
          const container = row.closest(".exp-row");
          if (container) container.classList.remove("is-current");
        });
      } else {
        navigationState.forEach(function (state) {
          if (!document.contains(state.row)) return;
          restoreAttribute(state.row, "tabindex", state.tabIndex);
          restoreAttribute(state.row, "aria-disabled", state.disabled);
          restoreAttribute(state.row, "aria-current", state.current);
          const container = state.row.closest(".exp-row");
          if (container) {
            container.classList.toggle(
              "is-current",
              state.current.present && state.current.value === "true"
            );
          }
        });
        navigationState = [];
      }
      batchModeActive = active;
    }

    navigationRows.forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (row.getAttribute("aria-disabled") !== "true") return;
        if (event.target.closest && event.target.closest(".row-check")) return;
        event.preventDefault();
        event.stopImmediatePropagation();
      }, true);
    });

    // 被类目筛选隐藏的行不参与批选/提交,否则"全选"会误改用户没看见的别类目账单。
    function isVisible(cb) {
      const row = cb.closest(".exp-row, .timeline-row");
      return !row || row.offsetParent !== null;
    }

    function selectedEntries() {
      const entries = [];
      document.querySelectorAll(".row-check:checked, .row-check.checked").forEach(function (el) {
        if (!isVisible(el)) return;
        entries.push({
          id: el.getAttribute("data-id"),
          rowVersion: el.getAttribute("data-row-version") || ""
        });
      });
      return entries;
    }

    function refresh() {
      const entries = selectedEntries();
      counter.textContent = String(entries.length);
      form.classList.toggle("on", entries.length > 0);
      checks.forEach(function (cb) {
        const checked = isChecked(cb);
        const row = cb.closest(".exp-row, .timeline-row");
        if (row) {
          // 选中态视觉: 容器 .selected 类 (旧页旧 CSS / 新栈 inbox.css 同名规则)。
          row.classList.toggle("selected", checked);
        }
      });
      setBatchNavigationMode(entries.length > 0);
      // 同步隐藏 input
      form.querySelectorAll('input[name="expense_ids"]').forEach(function (n) { n.remove(); });
      form.querySelectorAll('input[name="expected_row_version"]').forEach(function (n) { n.remove(); });
      entries.forEach(function (entry) {
        const h = document.createElement("input");
        h.type = "hidden";
        h.name = "expense_ids";
        h.value = entry.id;
        form.appendChild(h);

        const token = document.createElement("input");
        token.type = "hidden";
        token.name = "expected_row_version";
        token.value = entry.rowVersion;
        form.appendChild(token);
      });
      if (all) {
        const visibleCount = checks.filter(isVisible).length;
        const allChecked = visibleCount > 0 && entries.length === visibleCount;
        if (isNativeBox(all)) {
          all.checked = allChecked;
          all.indeterminate = !allChecked && entries.length > 0;
        } else {
          all.classList.toggle("checked", allChecked);
          all.setAttribute(
            "aria-checked",
            allChecked ? "true" : entries.length > 0 ? "mixed" : "false"
          );
        }
      }
    }

    // 暴露给 ledger-filter.js:筛选改变可见行后重算计数 + 重建提交字段。
    app.refreshBulkBar = refresh;

    // 批10: shift-click 范围连选。记最近点击的行 index;按住 shift 点另一行时,把
    // 区间内的可见行全部设成被点行的新状态(剔除隐藏行,与 isVisible 一致)。
    let lastIndex = -1;

    function applyRowToggle(cb, index, e, turnOn) {
      setChecked(cb, turnOn);
      if (e && e.shiftKey && lastIndex !== -1 && lastIndex !== index) {
        const lo = Math.min(lastIndex, index);
        const hi = Math.max(lastIndex, index);
        for (let i = lo; i <= hi; i++) {
          if (!isVisible(checks[i])) continue; // 只作用可见行
          setChecked(checks[i], turnOn);
        }
      }
      lastIndex = index;
      refresh();
    }

    checks.forEach(function (cb, index) {
      if (isNativeBox(cb)) {
        cb.addEventListener("click", function (e) {
          e.stopPropagation();
          applyRowToggle(cb, index, e, isChecked(cb));
        });
      } else {
        // div[role=checkbox]: 点击与 Space/Enter 都走同一 toggle; 吞事件是
        // 防嵌套回归的兜底 (控件若再被移进行链接, 勾选也不会穿透触发整行
        // 跳转/开抽屉 — C5a 教训, 矿同款 bindCheckbox)。
        const handler = function (e) {
          e.preventDefault();
          e.stopPropagation();
          applyRowToggle(cb, index, e, !isChecked(cb));
        };
        cb.addEventListener("click", handler);
        cb.addEventListener("keydown", function (e) {
          if (e.key !== " " && e.key !== "Enter") return;
          handler(e);
        });
      }
    });
    if (all) {
      const toggleAll = function (turnOn) {
        checks.forEach(function (cb) {
          if (turnOn && !isVisible(cb)) return; // 全选只勾可见行
          setChecked(cb, turnOn);
        });
        refresh();
      };
      if (isNativeBox(all)) {
        all.addEventListener("click", function () {
          toggleAll(isChecked(all));
        });
      } else {
        const allHandler = function (e) {
          e.preventDefault();
          e.stopPropagation();
          toggleAll(!isChecked(all));
        };
        all.addEventListener("click", allHandler);
        all.addEventListener("keydown", function (e) {
          if (e.key !== " " && e.key !== "Enter") return;
          allHandler(e);
        });
      }
    }

    // issue #64 W3: progressive-enhancement fetch+partial for the two removal
    // bulk actions — 批量确认入账 (/web/review/bulk confirm_ready) and 批量忽略
    // (/web/pending/batch-reject). Both pop rows out of the pending list, so on
    // success the server answers {removed_ids, message, flash_type} and we
    // splice exactly those rows, clear the selection, nudge the filter counts,
    // and flash the summary — no full-page reload (mirrors drawer.js). The
    // in-place 设置分类/设置商家 actions stay on the native redirect. Any fetch
    // failure (offline) falls through to a native full-page submit.
    function submitterActionUrl(submitter) {
      return (submitter && submitter.getAttribute && submitter.getAttribute("formaction")) ||
        form.getAttribute("action") || "";
    }

    function removalKind(actionUrl, submitter) {
      if (/\/pending\/batch-reject$/.test(actionUrl)) return "reject";
      const value = (submitter && submitter.getAttribute && submitter.getAttribute("value")) || "";
      if (/\/review\/bulk$/.test(actionUrl) && value === "confirm_ready") return "confirm_ready";
      return null; // set_category / set_merchant → native full-page POST
    }

    function flashBanner(message, type, undoItems) {
      if (!message) return;
      const content = document.querySelector("main.content");
      if (!content) return;
      let banner = document.getElementById("bulk-flash");
      if (!banner) {
        banner = document.createElement("div");
        banner.id = "bulk-flash";
        // Match the no-JS flash position: 新栈 pending.html 的 feedback 在
        // .product-page-header 之后, 旧页在 .page-header 之后 (nextSibling
        // null → appended). Falls back to the top if the header isn't present.
        const header = content.querySelector(".product-page-header, .page-header");
        content.insertBefore(banner, header ? header.nextSibling : content.firstElementChild);
      }
      // Reuse the server flash classes (alert.css; product/components.css 给
      // 新栈页备了同名别名) so the look matches the no-JS redirect banner —
      // no new CSS, no hardcoded values.
      banner.className = "dt-alert" +
        (type === "success" ? " success" : type === "error" ? " danger" : "") +
        (undoItems && undoItems.length ? " undo-banner" : "");
      const isError = type === "error";
      banner.setAttribute("role", isError ? "alert" : "status");
      banner.setAttribute("aria-live", isError ? "assertive" : "polite");
      banner.setAttribute("aria-atomic", "true");
      banner.textContent = "";
      const text = document.createElement("span");
      text.textContent = message;
      banner.appendChild(text);
      if (undoItems && undoItems.length) {
        const undoForm = document.createElement("form");
        undoForm.method = "post";
        undoForm.action = "/web/pending/batch-undo";
        undoForm.className = "undo-banner-action";
        undoForm.setAttribute("aria-label", "撤销刚才的批量操作");
        const ledger = form.querySelector('input[name="ledger_id"]');
        if (ledger) {
          const ledgerInput = document.createElement("input");
          ledgerInput.type = "hidden";
          ledgerInput.name = "ledger_id";
          ledgerInput.value = ledger.value;
          undoForm.appendChild(ledgerInput);
        }
        undoItems.forEach(function (item) {
          const idInput = document.createElement("input");
          idInput.type = "hidden";
          idInput.name = "expense_ids";
          idInput.value = item.id;
          undoForm.appendChild(idInput);

          const tokenInput = document.createElement("input");
          tokenInput.type = "hidden";
          tokenInput.name = "expected_row_version";
          tokenInput.value = item.expected_row_version;
          undoForm.appendChild(tokenInput);
        });
        const button = document.createElement("button");
        button.type = "submit";
        button.className = "dt-btn";
        button.textContent = "撤销 " + undoItems.length + " 条";
        button.setAttribute(
          "aria-label",
          "撤销刚才处理的 " + undoItems.length + " 条流水"
        );
        undoForm.appendChild(button);
        banner.appendChild(undoForm);
      }
    }

    // Mirror drawer.js's count drift policy: decrement the active filter tab and
    // 全部 by however many rows actually left; the other tabs self-heal on the
    // next page load.
    function decrementFilterCounts(n) {
      if (n <= 0) return;
      const seen = [];
      const active = document.querySelector(".filter-tab.is-active .count");
      const total = document.querySelector(".filter-tab .count"); // 全部 is first
      [active, total].forEach(function (node) {
        if (!node || seen.indexOf(node) !== -1) return;
        seen.push(node);
        const cur = parseInt(node.textContent, 10);
        if (!isNaN(cur)) node.textContent = String(Math.max(0, cur - n));
      });
    }

    function clearSelection(focusTarget) {
      document.querySelectorAll(".row-check:checked, .row-check.checked").forEach(function (cb) {
        setChecked(cb, false);
      });
      refresh(); // 0 selected → hides the bar + rebuilds the hidden id fields
      if (
        focusTarget &&
        document.contains(focusTarget) &&
        typeof focusTarget.focus === "function"
      ) {
        focusTarget.focus({ preventScroll: true });
      }
    }

    if (clearButton) {
      clearButton.addEventListener("click", function () {
        const focusTarget =
          checks.find(function (cb) { return isChecked(cb) && isVisible(cb); }) ||
          checks.find(function (cb) { return isChecked(cb); });
        clearSelection(focusTarget);
      });
    }

    function applyBulkResult(data) {
      const ids = (data && data.removed_ids) || [];
      let removed = 0;
      ids.forEach(function (id) {
        const row = document.querySelector('.exp-row[data-expense-id="' + id + '"]');
        if (row && row.parentNode) { row.parentNode.removeChild(row); removed++; }
      });
      clearSelection();
      decrementFilterCounts(removed);
      flashBanner(
        data && data.message,
        (data && data.flash_type) || "success",
        data && data.undo_items
      );
    }

    function setBulkBusy(busy) {
      form.querySelectorAll("button[type=submit]").forEach(function (b) {
        b.disabled = busy;
      });
    }

    function nativeFallback(actionUrl, submitter) {
      form.setAttribute("action", actionUrl);
      form.setAttribute("data-native-fallback", "1");
      // requestSubmit (not .submit()) fires the real submit event so csrf.js
      // injects csrf_token; passing the submitter keeps its name/value
      // (action=confirm_ready) + formaction. .submit() skips the event → 403.
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit(submitter);
      } else {
        HTMLFormElement.prototype.submit.call(form);
      }
    }

    function submitBulk(actionUrl, submitter) {
      const body = new FormData(form);
      // FormData(form) omits the submit button — carry its name/value so
      // /web/review/bulk still sees action=confirm_ready. csrf.js's fetch
      // wrapper adds X-CSRF-Token; the form also carries the injected
      // csrf_token field, so the /web CSRF gate is satisfied either way.
      if (submitter && submitter.name) body.append(submitter.name, submitter.value);
      body.append("fragment", "1");
      setBulkBusy(true);
      fetch(actionUrl, { method: "POST", credentials: "same-origin", body: body })
        .then(function (res) {
          return res.json().then(function (data) { return { ok: res.ok, data: data }; });
        })
        .then(function (out) {
          setBulkBusy(false);
          if (out.ok) {
            applyBulkResult(out.data);
          } else {
            flashBanner((out.data && out.data.message) || "操作失败，请重试。", "error");
          }
        })
        .catch(function () {
          setBulkBusy(false);
          nativeFallback(actionUrl, submitter);
        });
    }

    function bindSubmit() {
      if (form.getAttribute("data-fetch-bound") === "1") return;
      form.setAttribute("data-fetch-bound", "1");
      form.addEventListener("submit", function (e) {
        // Offline-fallback re-entry guard: requestSubmit() re-fires this listener.
        if (form.getAttribute("data-native-fallback") === "1") return;
        const submitter = e.submitter || document.activeElement;
        const actionUrl = submitterActionUrl(submitter);
        const kind = removalKind(actionUrl, submitter);
        if (!kind) return; // not a removal action → leave the native submit alone
        e.preventDefault();
        // confirm-modal latches data-confirm buttons (批量忽略) with _tbConfirmed.
        // Without a reload that flag persists and skips the dialog next time —
        // clear it so the next 批量忽略 re-prompts.
        if (submitter && submitter.dataset) delete submitter.dataset._tbConfirmed;
        submitBulk(actionUrl, submitter);
      });
    }

    bindSubmit();
    refresh();
  };
})(window, document);
