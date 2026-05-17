/* /web 桌面账本 · v0.10 vanilla JS
 *
 * 由 base.html `<script defer>` 引入，按需绑定页面里出现的元素：
 *   - #theme-toggle      → 循环切换 paper / mono / midnight，写 cookie + localStorage
 *   - #ledger-switcher   → 顶栏账本下拉
 *   - .exp-row           → 点击打开编辑抽屉（fetch ?fragment=1 注入）
 *   - .row-check         → 多选 + 浮动批量操作条
 *   - #chart-trend       → ECharts 月度趋势（六个月柱+线+预算虚线）
 *   - #chart-category    → ECharts 分类环图
 *   - .spark[data-points]→ Dashboard 14 日 sparkline (纯 SVG)
 *
 * 设计稿原始 JSX 在 design-system/project/，本文件把它的状态机翻成 vanilla。
 */
(function () {
  "use strict";

  // ─── Theme toggle ──────────────────────────────────────────────
  const THEMES = ["paper", "mono", "midnight"];
  function applyTheme(theme) {
    if (!THEMES.includes(theme)) theme = "paper";
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("ui-theme", theme); } catch (_) {}
    // SSR 用 cookie 读取主题以避免下次刷新闪烁
    document.cookie = "ui_theme=" + theme + ";path=/;max-age=31536000;samesite=lax";
  }
  function initThemeToggle() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      const current = document.documentElement.getAttribute("data-theme") || "paper";
      const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
      applyTheme(next);
    });
  }

  // ─── Ledger switcher dropdown ──────────────────────────────────
  function initLedgerSwitcher() {
    const root = document.getElementById("ledger-switcher");
    const popover = document.getElementById("ledger-popover");
    if (!root || !popover) return;
    root.addEventListener("click", function (e) {
      // 仅当点击 chip 自身（非 popover 行）时翻转
      if (popover.contains(e.target)) return;
      const open = popover.classList.toggle("open");
      root.setAttribute("data-open", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (root.contains(e.target)) return;
      popover.classList.remove("open");
      root.setAttribute("data-open", "false");
    });
  }

  // ─── Sparkline SVG render ──────────────────────────────────────
  function renderSpark(svg) {
    if (svg.getAttribute("data-spark-rendered") === "1") return;
    const raw = svg.getAttribute("data-points");
    if (!raw) return;
    let points;
    try { points = JSON.parse(raw); } catch (_) { return; }
    if (!points || !points.length) return;
    svg.setAttribute("data-spark-rendered", "1");
    const W = 280, H = 56;
    const vs = points.map(function (d) { return d.amount_yuan || 0; });
    const max = Math.max.apply(null, vs) || 1;
    const stepX = W / Math.max(points.length - 1, 1);
    const pts = points.map(function (d, i) {
      return [i * stepX, H - 6 - ((d.amount_yuan || 0) / max) * (H - 12)];
    });
    const path = pts.map(function (p, i) {
      return (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1);
    }).join(" ");
    const area = path + " L " + W + "," + H + " L 0," + H + " Z";
    const ns = "http://www.w3.org/2000/svg";
    const areaEl = document.createElementNS(ns, "path");
    areaEl.setAttribute("d", area);
    areaEl.setAttribute("fill", "url(#sparkArea)");
    svg.appendChild(areaEl);
    const lineEl = document.createElementNS(ns, "path");
    lineEl.setAttribute("d", path);
    lineEl.setAttribute("fill", "none");
    lineEl.setAttribute("stroke", "currentColor");
    lineEl.setAttribute("stroke-width", "1.25");
    svg.appendChild(lineEl);
    if (pts.length) {
      const last = pts[pts.length - 1];
      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", last[0]);
      dot.setAttribute("cy", last[1]);
      dot.setAttribute("r", "2.5");
      dot.setAttribute("fill", "var(--brand-primary)");
      svg.appendChild(dot);
    }
  }
  function initSparks(root) {
    (root || document).querySelectorAll(".spark[data-points]").forEach(renderSpark);
  }

  // ─── Drawer (single expense edit) ───────────────────────────────
  function initDrawer() {
    const drawer = document.getElementById("drawer");
    const scrim = document.getElementById("drawer-scrim");
    if (!drawer || !scrim) return;

    function close() {
      drawer.classList.remove("on");
      scrim.classList.remove("on");
      drawer.innerHTML = "";
    }
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
        const url = row.getAttribute("data-fragment-url");
        fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } })
          .then(function (res) { return res.text(); })
          .then(function (html) {
            drawer.innerHTML = html;
            drawer.classList.add("on");
            scrim.classList.add("on");
            initReceiptSkeletons(drawer);
            drawer.querySelectorAll("[data-drawer-close]").forEach(function (b) {
              b.addEventListener("click", close);
            });
          })
          .catch(function () {
            // fallback：fetch 失败时按链接正常跳转
            window.location.href = row.getAttribute("href");
          });
      });
    });
  }

  // ─── Bulk select bar ────────────────────────────────────────────
  function initBulkBar() {
    const form = document.querySelector("[data-bulk]");
    if (!form) return;
    const counter = form.querySelector("[data-bulk-count]");
    const all = document.getElementById("check-all");
    const checks = Array.from(document.querySelectorAll(".row-check"));

    function selectedIds() {
      const ids = [];
      document.querySelectorAll(".row-check.checked").forEach(function (el) {
        ids.push(el.getAttribute("data-id"));
      });
      return ids;
    }

    function refresh() {
      const ids = selectedIds();
      counter.textContent = String(ids.length);
      form.classList.toggle("on", ids.length > 0);
      checks.forEach(function (cb) {
        const checked = cb.classList.contains("checked");
        const row = cb.closest(".exp-row, .timeline-row");
        cb.setAttribute("aria-checked", checked ? "true" : "false");
        if (row) {
          row.classList.toggle("selected", checked);
          row.setAttribute("aria-selected", checked ? "true" : "false");
        }
      });
      // 同步隐藏 input
      form.querySelectorAll('input[name="expense_ids"]').forEach(function (n) { n.remove(); });
      ids.forEach(function (id) {
        const h = document.createElement("input");
        h.type = "hidden";
        h.name = "expense_ids";
        h.value = id;
        form.appendChild(h);
      });
      if (all) {
        const allChecked = checks.length > 0 && ids.length === checks.length;
        all.classList.toggle("checked", allChecked);
        all.setAttribute("aria-checked", allChecked ? "true" : (ids.length > 0 ? "mixed" : "false"));
      }
    }

    function bindCheckbox(el, handler) {
      el.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        handler();
      });
      el.addEventListener("keydown", function (e) {
        if (e.key !== " " && e.key !== "Enter") return;
        e.preventDefault();
        e.stopPropagation();
        handler();
      });
    }

    checks.forEach(function (cb) {
      bindCheckbox(cb, function () {
        cb.classList.toggle("checked");
        refresh();
      });
    });
    if (all) {
      bindCheckbox(all, function () {
        const turnOn = !all.classList.contains("checked");
        checks.forEach(function (cb) {
          cb.classList.toggle("checked", turnOn);
        });
        refresh();
      });
    }
    refresh();
  }

  // ─── Receipt image skeletons ───────────────────────────────────
  function initReceiptSkeletons(root) {
    (root || document).querySelectorAll("[data-image-skeleton]").forEach(function (box) {
      if (box.getAttribute("data-skeleton-bound") === "1") return;
      box.setAttribute("data-skeleton-bound", "1");
      const img = box.querySelector("img");
      if (!img) {
        box.classList.add("is-loaded");
        return;
      }
      const done = function () { box.classList.add("is-loaded"); };
      if (img.complete) {
        done();
        return;
      }
      img.addEventListener("load", done, { once: true });
      img.addEventListener("error", done, { once: true });
    });
  }

  // ─── Dashboard progressive data render ─────────────────────────
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function dashboardUrl(path, ledgerId, extra) {
    const params = new URLSearchParams(extra || {});
    if (ledgerId) params.set("ledger_id", ledgerId);
    const query = params.toString();
    return path + (query ? "?" + query : "");
  }

  function moneyParts(value) {
    const raw = String(value || "0.00");
    const parts = raw.split(".");
    return [parts[0] || "0", parts[1] || "00"];
  }

  function renderDashboardDelta(cards) {
    const direction = cards.delta_direction;
    if (!direction || direction === "none") return "";
    let label = "持平";
    if (direction === "up") {
      label = "↑ ¥" + escapeHtml(cards.delta_amount_yuan) +
        (cards.delta_percent != null ? " +" + escapeHtml(cards.delta_percent) + "%" : "");
    } else if (direction === "down") {
      label = "↓ ¥" + escapeHtml(cards.delta_amount_yuan) +
        (cards.delta_percent != null ? " -" + escapeHtml(cards.delta_percent) + "%" : "");
    }
    return '<div class="delta-pill-row" style="margin-top:8px">' +
      '<span class="delta-pill delta-' + escapeHtml(direction) + '">' + label + "</span>" +
      '<span class="delta-pill-prev">较上月 ¥' + escapeHtml(cards.previous_total_amount_yuan) + "</span>" +
      "</div>";
  }

  function renderPendingPills(cards) {
    const parts = [];
    if (cards.needs_amount_count) parts.push('<span class="dt-pill warn">缺金额 ' + escapeHtml(cards.needs_amount_count) + "</span>");
    if (cards.needs_merchant_count) parts.push('<span class="dt-pill warn">缺商家 ' + escapeHtml(cards.needs_merchant_count) + "</span>");
    if (cards.suspected_duplicate_count) parts.push('<span class="dt-pill danger">疑似重复 ' + escapeHtml(cards.suspected_duplicate_count) + "</span>");
    return parts.join("");
  }

  function renderSparkShell(points) {
    return '<svg class="spark" viewBox="0 0 280 56" width="100%" height="56" preserveAspectRatio="none" ' +
      'style="display:block;margin-top:14px;color:var(--text-default)" data-points=\'' +
      escapeHtml(JSON.stringify(points || [])) + "'>" +
      '<defs><linearGradient id="sparkArea" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="currentColor" stop-opacity="0.10"/>' +
      '<stop offset="100%" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs></svg>';
  }

  function renderCategoryRows(categoryShare) {
    if (!categoryShare || !categoryShare.length) {
      return '<div style="font-size:12.5px;color:var(--text-meta);padding:14px 0">本月还没有已确认账单。</div>';
    }
    const max = Math.max.apply(null, categoryShare.map(function (c) { return Number(c.amount_cents || 0); })) || 1;
    return categoryShare.map(function (c, index) {
      const width = Math.max(0, Number(c.amount_cents || 0) / max * 100);
      const color = index === 0 ? "var(--brand-primary)" : "var(--text-default)";
      const opacity = Math.max(0.4, 1 - index * 0.12);
      return '<div class="cat-row"><div class="cat-name">' + escapeHtml(c.name) + '</div>' +
        '<div class="cat-bar"><div class="cat-bar-fill" style="width:' + width.toFixed(2) +
        "%;background:" + color + ";opacity:" + opacity.toFixed(2) + '"></div></div>' +
        '<div class="cat-amt">¥' + escapeHtml(Math.round(Number(c.amount_yuan || 0))) + "</div></div>";
    }).join("");
  }

  function renderDashboardCard(item, data) {
    const cards = data.cards || {};
    const ledgerId = data.selected_ledger_id || "";
    const key = item.key;
    if (key === "pending") {
      return '<div class="col-4" data-dashboard-card="pending"><div class="dt-card">' +
        '<div class="card-head"><div><div class="card-title">待办</div><div class="card-sub" style="margin-top:4px">截图与草稿需要过目</div></div>' +
        '<a class="card-sub" href="' + dashboardUrl("/web/pending", ledgerId) + '" style="text-decoration:none">去处理 →</a></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px"><div>' +
        '<div class="trend-num">' + escapeHtml(cards.pending_count) + '</div>' +
        '<div style="font-size:12px;color:var(--text-meta);margin-top:6px">待确认账单</div>' +
        '<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">' + renderPendingPills(cards) + '</div></div>' +
        '<div style="border-left:1px solid var(--border-card);padding-left:14px"><div class="trend-num">' +
        escapeHtml(cards.confirmed_count) + '</div><div style="font-size:12px;color:var(--text-meta);margin-top:6px">本月已确认</div>' +
        '<div style="font-size:11.5px;color:var(--text-meta);margin-top:8px;line-height:1.6">目标 ' +
        escapeHtml(cards.goals_count) + ' 条' + (cards.goals_risk_count ? ' · 风险 ' + escapeHtml(cards.goals_risk_count) : "") +
        '<br>' + (cards.backup_available ? '最近备份 ' + escapeHtml(cards.backup_age_days) + " 天前" : "尚未生成备份") +
        "</div></div></div></div></div>";
    }
    if (key === "monthly_spend") {
      const parts = moneyParts(cards.total_amount_yuan);
      return '<div class="col-8" data-dashboard-card="monthly_spend"><div class="dt-card">' +
        '<div class="card-head"><div><div class="card-title">本月支出</div><div class="card-sub" style="margin-top:4px">' +
        escapeHtml(cards.month) + ' · 已确认</div></div><a class="card-sub" href="' +
        dashboardUrl("/web/reports", ledgerId, { month: cards.month || "" }) + '" style="text-decoration:none">报表 →</a></div>' +
        '<div class="kpi-amount"><span class="yuan">¥</span>' + escapeHtml(parts[0]) +
        '<span class="decimals">.' + escapeHtml(parts[1]) + '</span></div>' +
        renderDashboardDelta(cards) + renderSparkShell(data.trend14) +
        '<div class="trend-foot">' +
        (cards.budget_configured ? '<div>预算<span class="num">¥' + escapeHtml(cards.budget_total_yuan) + "</span></div>" : "") +
        (cards.budget_is_over ? '<div>超支<span class="num" style="color:var(--state-danger-fg)">¥' + escapeHtml(cards.budget_overspent_yuan) + "</span></div>" :
          (cards.budget_configured ? '<div>剩余<span class="num">¥' + escapeHtml(cards.budget_remaining_yuan) + "</span></div>" : "")) +
        '<div>笔数<span class="num">' + escapeHtml(cards.confirmed_count) + '</span></div>' +
        '<div>近 7 日上传<span class="num">' + escapeHtml(cards.recent_count) + '</span></div></div></div></div>';
    }
    if (key === "reports") {
      return '<div class="col-5" data-dashboard-card="reports"><div class="dt-card">' +
        '<div class="card-head"><div class="card-title">本月分类</div><a class="card-sub" href="' +
        dashboardUrl("/web/reports", ledgerId, { month: cards.month || "" }) + '" style="text-decoration:none">完整报表 →</a></div>' +
        '<div class="cat-list">' + renderCategoryRows(data.category_share || []) + '</div></div></div>';
    }
    if (key === "budget") {
      return '<div class="col-5" data-dashboard-card="budget"><div class="dt-card">' +
        '<div class="card-head"><div class="card-title">预算 · 本月</div><a class="card-sub" href="' +
        dashboardUrl("/web/budgets", ledgerId) + '" style="text-decoration:none">管理 →</a></div>' +
        (cards.budget_configured ?
          '<div><div class="budget-row"><div class="budget-label">总额</div><div class="budget-val">' +
          (cards.budget_is_over ? '<span style="color:var(--state-danger-fg)">¥' + escapeHtml(cards.budget_total_yuan) + '（超 ¥' + escapeHtml(cards.budget_overspent_yuan) + '）</span>' :
            '¥' + escapeHtml(cards.budget_total_yuan) + ' · 剩 ¥' + escapeHtml(cards.budget_remaining_yuan)) + "</div></div></div>" :
          '<div class="empty-state"><div class="empty-state__title">本月还没有预算</div><div class="empty-state__body">设个月度上限，超支会在卡片里给提示。</div><a class="empty-state__cta" href="' +
          dashboardUrl("/web/budgets", ledgerId) + '">去设置月度预算 →</a></div>') + "</div></div>";
    }
    if (key === "goals") {
      return '<div class="col-7" data-dashboard-card="goals"><div class="dt-card">' +
        '<div class="card-head"><div class="card-title">目标 · 月度</div><a class="card-sub" href="' +
        dashboardUrl("/web/goals", ledgerId) + '" style="text-decoration:none">新建 +</a></div>' +
        (Number(cards.goals_count || 0) === 0 ?
          '<div class="empty-state"><div class="empty-state__title">暂无目标</div><div class="empty-state__body">为某个分类设个月度上限，超过后会在这里提醒。</div><a class="empty-state__cta" href="' +
          dashboardUrl("/web/goals", ledgerId) + '">新建目标 →</a></div>' :
          '<div style="font-size:13px;color:var(--text-muted)">共 ' + escapeHtml(cards.goals_count) + ' 条目标' +
          (cards.goals_risk_count ? ' · <span class="dt-pill warn">' + escapeHtml(cards.goals_risk_count) + " 接近上限</span>" : "") + "。</div>") +
        "</div></div>";
    }
    if (key === "recurring") {
      return '<div class="col-4" data-dashboard-card="recurring"><div class="dt-card"><div class="card-head">' +
        '<div class="card-title">固定支出</div><a class="card-sub" href="' + dashboardUrl("/web/recurring", ledgerId) +
        '" style="text-decoration:none">管理 →</a></div><div class="trend-num">' + escapeHtml(cards.recurring_active_count) +
        '</div><div style="font-size:12px;color:var(--text-meta);margin-top:6px">正式固定支出' +
        (cards.recurring_paused_count ? ' · 暂停 ' + escapeHtml(cards.recurring_paused_count) : "") +
        (cards.recurring_candidate_count ? ' · ' + escapeHtml(cards.recurring_candidate_count) + " 个候选未确认" : "") +
        "</div></div></div>";
    }
    if (key === "recent_uploads") {
      return '<div class="col-4" data-dashboard-card="recent_uploads"><div class="dt-card"><div class="card-head">' +
        '<div class="card-title">最近 7 日上传</div><a class="card-sub" href="' + dashboardUrl("/web/pending", ledgerId) +
        '" style="text-decoration:none">查看 →</a></div><div class="trend-num">' + escapeHtml(cards.recent_count) +
        '</div><div style="font-size:12px;color:var(--text-meta);margin-top:6px">截图 / 手动新增</div></div></div>';
    }
    if (key === "backup_status") {
      return '<div class="col-4" data-dashboard-card="backup_status"><div class="dt-card"><div class="card-head">' +
        '<div class="card-title">备份状态</div><a class="card-sub" href="/owner/backups" style="text-decoration:none">打开 →</a></div>' +
        (cards.backup_available ? '<div class="trend-num">' + escapeHtml(cards.backup_age_days) +
          '</div><div style="font-size:12px;color:var(--text-meta);margin-top:6px">天前生成最近备份</div>' :
          '<div style="font-size:12.5px;color:var(--text-meta);padding:14px 0">尚未生成备份。</div>') + "</div></div>";
    }
    if (key === "device_status") {
      return '<div class="col-4" data-dashboard-card="device_status"><div class="dt-card"><div class="card-head">' +
        '<div class="card-title">设备状态</div><a class="card-sub" href="/owner/devices" style="text-decoration:none">管理 →</a></div>' +
        '<div class="trend-num">' + escapeHtml(cards.active_device_count) +
        '</div><div style="font-size:12px;color:var(--text-meta);margin-top:6px">当前账本有效设备</div></div></div>';
    }
    return "";
  }

  function renderDashboard(data) {
    const layout = data.visible_layout || ((data.cards && data.cards.layout) || []).filter(function (item) { return item.visible; });
    if (!layout.length) {
      return '<div class="dt-card" style="padding:48px 24px;text-align:center;color:var(--text-meta)">当前仪表盘没有可见卡片。可以在「仪表盘卡片」里重新启用。</div>';
    }
    return '<div class="dash-grid">' + layout.map(function (item) {
      return renderDashboardCard(item, data);
    }).join("") + "</div>";
  }

  function initDashboard() {
    const root = document.getElementById("dashboard-app");
    if (!root) return;
    const target = root.querySelector("[data-dashboard-rendered]");
    const url = root.getAttribute("data-dashboard-url");
    if (!target || !url || typeof fetch !== "function") {
      root.setAttribute("data-dashboard-state", "fallback");
      return;
    }
    fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("dashboard data failed");
        return res.json();
      })
      .then(function (data) {
        target.innerHTML = renderDashboard(data);
        root.setAttribute("data-dashboard-state", "ready");
        initSparks(target);
      })
      .catch(function () {
        root.setAttribute("data-dashboard-state", "fallback");
      });
  }

  // ─── ECharts: monthly trend (bar + budget dash + smooth line) ──
  function readVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function initTrendChart() {
    const el = document.getElementById("chart-trend");
    if (!el || typeof echarts === "undefined") return;
    let series;
    try { series = JSON.parse(el.getAttribute("data-series") || "[]"); } catch (_) { return; }
    if (!series.length) return;

    const chart = echarts.init(el, null, { renderer: "canvas" });
    function build() {
      const labels = series.map(function (s) { return s.month.slice(5) + "月"; });
      const amounts = series.map(function (s) { return Math.round(s.amount_yuan); });
      const budgets = series.map(function (s) { return Math.round(s.budget_yuan); });
      const ink = readVar("--text-default");
      const ink3 = readVar("--text-meta");
      const ink4 = readVar("--text-faint");
      const accent = readVar("--brand-primary");
      const hairline = readVar("--border-card");
      return {
        animation: false,
        grid: { left: 12, right: 12, top: 16, bottom: 28, containLabel: true },
        tooltip: {
          trigger: "axis",
          backgroundColor: readVar("--chart-tooltip-bg"),
          borderColor: readVar("--chart-tooltip-border"),
          textStyle: { color: readVar("--chart-tooltip-fg"), fontFamily: "Inter, 'Noto Sans SC'" },
          axisPointer: { lineStyle: { color: ink4, type: "dashed" } },
          formatter: function (params) {
            const head = '<div style="font-size:11px;letter-spacing:.1em;color:' + ink3 + ';margin-bottom:4px">' +
                         params[0].axisValue + "</div>";
            return head + params.map(function (p) {
              return '<div style="display:flex;justify-content:space-between;gap:14px;font-size:12px">' +
                '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
                p.color + ';margin-right:6px;vertical-align:1px"></span>' + p.seriesName + "</span>" +
                '<b style="font-variant-numeric:tabular-nums">¥' +
                (p.value || 0).toLocaleString() + "</b></div>";
            }).join("");
          },
        },
        legend: { show: false },
        xAxis: {
          type: "category",
          data: labels,
          axisLine: { lineStyle: { color: hairline } },
          axisTick: { show: false },
          axisLabel: { color: ink3, fontFamily: "Inter, 'Noto Sans SC'", fontSize: 11 },
        },
        yAxis: {
          type: "value",
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: hairline } },
          axisLabel: {
            color: ink4, fontFamily: "Inter", fontSize: 11,
            formatter: function (v) { return v >= 1000 ? (v / 1000) + "k" : v; },
          },
        },
        series: [
          {
            name: "预算", type: "line", data: budgets,
            smooth: false, symbol: "none",
            lineStyle: { color: ink4, width: 1, type: "dashed" }, z: 1,
          },
          {
            name: "支出", type: "bar", data: amounts, barWidth: 22,
            itemStyle: {
              color: function (params) {
                const i = params.dataIndex;
                return budgets[i] && amounts[i] > budgets[i] ? readVar("--state-danger-fg") : ink;
              },
              borderRadius: [2, 2, 0, 0],
            },
            z: 2,
          },
          {
            name: "趋势", type: "line", data: amounts,
            smooth: 0.3, symbol: "circle", symbolSize: 5, showSymbol: true,
            lineStyle: { color: accent, width: 1.4 },
            itemStyle: { color: accent, borderColor: readVar("--surface-card"), borderWidth: 1.5 },
            z: 3,
          },
        ],
      };
    }
    chart.setOption(build());
    new ResizeObserver(function () { chart.resize(); }).observe(el);
  }

  function initCategoryDonut() {
    const el = document.getElementById("chart-category");
    if (!el || typeof echarts === "undefined") return;
    let data;
    try { data = JSON.parse(el.getAttribute("data-categories") || "[]"); } catch (_) { return; }
    if (!data.length) return;

    const chart = echarts.init(el, null, { renderer: "canvas" });
    function build() {
      const palette = [
        readVar("--chart-series-1"),
        readVar("--chart-series-2"),
        readVar("--chart-series-3"),
        readVar("--chart-series-4"),
        readVar("--chart-series-5"),
        readVar("--chart-series-6"),
      ];
      const ink = readVar("--text-default");
      const ink2 = readVar("--text-muted");
      const ink3 = readVar("--text-meta");
      return {
        animation: false,
        tooltip: {
          trigger: "item",
          backgroundColor: readVar("--chart-tooltip-bg"),
          borderColor: readVar("--chart-tooltip-border"),
          textStyle: { color: readVar("--chart-tooltip-fg"), fontFamily: "'Noto Sans SC', Inter" },
          formatter: function (p) {
            return '<div style="font-size:12px"><b>' + p.name + "</b><br/>¥" +
                   (p.value || 0).toLocaleString() + " · " + p.percent + "%</div>";
          },
        },
        legend: { show: false },
        series: [{
          type: "pie",
          radius: ["62%", "85%"],
          center: ["50%", "55%"],
          avoidLabelOverlap: false,
          itemStyle: { borderColor: readVar("--surface-card"), borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: {
            scale: true, scaleSize: 4,
            label: {
              show: true, position: "center", color: ink,
              fontFamily: "Newsreader, 'Source Han Serif SC', serif", fontSize: 22,
              formatter: function (p) {
                return "{n|" + p.name + "}\n{v|¥" + Math.round(p.value || 0).toLocaleString() +
                       "}\n{p|" + p.percent + "%}";
              },
              rich: {
                n: { color: ink2, fontSize: 12, fontFamily: "'Noto Sans SC', Inter", lineHeight: 18, fontWeight: 500 },
                v: { color: ink, fontSize: 22, fontFamily: "Newsreader, serif", lineHeight: 28 },
                p: { color: ink3, fontSize: 11, fontFamily: "Inter", lineHeight: 16 },
              },
            },
          },
          data: data.slice(0, 6).map(function (d, i) {
            return {
              name: d.category,
              value: d.amount_cents,
              itemStyle: { color: palette[i % palette.length] },
            };
          }),
        }],
        graphic: {
          type: "text", left: "center", top: "44%",
          style: { text: "合计", fill: ink3, fontFamily: "'Noto Sans SC', Inter", fontSize: 11 },
          z: 0,
        },
      };
    }
    chart.setOption(build());
    new ResizeObserver(function () { chart.resize(); }).observe(el);

    // 把环图 legend dots 的颜色也按 chart-series 涂上
    document.querySelectorAll(".chart-legend-0").forEach(function (n) { n.style.background = readVar("--chart-series-1"); });
    document.querySelectorAll(".chart-legend-1").forEach(function (n) { n.style.background = readVar("--chart-series-2"); });
    document.querySelectorAll(".chart-legend-2").forEach(function (n) { n.style.background = readVar("--chart-series-3"); });
    document.querySelectorAll(".chart-legend-3").forEach(function (n) { n.style.background = readVar("--chart-series-4"); });
    document.querySelectorAll(".chart-legend-4").forEach(function (n) { n.style.background = readVar("--chart-series-5"); });
    document.querySelectorAll(".chart-legend-5").forEach(function (n) { n.style.background = readVar("--chart-series-6"); });
  }

  // ─── Bootstrap ─────────────────────────────────────────────────
  function boot() {
    // 启动时先把 cookie / localStorage 与 <html data-theme> 对齐（防止刷新闪烁）
    let saved = null;
    try { saved = localStorage.getItem("ui-theme"); } catch (_) {}
    if (saved && THEMES.includes(saved)) {
      const current = document.documentElement.getAttribute("data-theme");
      if (current !== saved) document.documentElement.setAttribute("data-theme", saved);
    }
    initThemeToggle();
    initLedgerSwitcher();
    initSparks();
    initDrawer();
    initBulkBar();
    initReceiptSkeletons();
    initDashboard();
    initTrendChart();
    initCategoryDonut();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
