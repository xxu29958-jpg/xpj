/* ECharts monthly trend chart. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  // States the bars alone cannot show: records netting to zero, an amount waiting for its rate, and a
  // set budget waiting for its rate. Each gets its own mark, never a guessed value.
  function renderMarks(marks, style) {
    return function (params, api) {
      const item = marks[params.dataIndex];
      const base = api.coord([item.value[0], 0]);
      const half = Math.min(api.size([1, 0])[0] * 0.41, 36);
      const current = params.dataIndex === marks.length - 1;
      const children = [];
      if (item.amount === "zero") {
        // Recorded as zero: a flat tick on the baseline, in the bar colour.
        children.push({ type: "rect", shape: { x: base[0] - half, y: base[1] - 3, width: half * 2, height: 3, r: 1.5 },
          style: { fill: style.accent, opacity: current ? 1 : 0.5 } });
        if (style.labelled) children.push({ type: "text", style: { x: base[0], y: base[1] - 7, text: app.homeMoneyMajor("0").replace(/\.0+$/, ""),
          fill: style.axisLabel, font: style.font, align: "center", verticalAlign: "bottom" } });
      } else if (item.amount === "unavailable") {
        // No value yet: an empty dashed outline of fixed height, so it never reads as an amount.
        const height = Math.min(48, params.coordSys.height * 0.3);
        children.push({ type: "rect", shape: { x: base[0] - half, y: base[1] - height, width: half * 2, height: height, r: [6, 6, 0, 0] },
          style: { fill: "transparent", stroke: style.warn, lineWidth: 1.5, lineDash: [4, 3] } });
        children.push({ type: "text", style: { x: base[0], y: base[1] - height - 4, text: style.roomy ? "待补汇率" : "?",
          fill: style.warn, font: style.font, align: "center", verticalAlign: "bottom" } });
      }
      if (item.budget) {
        // The budget exists but its level is unknown: name it at the top of the month instead of drawing a line.
        children.push({ type: "text", style: { x: base[0], y: params.coordSys.y, text: "预算?",
          fill: style.warn, font: style.font, align: "center", verticalAlign: "bottom" } });
      }
      return { type: "group", children: children };
    };
  }

  // A set budget is a dashed level inside its own month's band, never a line joining months.
  function renderBudgetLevel(stroke) {
    return function (params, api) {
      const value = api.value(1);
      if (value == null || isNaN(value)) return null;
      const point = api.coord([api.value(0), value]);
      const half = Math.min(api.size([1, 0])[0] * 0.44, 42);
      return { type: "line", shape: { x1: point[0] - half, y1: point[1], x2: point[0] + half, y2: point[1] },
        style: { stroke: stroke, lineWidth: 1.5, lineDash: [4, 3] } };
    };
  }

  // The server series as chart data; theme colours are applied separately in build().
  function monthData(series) {
    return {
      labels: series.map(function (s) { return Number(s.month.slice(5)) + "月"; }),
      amounts: series.map(function (s) {
        return {
          value: s.amount_cents == null ? null : app.homeMinorToMajor(s.amount_cents),
          majorText: s.amount_cents == null ? null : (s.amount_major_text || app.homeMinorToMajorText(s.amount_cents)),
          none: s.amount_state === "none",
        };
      }),
      // Only a set budget has a level to draw. A month without one is left out of the tooltip;
      // a set budget waiting for its rate stays in it as 待补汇率.
      budgets: series.map(function (s, index) {
        const set = s.budget_status === "set";
        return {
          value: [index, set ? app.homeMinorToMajor(s.budget_cents) : null],
          majorText: set ? (s.budget_major_text || app.homeMinorToMajorText(s.budget_cents)) : null,
          unset: s.budget_status === "not_set",
        };
      }),
      marks: series.map(function (s, index) {
        return { value: [index, 0], mark: true, budget: s.budget_status === "unavailable",
          amount: s.amount_state === "unavailable" || s.amount_state === "zero" ? s.amount_state : null };
      }),
    };
  }

  function formatMonthTooltip(params) {
    const head = '<div style="font-size:var(--type-caption-size);margin-bottom:var(--space-2)">' +
                 params[0].axisValue + "</div>";
    return head + params.filter(function (p) { return !p.data.unset && !p.data.mark; }).map(function (p) {
      return '<div style="display:flex;justify-content:space-between;gap:var(--space-4);font-size:var(--type-caption-size)">' +
        '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
        p.color + ';margin-right:6px;vertical-align:1px"></span>' + p.seriesName + "</span>" +
        '<b style="font-variant-numeric:tabular-nums">' +
        (p.data.none ? "没有记录" : p.data.majorText == null ? "待补汇率" : app.homeMoneyMajor(p.data.majorText)) + "</b></div>";
    }).join("");
  }

  app.initTrendChart = function initTrendChart() {
    const el = document.getElementById("chart-trend");
    if (!el || typeof echarts === "undefined") return;
    let series;
    try { series = JSON.parse(el.getAttribute("data-series") || "[]"); } catch (_) { return; }
    if (!series.length) return;

    const chart = echarts.init(el, null, { renderer: "canvas" });
    const { labels, amounts, budgets, marks } = monthData(series);
    function build() {
      const axisLabel = app.readVar("--chart-axis-label");
      const ink4 = app.readVar("--text-faint");
      const accent = app.readVar("--chart-series-1");
      const warn = app.readVar("--state-warn-fg");
      const hairline = app.readVar("--border-card");
      const fontSize = parseFloat(app.readVar("--type-caption-size"));
      const font = fontSize + "px " + app.readVar("--font-numeric");
      const known = amounts.filter(s => s.value !== null);
      const ordinary = known.every(s => s.value >= 0) && known.some(s => s.value > 0);
      const roomy = el.clientWidth / series.length > fontSize * 4;
      return {
        animation: false,
        grid: { left: 12, right: 12, top: fontSize * 3, bottom: 28, containLabel: true },
        tooltip: {
          trigger: "axis",
          backgroundColor: app.readVar("--chart-tooltip-bg"),
          borderColor: app.readVar("--chart-tooltip-border"),
          textStyle: { color: app.readVar("--chart-tooltip-fg"), fontFamily: app.readVar("--font-numeric") },
          axisPointer: { lineStyle: { color: ink4, type: "dashed" } },
          formatter: formatMonthTooltip,
        },
        legend: { show: false },
        xAxis: {
          type: "category",
          data: labels,
          axisLine: { show: !ordinary, lineStyle: { color: hairline } },
          axisTick: { show: false },
          axisLabel: { color: axisLabel, fontFamily: app.readVar("--font-numeric"), fontSize: fontSize, hideOverlap: true },
        },
        yAxis: {
          type: "value",
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { show: !ordinary, lineStyle: { color: hairline } },
          axisLabel: {
            show: !ordinary, color: axisLabel, fontFamily: app.readVar("--font-numeric"), fontSize: fontSize,
            formatter: function (v) { return v >= 1000 ? (v / 1000) + "k" : v; },
          },
        },
        series: [
          {
            // Each month's budget is its own level across that month's bar, never a line between months.
            name: "预算", type: "custom", data: budgets, encode: { x: 0, y: 1 }, color: ink4, z: 3,
            renderItem: renderBudgetLevel(ink4),
          },
          {
            name: "净支出", type: "bar", barMaxWidth: 72, barCategoryGap: "18%",
            data: amounts.map((amount, index) => ({...amount, itemStyle: {opacity: index === amounts.length - 1 ? 1 : .3}})),
            itemStyle: { color: accent, borderRadius: [6, 6, 0, 0] },
            label: { show: ordinary && roomy, position: "top", color: axisLabel, opacity: 1,
              fontFamily: app.readVar("--font-numeric"), fontSize: fontSize,
              formatter: p => p.data.majorText == null || p.data.none || p.data.value === 0 ? "" : app.homeMoneyMajor(p.data.majorText).replace(/\.0+$/, "") },
            z: 2,
          },
          {
            name: "标记", type: "custom", data: marks, encode: { x: 0, y: 1 }, silent: true, z: 4,
            renderItem: renderMarks(marks, { accent: accent, warn: warn, axisLabel: axisLabel, font: font, labelled: ordinary && roomy, roomy: roomy }),
          },
        ],
      };
    }
    app.withChartFonts("0123456789.,%−-k月" + app.homeCurrencySymbol(), function () {
      chart.setOption(build());
      // Canvas does not inherit changed CSS colors. Reproject the same data/instance.
      new MutationObserver(function () { chart.setOption(build()); }).observe(document.documentElement, {
        attributes: true, attributeFilter: ["data-theme", "data-accent"],
      });
    });
    new ResizeObserver(function () { chart.resize(); chart.setOption(build()); }).observe(el);
  };
})(window, document);
