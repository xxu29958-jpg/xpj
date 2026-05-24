/* Dashboard progressive data render. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};
  const escapeHtml = app.escapeHtml;
  const dashboardUrl = app.dashboardUrl;
  const homeCurrencySymbol = app.homeCurrencySymbol;
  const homeMoney = app.homeMoney;
  const homeMoneyRounded = app.homeMoneyRounded;
  const moneyParts = app.moneyParts;

  function renderDashboardDelta(cards) {
    const direction = cards.delta_direction;
    if (!direction || direction === "none") return "";
    let label = "持平";
    if (direction === "up") {
      label = "↑ " + homeMoney(cards.delta_amount_yuan) +
        (cards.delta_percent != null ? " +" + escapeHtml(cards.delta_percent) + "%" : "");
    } else if (direction === "down") {
      label = "↓ " + homeMoney(cards.delta_amount_yuan) +
        (cards.delta_percent != null ? " -" + escapeHtml(cards.delta_percent) + "%" : "");
    }
    return '<div class="delta-pill-row" style="margin-top:8px">' +
      '<span class="delta-pill delta-' + escapeHtml(direction) + '">' + label + "</span>" +
      '<span class="delta-pill-prev">较上月 ' + homeMoney(cards.previous_total_amount_yuan) + "</span>" +
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
        '<div class="cat-amt">' + homeMoneyRounded(c.amount_yuan) + "</div></div>";
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
        '<div class="kpi-amount"><span class="yuan">' + escapeHtml(homeCurrencySymbol()) + '</span>' + escapeHtml(parts[0]) +
        '<span class="decimals">.' + escapeHtml(parts[1]) + '</span></div>' +
        renderDashboardDelta(cards) + renderSparkShell(data.trend14) +
        '<div class="trend-foot">' +
        (cards.budget_configured ? '<div>预算<span class="num">' + homeMoney(cards.budget_total_yuan) + "</span></div>" : "") +
        (cards.budget_is_over ? '<div>超支<span class="num" style="color:var(--state-danger-fg)">' + homeMoney(cards.budget_overspent_yuan) + "</span></div>" :
          (cards.budget_configured ? '<div>剩余<span class="num">' + homeMoney(cards.budget_remaining_yuan) + "</span></div>" : "")) +
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
          (cards.budget_is_over ? '<span style="color:var(--state-danger-fg)">' + homeMoney(cards.budget_total_yuan) + '（超 ' + homeMoney(cards.budget_overspent_yuan) + '）</span>' :
            homeMoney(cards.budget_total_yuan) + ' · 剩 ' + homeMoney(cards.budget_remaining_yuan)) + "</div></div></div>" :
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

  app.renderDashboard = renderDashboard;

  app.initDashboard = function initDashboard() {
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
        if (typeof app.initSparks === "function") app.initSparks(target);
      })
      .catch(function () {
        root.setAttribute("data-dashboard-state", "fallback");
      });
  };
})(window, document);
