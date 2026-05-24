/* ECharts monthly trend chart. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initTrendChart = function initTrendChart() {
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
      const ink = app.readVar("--text-default");
      const ink3 = app.readVar("--text-meta");
      const ink4 = app.readVar("--text-faint");
      const accent = app.readVar("--brand-primary");
      const hairline = app.readVar("--border-card");
      return {
        animation: false,
        grid: { left: 12, right: 12, top: 16, bottom: 28, containLabel: true },
        tooltip: {
          trigger: "axis",
          backgroundColor: app.readVar("--chart-tooltip-bg"),
          borderColor: app.readVar("--chart-tooltip-border"),
          textStyle: { color: app.readVar("--chart-tooltip-fg"), fontFamily: "Inter, 'Noto Sans SC'" },
          axisPointer: { lineStyle: { color: ink4, type: "dashed" } },
          formatter: function (params) {
            const head = '<div style="font-size:11px;letter-spacing:.1em;color:' + ink3 + ';margin-bottom:4px">' +
                         params[0].axisValue + "</div>";
            return head + params.map(function (p) {
              return '<div style="display:flex;justify-content:space-between;gap:14px;font-size:12px">' +
                '<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' +
                p.color + ';margin-right:6px;vertical-align:1px"></span>' + p.seriesName + "</span>" +
                '<b style="font-variant-numeric:tabular-nums">' +
                app.homeMoney((p.value || 0).toLocaleString()) + "</b></div>";
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
                return budgets[i] && amounts[i] > budgets[i] ? app.readVar("--state-danger-fg") : ink;
              },
              borderRadius: [2, 2, 0, 0],
            },
            z: 2,
          },
          {
            name: "趋势", type: "line", data: amounts,
            smooth: 0.3, symbol: "circle", symbolSize: 5, showSymbol: true,
            lineStyle: { color: accent, width: 1.4 },
            itemStyle: { color: accent, borderColor: app.readVar("--surface-card"), borderWidth: 1.5 },
            z: 3,
          },
        ],
      };
    }
    chart.setOption(build());
    new ResizeObserver(function () { chart.resize(); }).observe(el);
  };
})(window, document);
