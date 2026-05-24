/* Dashboard progressive data render. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};
  const dashboardUrl = app.dashboardUrl;
  const homeCurrencySymbol = app.homeCurrencySymbol;
  const moneyParts = app.moneyParts;

  function text(value) {
    return String(value == null ? "" : value);
  }

  function money(value) {
    return homeCurrencySymbol() + text(value);
  }

  function moneyRounded(value) {
    return homeCurrencySymbol() + Math.round(Number(value || 0));
  }

  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = text(content);
    return node;
  }

  function styled(node, cssText) {
    node.setAttribute("style", cssText);
    return node;
  }

  function append(parent) {
    for (let index = 1; index < arguments.length; index += 1) {
      const child = arguments[index];
      if (child == null) continue;
      if (Array.isArray(child)) {
        child.forEach(function (item) { append(parent, item); });
      } else if (typeof child === "string" || typeof child === "number") {
        parent.appendChild(document.createTextNode(text(child)));
      } else {
        parent.appendChild(child);
      }
    }
    return parent;
  }

  function link(className, href, label) {
    const anchor = el("a", className, label);
    anchor.setAttribute("href", href);
    anchor.style.textDecoration = "none";
    return anchor;
  }

  function cardShell(columnClass, key) {
    const outer = el("div", columnClass);
    outer.setAttribute("data-dashboard-card", key);
    const card = el("div", "dt-card");
    outer.appendChild(card);
    return { outer: outer, card: card };
  }

  function cardHead(title, subtitle, action) {
    const head = el("div", "card-head");
    const titleWrap = el("div");
    append(titleWrap, el("div", "card-title", title));
    if (subtitle) {
      append(titleWrap, styled(el("div", "card-sub", subtitle), "margin-top:4px"));
    }
    append(head, titleWrap);
    if (action) append(head, action);
    return head;
  }

  function pill(className, label) {
    return el("span", className, label);
  }

  function emptyState(title, body, href, cta) {
    const node = el("div", "empty-state");
    append(
      node,
      el("div", "empty-state__title", title),
      el("div", "empty-state__body", body),
      link("empty-state__cta", href, cta)
    );
    return node;
  }

  function renderDashboardDelta(cards) {
    const direction = cards.delta_direction;
    if (!direction || direction === "none") return null;
    const row = styled(el("div", "delta-pill-row"), "margin-top:8px");
    let label = "持平";
    let directionClass = "delta-none";
    if (direction === "up") {
      directionClass = "delta-up";
      label = "↑ " + money(cards.delta_amount_yuan) +
        (cards.delta_percent != null ? " +" + text(cards.delta_percent) + "%" : "");
    } else if (direction === "down") {
      directionClass = "delta-down";
      label = "↓ " + money(cards.delta_amount_yuan) +
        (cards.delta_percent != null ? " -" + text(cards.delta_percent) + "%" : "");
    }
    append(
      row,
      pill("delta-pill " + directionClass, label),
      pill("delta-pill-prev", "较上月 " + money(cards.previous_total_amount_yuan))
    );
    return row;
  }

  function renderPendingPills(cards) {
    const row = styled(el("div"), "display:flex;gap:6px;margin-top:8px;flex-wrap:wrap");
    if (cards.needs_amount_count) append(row, pill("dt-pill warn", "缺金额 " + text(cards.needs_amount_count)));
    if (cards.needs_merchant_count) append(row, pill("dt-pill warn", "缺商家 " + text(cards.needs_merchant_count)));
    if (cards.suspected_duplicate_count) append(row, pill("dt-pill danger", "疑似重复 " + text(cards.suspected_duplicate_count)));
    return row;
  }

  function renderSparkShell(points) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "spark");
    svg.setAttribute("viewBox", "0 0 280 56");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "56");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("style", "display:block;margin-top:14px;color:var(--text-default)");
    svg.setAttribute("data-points", JSON.stringify(points || []));
    const defs = document.createElementNS(ns, "defs");
    const gradient = document.createElementNS(ns, "linearGradient");
    gradient.setAttribute("id", "sparkArea");
    gradient.setAttribute("x1", "0");
    gradient.setAttribute("y1", "0");
    gradient.setAttribute("x2", "0");
    gradient.setAttribute("y2", "1");
    const start = document.createElementNS(ns, "stop");
    start.setAttribute("offset", "0%");
    start.setAttribute("stop-color", "currentColor");
    start.setAttribute("stop-opacity", "0.10");
    const end = document.createElementNS(ns, "stop");
    end.setAttribute("offset", "100%");
    end.setAttribute("stop-color", "currentColor");
    end.setAttribute("stop-opacity", "0");
    append(gradient, start, end);
    append(defs, gradient);
    append(svg, defs);
    return svg;
  }

  function renderCategoryRows(categoryShare) {
    const list = el("div", "cat-list");
    if (!categoryShare || !categoryShare.length) {
      append(list, styled(el("div", "", "本月还没有已确认账单。"), "font-size:12.5px;color:var(--text-meta);padding:14px 0"));
      return list;
    }
    const max = Math.max.apply(null, categoryShare.map(function (c) { return Number(c.amount_cents || 0); })) || 1;
    categoryShare.forEach(function (c, index) {
      const width = Math.max(0, Number(c.amount_cents || 0) / max * 100);
      const color = index === 0 ? "var(--brand-primary)" : "var(--text-default)";
      const opacity = Math.max(0.4, 1 - index * 0.12);
      const row = el("div", "cat-row");
      const bar = el("div", "cat-bar");
      append(
        row,
        el("div", "cat-name", c.name),
        append(
          bar,
          styled(el("div", "cat-bar-fill"), "width:" + width.toFixed(2) + "%;background:" + color + ";opacity:" + opacity.toFixed(2))
        ),
        el("div", "cat-amt", moneyRounded(c.amount_yuan))
      );
      append(list, row);
    });
    return list;
  }

  function renderPendingCard(cards, ledgerId) {
    const shell = cardShell("col-4", "pending");
    append(shell.card, cardHead(
      "待办",
      "截图与草稿需要过目",
      link("card-sub", dashboardUrl("/web/pending", ledgerId), "去处理 →")
    ));
    const grid = styled(el("div"), "display:grid;grid-template-columns:1fr 1fr;gap:14px");
    const left = el("div");
    append(
      left,
      el("div", "trend-num", cards.pending_count),
      styled(el("div", "", "待确认账单"), "font-size:12px;color:var(--text-meta);margin-top:6px"),
      renderPendingPills(cards)
    );
    const right = styled(el("div"), "border-left:1px solid var(--border-card);padding-left:14px");
    const meta = styled(el("div"), "font-size:11.5px;color:var(--text-meta);margin-top:8px;line-height:1.6");
    append(meta, "目标 " + text(cards.goals_count) + " 条");
    if (cards.goals_risk_count) append(meta, " · 风险 " + text(cards.goals_risk_count));
    append(meta, document.createElement("br"), cards.backup_available ? "最近备份 " + text(cards.backup_age_days) + " 天前" : "尚未生成备份");
    append(
      right,
      el("div", "trend-num", cards.confirmed_count),
      styled(el("div", "", "本月已确认"), "font-size:12px;color:var(--text-meta);margin-top:6px"),
      meta
    );
    append(shell.card, append(grid, left, right));
    return shell.outer;
  }

  function renderMonthlySpendCard(cards, data, ledgerId) {
    const shell = cardShell("col-8", "monthly_spend");
    append(shell.card, cardHead(
      "本月支出",
      text(cards.month) + " · 已确认",
      link("card-sub", dashboardUrl("/web/reports", ledgerId, { month: cards.month || "" }), "报表 →")
    ));
    const parts = moneyParts(cards.total_amount_yuan);
    const amount = el("div", "kpi-amount");
    append(amount, el("span", "yuan", homeCurrencySymbol()), text(parts[0]), el("span", "decimals", "." + text(parts[1])));
    const foot = el("div", "trend-foot");
    if (cards.budget_configured) {
      append(foot, append(el("div"), "预算", el("span", "num", money(cards.budget_total_yuan))));
      if (cards.budget_is_over) {
        const overspent = el("span", "num", money(cards.budget_overspent_yuan));
        overspent.style.color = "var(--state-danger-fg)";
        append(foot, append(el("div"), "超支", overspent));
      } else {
        append(foot, append(el("div"), "剩余", el("span", "num", money(cards.budget_remaining_yuan))));
      }
    }
    append(
      foot,
      append(el("div"), "笔数", el("span", "num", cards.confirmed_count)),
      append(el("div"), "近 7 日上传", el("span", "num", cards.recent_count))
    );
    append(shell.card, amount, renderDashboardDelta(cards), renderSparkShell(data.trend14), foot);
    return shell.outer;
  }

  function renderReportsCard(data, cards, ledgerId) {
    const shell = cardShell("col-5", "reports");
    append(shell.card, cardHead(
      "本月分类",
      "",
      link("card-sub", dashboardUrl("/web/reports", ledgerId, { month: cards.month || "" }), "完整报表 →")
    ));
    append(shell.card, renderCategoryRows(data.category_share || []));
    return shell.outer;
  }

  function renderBudgetCard(cards, ledgerId) {
    const shell = cardShell("col-5", "budget");
    append(shell.card, cardHead(
      "预算 · 本月",
      "",
      link("card-sub", dashboardUrl("/web/budgets", ledgerId), "管理 →")
    ));
    if (cards.budget_configured) {
      const row = el("div", "budget-row");
      const value = el("div", "budget-val");
      if (cards.budget_is_over) {
        const warning = el("span", "", money(cards.budget_total_yuan) + "（超 " + money(cards.budget_overspent_yuan) + "）");
        warning.style.color = "var(--state-danger-fg)";
        append(value, warning);
      } else {
        value.textContent = money(cards.budget_total_yuan) + " · 剩 " + money(cards.budget_remaining_yuan);
      }
      append(shell.card, append(el("div"), append(row, el("div", "budget-label", "总额"), value)));
    } else {
      append(shell.card, emptyState(
        "本月还没有预算",
        "设个月度上限，超支会在卡片里给提示。",
        dashboardUrl("/web/budgets", ledgerId),
        "去设置月度预算 →"
      ));
    }
    return shell.outer;
  }

  function renderGoalsCard(cards, ledgerId) {
    const shell = cardShell("col-7", "goals");
    append(shell.card, cardHead(
      "目标 · 月度",
      "",
      link("card-sub", dashboardUrl("/web/goals", ledgerId), "新建 +")
    ));
    if (Number(cards.goals_count || 0) === 0) {
      append(shell.card, emptyState(
        "暂无目标",
        "为某个分类设个月度上限，超过后会在这里提醒。",
        dashboardUrl("/web/goals", ledgerId),
        "新建目标 →"
      ));
    } else {
      const body = styled(el("div"), "font-size:13px;color:var(--text-muted)");
      append(body, "共 " + text(cards.goals_count) + " 条目标");
      if (cards.goals_risk_count) append(body, " · ", pill("dt-pill warn", text(cards.goals_risk_count) + " 接近上限"));
      append(body, "。");
      append(shell.card, body);
    }
    return shell.outer;
  }

  function renderSimpleCountCard(key, title, href, actionText, count, bodyText) {
    const shell = cardShell("col-4", key);
    append(shell.card, cardHead(title, "", link("card-sub", href, actionText)));
    append(
      shell.card,
      el("div", "trend-num", count),
      styled(el("div", "", bodyText), "font-size:12px;color:var(--text-meta);margin-top:6px")
    );
    return shell.outer;
  }

  function renderDashboardCard(item, data) {
    const cards = data.cards || {};
    const ledgerId = data.selected_ledger_id || "";
    const key = item.key;
    if (key === "pending") return renderPendingCard(cards, ledgerId);
    if (key === "monthly_spend") return renderMonthlySpendCard(cards, data, ledgerId);
    if (key === "reports") return renderReportsCard(data, cards, ledgerId);
    if (key === "budget") return renderBudgetCard(cards, ledgerId);
    if (key === "goals") return renderGoalsCard(cards, ledgerId);
    if (key === "recurring") {
      let body = "正式固定支出";
      if (cards.recurring_paused_count) body += " · 暂停 " + text(cards.recurring_paused_count);
      if (cards.recurring_candidate_count) body += " · " + text(cards.recurring_candidate_count) + " 个候选未确认";
      return renderSimpleCountCard("recurring", "固定支出", dashboardUrl("/web/recurring", ledgerId), "管理 →", cards.recurring_active_count, body);
    }
    if (key === "recent_uploads") {
      return renderSimpleCountCard("recent_uploads", "最近 7 日上传", dashboardUrl("/web/pending", ledgerId), "查看 →", cards.recent_count, "截图 / 手动新增");
    }
    if (key === "backup_status") {
      const shell = cardShell("col-4", "backup_status");
      append(shell.card, cardHead("备份状态", "", link("card-sub", "/owner/backups", "打开 →")));
      if (cards.backup_available) {
        append(
          shell.card,
          el("div", "trend-num", cards.backup_age_days),
          styled(el("div", "", "天前生成最近备份"), "font-size:12px;color:var(--text-meta);margin-top:6px")
        );
      } else {
        append(shell.card, styled(el("div", "", "尚未生成备份。"), "font-size:12.5px;color:var(--text-meta);padding:14px 0"));
      }
      return shell.outer;
    }
    if (key === "device_status") {
      return renderSimpleCountCard("device_status", "设备状态", "/owner/devices", "管理 →", cards.active_device_count, "当前账本有效设备");
    }
    return null;
  }

  function renderDashboard(data) {
    const layout = data.visible_layout || ((data.cards && data.cards.layout) || []).filter(function (item) { return item.visible; });
    if (!layout.length) {
      return styled(el("div", "dt-card", "当前仪表盘没有可见卡片。可以在「仪表盘卡片」里重新启用。"), "padding:48px 24px;text-align:center;color:var(--text-meta)");
    }
    const grid = el("div", "dash-grid");
    layout.forEach(function (item) { append(grid, renderDashboardCard(item, data)); });
    return grid;
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
        target.replaceChildren(renderDashboard(data));
        root.setAttribute("data-dashboard-state", "ready");
        if (typeof app.initSparks === "function") app.initSparks(target);
      })
      .catch(function () {
        root.setAttribute("data-dashboard-state", "fallback");
      });
  };
})(window, document);
