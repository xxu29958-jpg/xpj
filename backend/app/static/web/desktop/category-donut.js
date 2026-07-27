/* ECharts category donut chart. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initCategoryDonut = function initCategoryDonut() {
    const el = document.getElementById("chart-category");
    if (!el || typeof echarts === "undefined") return;
    let data;
    try { data = JSON.parse(el.getAttribute("data-categories") || "[]"); } catch (_) { return; }
    if (!data.length) return;

    const chart = echarts.init(el, null, { renderer: "canvas" });
    function build() {
      const palette = [
        app.readVar("--chart-series-1"),
        app.readVar("--chart-series-2"),
        app.readVar("--chart-series-3"),
        app.readVar("--chart-series-4"),
        app.readVar("--chart-series-5"),
        app.readVar("--chart-series-6"),
      ];
      const ink = app.readVar("--text-default");
      const ink3 = app.readVar("--text-meta");
      return {
        animation: false,
        tooltip: {
          trigger: "item",
          backgroundColor: app.readVar("--chart-tooltip-bg"),
          borderColor: app.readVar("--chart-tooltip-border"),
          textStyle: { color: app.readVar("--chart-tooltip-fg"), fontFamily: "'Noto Sans SC', Inter" },
          formatter: function (p) {
            // PR #253 P1-2: 分类名是用户/导入可控文本, 进 HTML tooltip 前必须转义。
            return '<div style="font-size:12px"><b>' + app.escapeHtml(p.name) + "</b><br/>" +
                   app.homeMoney((p.value || 0).toLocaleString()) + " · " + p.percent + "%</div>";
          },
        },
        legend: { show: false },
        series: [{
          type: "pie",
          radius: ["62%", "85%"],
          center: ["50%", "55%"],
          avoidLabelOverlap: false,
          itemStyle: { borderColor: app.readVar("--surface-card"), borderWidth: 2 },
          label: { show: false },
          labelLine: { show: false },
          emphasis: {
            scale: true, scaleSize: 4,
            label: {
              show: true, position: "center", color: ink,
              fontFamily: "Newsreader, 'Source Han Serif SC', serif", fontSize: 22,
              formatter: function (p) {
                // 纯文本拼接, 不用 ECharts rich-text DSL: 分类名里的 "}"/"{x|" 元字符
                // 会被当成样式段解析而破坏中心排版 (canvas 无 XSS, 但排版注入同样
                // 不可接受 — PR #253 R2 复审 P2-2)。
                return p.name + "\n" + app.homeCurrencySymbol() +
                       Math.round(p.value || 0).toLocaleString() + "\n" + p.percent + "%";
              },
            },
          },
          // Reads the dashboard category_share payload shape (name / amount_yuan, with
          // exponent-aware amount_major preferred when present — PR #253 P1-1).
          // Major units, not minor: tooltip and the center label print the value as-is.
          data: data.slice(0, 6).map(function (d, i) {
            return {
              name: d.name,
              value: d.amount_major == null ? d.amount_yuan : d.amount_major,
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
    document.querySelectorAll(".chart-legend-0").forEach(function (n) { n.style.background = app.readVar("--chart-series-1"); });
    document.querySelectorAll(".chart-legend-1").forEach(function (n) { n.style.background = app.readVar("--chart-series-2"); });
    document.querySelectorAll(".chart-legend-2").forEach(function (n) { n.style.background = app.readVar("--chart-series-3"); });
    document.querySelectorAll(".chart-legend-3").forEach(function (n) { n.style.background = app.readVar("--chart-series-4"); });
    document.querySelectorAll(".chart-legend-4").forEach(function (n) { n.style.background = app.readVar("--chart-series-5"); });
    document.querySelectorAll(".chart-legend-5").forEach(function (n) { n.style.background = app.readVar("--chart-series-6"); });
  };
})(window, document);
