/* ECharts category donut chart. */
(function (window, document) {
  "use strict";

  const app = window.TicketboxWeb = window.TicketboxWeb || {};

  app.initCategoryDonut = function initCategoryDonut() {
    const el = document.getElementById("chart-category");
    if (!el || typeof echarts === "undefined") return;
    let data;
    try { data = JSON.parse(el.getAttribute("data-categories") || "[]"); } catch (_) { return; }
    if (!data.length || data.some(function (d) {
      return d.amount_major == null || !Number.isFinite(d.amount_major) || d.amount_major < 0;
    }) || !data.some(function (d) { return d.amount_major > 0; })) return;

    let chart = null;
    function build() {
      const palette = [
        app.readVar("--chart-series-1"),
        app.readVar("--chart-series-2"),
        app.readVar("--chart-series-3"),
        app.readVar("--chart-series-4"),
        app.readVar("--chart-series-5"),
        app.readVar("--chart-series-6"),
      ];
      return {
        animation: false,
        tooltip: {
          trigger: "item",
          backgroundColor: app.readVar("--chart-tooltip-bg"),
          borderColor: app.readVar("--chart-tooltip-border"),
          textStyle: { color: app.readVar("--chart-tooltip-fg"), fontFamily: app.readVar("--font-numeric"), fontSize: parseFloat(app.readVar("--type-caption-size")) },
          formatter: function (p) {
            // PR #253 P1-2: 分类名是用户/导入可控文本, 进 HTML tooltip 前必须转义。
            // 金额文案只消费服务器生成的精确 label；value 仅供几何。
            return '<div><b>' + app.escapeHtml(p.name) + "</b><br/>" +
                   app.escapeHtml(p.data.amountLabel) + " · " + app.escapeHtml(p.data.percentLabel) + "</div>";
          },
        },
        legend: { show: false },
        series: [{
          type: "pie",
          radius: ["70%", "94%"],
          center: ["50%", "50%"],
          avoidLabelOverlap: false,
          itemStyle: { borderColor: app.readVar("--surface-card"), borderWidth: 2 },
          label: { show: false, position: "center" },
          labelLine: { show: false },
          emphasis: {
            scale: true, scaleSize: 4,
            label: { show: false },
          },
          // Values describe geometry only; labels and percentages come from the
          // same server projection as the visible, accessible category list.
          data: data.slice(0, 6).map(function (d, i) {
            return {
              name: d.name,
              value: d.amount_major,
              amountLabel: d.amount_label,
              percentLabel: d.percent_label,
              itemStyle: { color: palette[i % palette.length] },
            };
          }),
        }],
      };
    }
    const fontText = "0123456789.,%−-" + data.slice(0, 6).map(function (d) { return d.name + d.amount_label; }).join("");
    function render() {
      // The narrow layout presents the same server-owned shares as text rows.
      // Initialise only after CSS gives the canvas space, including on resize.
      if (!el.clientWidth || !el.clientHeight) return;
      if (!chart) chart = echarts.init(el, null, { renderer: "canvas" });
      chart.resize();
      chart.setOption(build());
    }
    app.withChartFonts(fontText, function () {
      render();
      // Canvas does not inherit changed CSS colors. Reproject the same data/instance.
      new MutationObserver(render).observe(document.documentElement, {
        attributes: true, attributeFilter: ["data-theme", "data-accent"],
      });
      new ResizeObserver(render).observe(el);
    });

    // 把环图 legend dots 的颜色也按 chart-series 涂上
    document.querySelectorAll(".chart-legend-0").forEach(function (n) { n.style.background = app.readVar("--chart-series-1"); });
    document.querySelectorAll(".chart-legend-1").forEach(function (n) { n.style.background = app.readVar("--chart-series-2"); });
    document.querySelectorAll(".chart-legend-2").forEach(function (n) { n.style.background = app.readVar("--chart-series-3"); });
    document.querySelectorAll(".chart-legend-3").forEach(function (n) { n.style.background = app.readVar("--chart-series-4"); });
    document.querySelectorAll(".chart-legend-4").forEach(function (n) { n.style.background = app.readVar("--chart-series-5"); });
    document.querySelectorAll(".chart-legend-5").forEach(function (n) { n.style.background = app.readVar("--chart-series-6"); });
  };
})(window, document);
