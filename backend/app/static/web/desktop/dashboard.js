/* Insights overview: server-first refresh using the product DOM vocabulary. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};
  const dashboardUrl = app.dashboardUrl;
  const homeCurrencySymbol = app.homeCurrencySymbol;
  const SLOW_LOAD_MS = 2000;
  const FALLBACK_LOAD_MS = 8000;
  const DASHBOARD_LANES = [
    {
      title: "需处理",
      summary: "优先处理会影响账面可信度的记录",
      keys: ["pending", "recent_uploads"],
    },
    {
      title: "本月事实",
      summary: "已入账金额、结构与基础状态",
      keys: ["monthly_spend", "reports", "backup_status", "device_status"],
    },
    {
      title: "计划状态",
      summary: "预算、目标和固定支出的执行情况",
      keys: ["budget", "goals", "recurring"],
    },
  ];

  function text(value) {
    return String(value == null ? "" : value);
  }

  function money(value) {
    return homeCurrencySymbol() + text(value);
  }

  function el(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = text(content);
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
    return anchor;
  }

  function panel(key, extraClass) {
    const article = el(
      "article",
      "product-panel product-panel--padded " + (extraClass || "")
    );
    article.setAttribute("data-dashboard-card", key);
    return article;
  }

  function panelHeader(title, subtitle, href, actionLabel) {
    const header = el("div", "product-panel-header");
    const copy = el("div");
    append(copy, el("div", "product-panel-title", title));
    if (subtitle) append(copy, el("div", "product-panel-subtitle", subtitle));
    append(header, copy);
    if (href && actionLabel) {
      append(header, link("product-panel-subtitle", href, actionLabel));
    }
    return header;
  }

  function statusPill(label, tone) {
    const toneClass = tone ? " product-status--" + tone : "";
    return el("span", "product-status" + toneClass, label);
  }

  function productState(title, body, href, actionLabel, compact) {
    const state = el(
      "div",
      "product-state" + (compact ? " product-state--compact" : "")
    );
    append(
      state,
      el("div", "product-state-title", title),
      el("div", "product-state-body", body)
    );
    if (href && actionLabel) {
      append(state, link("product-state-action", href, actionLabel));
    }
    return state;
  }

  function renderOnboarding(ledgerId) {
    const state = productState(
      "先录入第一笔流水",
      "整理一笔新账单或导入历史记录后，月度支出、分类结构和预算执行会在这里出现。",
      null,
      null,
      false
    );
    state.classList.add("insight-onboarding");
    state.setAttribute("aria-label", "开始记录");
    const actions = el("div", "cluster");
    append(
      actions,
      link("product-state-action", dashboardUrl("/web/pending", ledgerId), "前往待我处理"),
      link("product-state-action", dashboardUrl("/web/import", ledgerId), "导入历史记录")
    );
    append(state, actions);
    return state;
  }

  function renderProgressList(rows, kind) {
    const list = el("div", "insight-progress-list");
    rows.forEach(function (item) {
      const row = el("div", "insight-progress-row");
      const meta = el("div", "insight-progress-meta");
      let valueLabel = text(item.percent) + "%";
      let valueClass = "num";
      if (kind === "budget" && item.is_over) {
        valueLabel = "超 " + money(item.overspent_yuan);
        valueClass += " text-danger";
      }
      if (kind === "goal" && item.state === "over_limit") {
        valueClass += " text-danger";
      }
      const progress = el("progress", "product-progress");
      progress.setAttribute("max", "100");
      progress.setAttribute("value", text(item.percent || 0));
      progress.setAttribute(
        "aria-label",
        text(item.name) + (kind === "budget" ? "预算已使用 " : "已使用 ") +
          text(item.percent || 0) + "%"
      );
      append(meta, el("span", "", item.name), el("strong", valueClass, valueLabel));
      append(row, meta, progress);
      append(list, row);
    });
    return list;
  }

  function renderMonthlySpend(cards, ledgerId) {
    const article = panel("monthly_spend", "insight-hero is-wide");
    const header = el("div", "product-panel-header");
    const copy = el("div");
    append(
      copy,
      el("div", "product-eyebrow", "本月支出"),
      el("div", "product-panel-subtitle", text(cards.month) + " · 已入账")
    );
    append(
      header,
      copy,
      link(
        "product-panel-subtitle",
        dashboardUrl("/web/confirmed", ledgerId, { month: cards.month || "" }),
        "查看流水"
      )
    );

    const value = el("div", "insight-hero-value");
    append(value, el("small", "", homeCurrencySymbol()), text(cards.total_amount_yuan));

    const foot = el("div", "insight-module-foot");
    if (cards.delta_direction && cards.delta_direction !== "none") {
      const increased = cards.delta_direction === "up";
      const deltaLabel = increased
        ? "比上月多 " + money(cards.delta_amount_yuan)
        : "比上月少 " + money(cards.delta_amount_yuan);
      append(foot, statusPill(deltaLabel, increased ? "warning" : "success"));
    }
    append(
      foot,
      el("span", "text-meta", "上月 " + money(cards.previous_total_amount_yuan))
    );
    return append(article, header, value, foot);
  }

  function renderPending(cards, ledgerId) {
    const article = panel("pending", "insight-stat");
    const copy = el("div");
    append(
      copy,
      el("div", "product-panel-title", "待整理"),
      el("div", "product-panel-subtitle", "需要进入账面的新记录")
    );
    const pills = el("div", "pill-row");
    if (cards.needs_amount_count) {
      append(pills, statusPill("缺金额 " + text(cards.needs_amount_count), "warning"));
    }
    if (cards.needs_merchant_count) {
      append(pills, statusPill("缺商家 " + text(cards.needs_merchant_count), "warning"));
    }
    if (cards.suspected_duplicate_count) {
      append(
        pills,
        statusPill("重复风险 " + text(cards.suspected_duplicate_count), "danger")
      );
    }
    return append(
      article,
      copy,
      el("div", "insight-stat-value num", cards.pending_count),
      pills,
      link("product-panel-subtitle", dashboardUrl("/web/pending", ledgerId), "去处理")
    );
  }

  function renderBudget(cards, ledgerId) {
    const article = panel("budget", "insight-module");
    append(
      article,
      panelHeader(
        "预算余量",
        cards.month,
        dashboardUrl("/web/budgets", ledgerId),
        "管理"
      )
    );
    if (!cards.budget_configured) {
      append(
        article,
        productState(
          "还没有预算基线",
          "设置本月总额后，概览会持续显示余量和超支。",
          null,
          null,
          true
        )
      );
      return article;
    }

    const value = cards.budget_is_over
      ? "-" + money(cards.budget_overspent_yuan)
      : money(cards.budget_remaining_yuan);
    append(
      article,
      el(
        "div",
        "insight-stat-value num" + (cards.budget_is_over ? " text-danger" : ""),
        value
      ),
      statusPill(cards.budget_is_over ? "已超支" : "仍可使用", cards.budget_is_over ? "danger" : "success")
    );
    if (cards.budget_top && cards.budget_top.length) {
      append(article, renderProgressList(cards.budget_top, "budget"));
    }
    return article;
  }

  function renderReports(data, cards, ledgerId) {
    const article = panel("reports", "insight-module is-wide");
    append(
      article,
      panelHeader(
        "分类结构",
        "本月已入账支出的主要去向",
        dashboardUrl("/web/reports", ledgerId, { month: cards.month || "" }),
        "完整分析"
      )
    );
    const categories = data.category_share || [];
    if (!categories.length) {
      append(
        article,
        productState(
          "还没有分类结构",
          "有流水入账并完成分类后，这里会显示主要支出去向。",
          null,
          null,
          true
        )
      );
      return article;
    }

    const layout = el("div", "insight-category-layout");
    const chart = el("div", "insight-category-chart");
    chart.id = "chart-category";
    chart.setAttribute("data-categories", JSON.stringify(categories));
    chart.setAttribute("role", "img");
    chart.setAttribute("aria-label", "本月分类支出占比");

    const list = el("div", "insight-list");
    categories.forEach(function (category) {
      const row = el("div", "insight-list-row");
      append(
        row,
        el("span", "", category.name),
        el(
          "strong",
          "cat-amt",
          money(
            category.amount_value == null
              ? app.homeMajorNumber(category.amount_major == null ? category.amount_yuan : category.amount_major)
              : category.amount_value
          )
        )
      );
      append(list, row);
    });
    append(layout, chart, list);
    return append(article, layout);
  }

  function renderGoals(cards, ledgerId) {
    const article = panel("goals", "insight-module");
    append(
      article,
      panelHeader(
        "目标",
        text(cards.goals_count) + " 条生效中",
        dashboardUrl("/web/goals", ledgerId),
        "管理"
      )
    );
    if (Number(cards.goals_count || 0) === 0) {
      append(article, el("div", "text-muted", "还没有设置分类目标。"));
    } else if (cards.goals_top && cards.goals_top.length) {
      append(article, renderProgressList(cards.goals_top, "goal"));
    }
    return article;
  }

  function renderCountModule(key, title, subtitle, count, body, href, actionLabel) {
    const article = panel(key, "insight-module");
    if (href) {
      append(article, panelHeader(title, subtitle, href, actionLabel));
    } else {
      append(article, el("div", "product-panel-title", title));
    }
    append(article, el("div", "trend-num", count), el("div", "text-muted", body));
    return article;
  }

  function renderDashboardCard(item, data) {
    const cards = data.cards || {};
    const ledgerId = data.selected_ledger_id || "";
    switch (item.key) {
      case "monthly_spend":
        return renderMonthlySpend(cards, ledgerId);
      case "pending":
        return renderPending(cards, ledgerId);
      case "budget":
        return renderBudget(cards, ledgerId);
      case "reports":
        return renderReports(data, cards, ledgerId);
      case "goals":
        return renderGoals(cards, ledgerId);
      case "recurring": {
        let body = text(cards.recurring_candidate_count) + " 个候选待确认";
        if (cards.recurring_paused_count) {
          body = "暂停 " + text(cards.recurring_paused_count) + " 条 · " + body;
        }
        return renderCountModule(
          "recurring",
          "固定支出",
          "正式计划",
          cards.recurring_active_count,
          body,
          dashboardUrl("/web/recurring", ledgerId),
          "管理"
        );
      }
      case "recent_uploads":
        return renderCountModule(
          "recent_uploads",
          "最近新增",
          "过去 7 天",
          cards.recent_count,
          "截图、手动记账与导入",
          dashboardUrl("/web/pending", ledgerId),
          "查看"
        );
      case "backup_status":
        if (cards.backup_available) {
          return renderCountModule(
            "backup_status",
            "备份状态",
            "",
            cards.backup_age_days,
            "天前生成最近备份",
            null,
            null
          );
        }
        return append(
          panel("backup_status", "insight-module"),
          el("div", "product-panel-title", "备份状态"),
          statusPill("还没有备份", "warning")
        );
      case "device_status":
        return renderCountModule(
          "device_status",
          "连接设备",
          "",
          cards.active_device_count,
          "当前账本有效设备",
          null,
          null
        );
      default:
        return null;
    }
  }

  function renderDashboard(data) {
    const fragment = document.createDocumentFragment();
    const ledgerId = data.selected_ledger_id || "";
    if (!data.has_any_expense) append(fragment, renderOnboarding(ledgerId));

    const cards = data.cards || {};
    const layout = data.visible_layout ||
      (cards.layout || []).filter(function (item) { return item.visible; });
    if (!layout.length) {
      append(
        fragment,
        productState(
          "概览暂时没有可见模块",
          "重新启用一个模块后，这里会继续显示对应的账面概况。",
          dashboardUrl("/web/dashboard/cards", ledgerId),
          "调整概览模块",
          false
        )
      );
      return fragment;
    }

    const visibleByKey = {};
    layout.forEach(function (item) {
      visibleByKey[item.key] = item;
    });

    const sequence = el("section", "insight-sequence");
    sequence.setAttribute("aria-label", "本月任务与事实");
    DASHBOARD_LANES.forEach(function (lane) {
      const rendered = lane.keys
        .filter(function (key) { return Boolean(visibleByKey[key]); })
        .map(function (key) { return renderDashboardCard(visibleByKey[key], data); })
        .filter(Boolean);
      if (!rendered.length) return;
      const heading = el("header", "insight-lane-heading");
      append(
        heading,
        el("h2", "", lane.title),
        el("p", "", lane.summary)
      );
      append(sequence, heading, rendered);
    });
    append(fragment, sequence);
    return fragment;
  }

  function setDashboardStatus(root, title, body, retryable, visible) {
    const status = root.querySelector("[data-dashboard-status]");
    const titleNode = root.querySelector("[data-dashboard-status-title]");
    const bodyNode = root.querySelector("[data-dashboard-status-body]");
    const retry = root.querySelector("[data-dashboard-retry]");
    if (status) status.hidden = !visible;
    if (titleNode) titleNode.textContent = title;
    if (bodyNode) bodyNode.textContent = body;
    if (retry) {
      retry.hidden = !retryable;
      retry.disabled = false;
    }
  }

  function clearDashboardTimers(load) {
    if (!load) return;
    if (load.slowTimer) window.clearTimeout(load.slowTimer);
    if (load.fallbackTimer) window.clearTimeout(load.fallbackTimer);
    load.slowTimer = null;
    load.fallbackTimer = null;
  }

  function showDashboardFallback(root, load, title, body) {
    if (load.done) return;
    load.done = true;
    clearDashboardTimers(load);
    if (load.controller) load.controller.abort();
    setDashboardStatus(root, title, body, true, true);
    root.setAttribute("data-dashboard-state", "fallback");
  }

  function disposeCategoryChart() {
    const chartNode = document.getElementById("chart-category");
    if (!chartNode || typeof window.echarts === "undefined") return;
    const instance = window.echarts.getInstanceByDom(chartNode);
    if (instance) instance.dispose();
  }

  app.renderDashboard = renderDashboard;

  app.initDashboard = function initDashboard() {
    const root = document.getElementById("dashboard-app");
    if (!root) return;
    const target = root.querySelector("[data-dashboard-rendered]");
    const url = root.getAttribute("data-dashboard-url");
    let activeLoad = null;

    function startLoad() {
      if (activeLoad) {
        activeLoad.done = true;
        clearDashboardTimers(activeLoad);
        if (activeLoad.controller) activeLoad.controller.abort();
      }
      root.setAttribute("data-dashboard-state", "pending");
      setDashboardStatus(
        root,
        "正在更新概览",
        "正在读取收件、计划和洞察数据。",
        false,
        false
      );

      const load = {
        done: false,
        controller: typeof AbortController === "function" ? new AbortController() : null,
        slowTimer: null,
        fallbackTimer: null,
      };
      activeLoad = load;

      load.slowTimer = window.setTimeout(function () {
        if (load.done || activeLoad !== load) return;
        setDashboardStatus(
          root,
          "概览更新比平时慢",
          "页面保留当前账面结果，同时继续读取最新数据。",
          false,
          true
        );
        root.setAttribute("data-dashboard-state", "slow");
      }, SLOW_LOAD_MS);

      load.fallbackTimer = window.setTimeout(function () {
        if (load.done || activeLoad !== load) return;
        showDashboardFallback(
          root,
          load,
          "暂时没拿到最新数据",
          "当前页面仍是服务端生成的账面结果；稍后可以重试。"
        );
      }, FALLBACK_LOAD_MS);

      const fetchOptions = {
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
      };
      if (load.controller) fetchOptions.signal = load.controller.signal;

      fetch(url, fetchOptions)
        .then(function (response) {
          if (!response.ok) throw new Error("dashboard data failed");
          return response.json();
        })
        .then(function (data) {
          if (load.done || activeLoad !== load) return;
          load.done = true;
          clearDashboardTimers(load);
          disposeCategoryChart();
          target.replaceChildren(renderDashboard(data));
          root.setAttribute("data-dashboard-state", "ready");
          setDashboardStatus(root, "", "", false, false);
          if (typeof app.initCategoryDonut === "function") app.initCategoryDonut();
        })
        .catch(function () {
          if (load.done || activeLoad !== load) return;
          showDashboardFallback(
            root,
            load,
            "概览暂时刷新失败",
            "当前页面仍是服务端生成的账面结果；检查连接后可以重试。"
          );
        });
    }

    if (!target || !url || typeof fetch !== "function") {
      setDashboardStatus(
        root,
        "正在显示当前结果",
        "当前浏览器不支持动态刷新，页面保留服务端生成的账面结果。",
        false,
        true
      );
      root.setAttribute("data-dashboard-state", "fallback");
      return;
    }

    const retry = root.querySelector("[data-dashboard-retry]");
    if (retry) {
      retry.addEventListener("click", function () {
        retry.disabled = true;
        startLoad();
      });
    }
    startLoad();
  };
})(window, document);
