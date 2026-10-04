/* v0.9 /web/reports - ECharts view layer.
 * The backend still returns plain report data; this script only renders the
 * server-injected JSON from #reports-overview-data.
 */
(function () {
  'use strict';

  var app = window.TicketboxWeb = window.TicketboxWeb || {};

  function disableExport(reason) {
    var button = document.getElementById('reports-export-png');
    if (!button) return;
    button.disabled = true;
    button.setAttribute('aria-disabled', 'true');
    button.title = reason;
    button.textContent = 'PNG 预览不可用';
  }

  if (typeof window.echarts === 'undefined') {
    disableExport('图表组件没有加载，仍可查看页面数据和导出 CSV。');
    return;
  }

  var root = document.documentElement;
  var chartInstances = [];

  function cssVar(name, fallback) {
    var value = window.getComputedStyle(root).getPropertyValue(name);
    return value && value.trim() ? value.trim() : fallback;
  }

  function palette() {
    // fallback 兜底色 = paper 主题真值（shared/tokens.css :root），仅在 getComputedStyle
    // 读不到 CSS 变量时生效；正常运行总是拿到主题实时值。务必与 tokens.css paper 块同步。
    return {
      series: [
        cssVar('--chart-series-1', '#487d5b'),
        cssVar('--chart-series-2', '#bb9878'),
        cssVar('--chart-series-3', '#a598c2'),
        cssVar('--chart-series-4', '#deb985'),
        cssVar('--chart-series-5', '#3e6770'),
        cssVar('--chart-series-6', '#d6b487'),
        cssVar('--chart-series-7', '#5a4a6e'),
        cssVar('--chart-series-8', '#807968'),
      ],
      axis: cssVar('--chart-axis', '#aaa294'),
      axisLabel: cssVar('--chart-axis-label', '#4a463f'),
      grid: cssVar('--chart-grid', 'rgba(28, 26, 24, 0.08)'),
      tooltipBg: cssVar('--chart-tooltip-bg', '#1c1a18'),
      tooltipFg: cssVar('--chart-tooltip-fg', '#fbf8f1'),
      surface: cssVar('--surface-card', '#ffffff'),
      overspend: cssVar('--chart-overspend', '#a4361c'),
    };
  }

  function parseReport() {
    var tag = document.getElementById('reports-overview-data');
    if (!tag) return null;
    try {
      return JSON.parse(tag.textContent || '{}');
    } catch (_) {
      return null;
    }
  }

  function compactYuan(cents) {
    if (cents === null || cents === undefined) return '待补汇率';
    var yuanValue = app.homeMinorToMajor(cents);
    if (yuanValue === null) return '金额不可用';
    var abs = Math.abs(yuanValue);
    if (abs >= 10000) return (yuanValue / 10000).toFixed(1) + '万';
    if (abs >= 1000) return Math.round(yuanValue).toString();
    return yuanValue.toFixed(0);
  }

  function homeMoneyCents(cents) {
    return cents === null || cents === undefined ? '待补汇率' : app.homeMoneyMinor(cents);
  }

  function homeCompactCents(cents) {
    return app.homeCurrencySymbol() + compactYuan(cents);
  }

  function rgba(color, alpha) {
    var clean = (color || '').trim();
    if (!clean || clean.indexOf('#') !== 0) return color;
    var hex = clean.slice(1);
    if (hex.length === 3) {
      hex = hex.split('').map(function (part) { return part + part; }).join('');
    }
    if (hex.length !== 6) return color;
    return 'rgba(' + [
      parseInt(hex.slice(0, 2), 16),
      parseInt(hex.slice(2, 4), 16),
      parseInt(hex.slice(4, 6), 16),
      alpha,
    ].join(', ') + ')';
  }

  function truncate(value, max) {
    var text = value || '';
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }

  function baseTooltipColors(colors) {
    return {
      backgroundColor: colors.tooltipBg,
      borderWidth: 0,
      textStyle: { color: colors.tooltipFg, fontSize: parseFloat(cssVar('--type-caption-size', '13')), fontFamily: cssVar('--font-numeric', 'sans-serif') },
      extraCssText: 'box-shadow:0 8px 24px rgba(0,0,0,.22);border-radius:8px;',
    };
  }

  function markRendered(container, chart) {
    var panel = container.closest('.reports-panel');
    if (panel) panel.classList.add('is-chart-rendered');
    return chart;
  }

  function chartFor(container) {
    var chart = chartInstances.find(function (item) { return item.getDom() === container; });
    if (!chart) {
      chart = window.echarts.init(container);
      chartInstances.push(chart);
    }
    return chart;
  }

  function hasChartSpace(container) {
    return container && container.clientWidth > 0 && !container.closest('details:not([open])');
  }

  function renderTrend(report, colors) {
    var container = document.getElementById('reports-trend-chart');
    var points = report && report.trend ? report.trend : [];
    var hasData = points.some(function (point) {
      return Number(point.amount_cents || 0) > 0 || Number(point.count || 0) > 0;
    });
    if (!hasChartSpace(container) || !hasData) return null;

    var chart = chartFor(container);
    var lineColor = colors.series[0];
    chart.setOption({
      textStyle: { fontFamily: cssVar('--font-numeric', 'sans-serif') },
      color: colors.series,
      tooltip: Object.assign(baseTooltipColors(colors), {
        trigger: 'axis',
        formatter: function (items) {
          if (!items || !items.length) return '';
          var point = points[items[0].dataIndex];
          return point.label + '<br><strong>' + homeMoneyCents(point.amount_cents) + '</strong> · ' + point.count + ' 笔';
        },
      }),
      grid: { left: 58, right: 20, top: 24, bottom: 38 },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: points.map(function (point) { return point.label; }),
        axisLine: { lineStyle: { color: colors.axis } },
        axisTick: { show: false },
        axisLabel: { color: colors.axisLabel, fontSize: parseFloat(cssVar('--type-caption-size', '13')), hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: colors.axisLabel,
          fontSize: parseFloat(cssVar('--type-caption-size', '13')),
          formatter: function (value) { return homeCompactCents(value); },
        },
        splitLine: { lineStyle: { color: colors.grid, type: 'dashed' } },
      },
      series: [{
        name: '支出',
        type: 'line',
        data: points.map(function (point) { return point.amount_cents; }),
        smooth: true,
        showSymbol: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { width: 3, color: lineColor },
        itemStyle: { color: lineColor, borderColor: colors.surface, borderWidth: 2 },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: rgba(lineColor, 0.30) },
              { offset: 1, color: rgba(lineColor, 0.03) },
            ],
          },
        },
      }],
      animationDuration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180,
      animationEasing: 'cubicOut',
    });
    return markRendered(container, chart);
  }

  function renderMerchant(report, colors) {
    var container = document.getElementById('reports-merchant-chart');
    var rows = report && report.merchant_ranking ? report.merchant_ranking.slice(0, 8) : [];
    if (!hasChartSpace(container) || !rows.length) return null;

    var metric = report.ranking_metric === 'count' ? 'count' : 'amount';
    if (metric === 'amount' && rows.some(function (row) { return row.amount_cents == null; })) return null;
    var reversedRows = rows.slice().reverse();
    var chart = chartFor(container);
    chart.setOption({
      textStyle: { fontFamily: cssVar('--font-numeric', 'sans-serif') },
      color: colors.series,
      tooltip: Object.assign(baseTooltipColors(colors), {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (items) {
          if (!items || !items.length) return '';
          var row = reversedRows[items[0].dataIndex];
          var value = metric === 'count' ? row.count + ' 笔' : homeMoneyCents(row.amount_cents);
          return row.merchant + '<br><strong>' + value + '</strong>';
        },
      }),
      grid: { left: 106, right: 44, top: 8, bottom: 30 },
      xAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: colors.axis } },
        axisTick: { show: false },
        axisLabel: {
          color: colors.axisLabel,
          fontSize: parseFloat(cssVar('--type-caption-size', '13')),
          formatter: function (value) {
            return metric === 'count' ? value : homeCompactCents(value);
          },
        },
        splitLine: { lineStyle: { color: colors.grid, type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        data: reversedRows.map(function (row) { return truncate(row.merchant || '未填写商家', 12); }),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: colors.axisLabel, fontSize: parseFloat(cssVar('--type-caption-size', '13')) },
      },
      series: [{
        type: 'bar',
        data: reversedRows.map(function (row, index) {
          return {
            value: metric === 'count' ? row.count : row.amount_cents,
            itemStyle: { color: colors.series[index % colors.series.length] },
          };
        }),
        barWidth: 14,
        itemStyle: { borderRadius: [0, 7, 7, 0] },
        label: {
          show: true,
          position: 'right',
          color: colors.axisLabel,
          fontSize: parseFloat(cssVar('--type-caption-size', '13')),
          formatter: function (item) {
            return metric === 'count' ? item.value + ' 笔' : homeCompactCents(item.value);
          },
        },
      }],
      animationDuration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180,
    });
    return markRendered(container, chart);
  }

  function renderCategory(report, colors) {
    var container = document.getElementById('reports-category-chart');
    var rows = report && report.category_comparison ? report.category_comparison.slice(0, 8) : [];
    if (!hasChartSpace(container) || !rows.length) return null;

    var chart = chartFor(container);
    chart.setOption({
      textStyle: { fontFamily: cssVar('--font-numeric', 'sans-serif') },
      color: [colors.series[0], rgba(colors.series[2], 0.55), rgba(colors.series[4], 0.55)],
      legend: {
        data: ['本月', '上月', '去年同月'],
        top: 0,
        textStyle: { color: colors.axisLabel, fontSize: parseFloat(cssVar('--type-caption-size', '13')) },
      },
      tooltip: Object.assign(baseTooltipColors(colors), {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (items) {
          if (!items || !items.length) return '';
          var row = rows[items[0].dataIndex];
          var delta = row.delta_amount_cents;
          var yoyDelta = row.year_over_year_delta_amount_cents;
          var prefix = delta > 0 ? '+' : '';
          var yoyPrefix = yoyDelta > 0 ? '+' : '';
          return row.category + '<br>本月 ' + homeMoneyCents(row.amount_cents)
            + '<br>上月 ' + homeMoneyCents(row.previous_amount_cents)
            + '<br>去年同月 ' + homeMoneyCents(row.year_over_year_amount_cents)
            + '<br>环比 ' + prefix + homeMoneyCents(delta)
            + '<br>同比 ' + yoyPrefix + homeMoneyCents(yoyDelta);
        },
      }),
      grid: { left: 58, right: 22, top: 36, bottom: 44 },
      xAxis: {
        type: 'category',
        data: rows.map(function (row) { return truncate(row.category || '未分类', 8); }),
        axisLine: { lineStyle: { color: colors.axis } },
        axisTick: { show: false },
        axisLabel: { color: colors.axisLabel, fontSize: parseFloat(cssVar('--type-caption-size', '13')), interval: 0, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: colors.axisLabel,
          fontSize: parseFloat(cssVar('--type-caption-size', '13')),
          formatter: function (value) { return homeCompactCents(value); },
        },
        splitLine: { lineStyle: { color: colors.grid, type: 'dashed' } },
      },
      series: [{
        name: '本月',
        type: 'bar',
        data: rows.map(function (row) {
          return {
            value: row.amount_cents,
            itemStyle: {
              color: Number(row.delta_amount_cents || 0) > 0 ? colors.overspend : colors.series[0],
              borderRadius: [5, 5, 0, 0],
            },
          };
        }),
        barWidth: 14,
      }, {
        name: '上月',
        type: 'bar',
        data: rows.map(function (row) { return row.previous_amount_cents; }),
        itemStyle: { borderRadius: [5, 5, 0, 0] },
        barWidth: 14,
      }, {
        name: '去年同月',
        type: 'bar',
        data: rows.map(function (row) { return row.year_over_year_amount_cents; }),
        itemStyle: { borderRadius: [5, 5, 0, 0] },
        barWidth: 14,
      }],
      animationDuration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180,
    });
    return markRendered(container, chart);
  }

  function bindExport() {
    var button = document.getElementById('reports-export-png');
    var dialog = document.getElementById('reports-export-dialog');
    var image = document.getElementById('reports-export-image');
    if (!button || !dialog || !image) return;
    button.addEventListener('click', function () {
      var trendChart = window.echarts.getInstanceByDom(document.getElementById('reports-trend-chart'));
      if (!trendChart) {
        window.alert('还没有趋势图可导出。');
        return;
      }
      var dataUrl = trendChart.getDataURL({
        type: 'png',
        pixelRatio: 2,
        backgroundColor: palette().surface,
      });
      image.src = dataUrl;
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        window.open(dataUrl, '_blank');
      }
    });
  }

  function bindResize(report) {
    document.addEventListener('toggle', function (event) {
      if (event.target.matches('details.report-section') && event.target.open) {
        renderCharts(report);
        chartInstances.forEach(function (chart) { chart.resize(); });
      }
    }, true);
    window.addEventListener('resize', function () {
      chartInstances.forEach(function (chart) { chart.resize(); });
    });
    if (typeof window.ResizeObserver === 'function') {
      var observer = new ResizeObserver(function () {
        renderCharts(report);
        chartInstances.forEach(function (chart) { chart.resize(); });
      });
      document.querySelectorAll('.reports-panel .report-chart').forEach(function (container) {
        observer.observe(container);
      });
    }
  }

  function renderCharts(report) {
    var colors = palette();
    var trendChart = renderTrend(report, colors);
    renderMerchant(report, colors);
    renderCategory(report, colors);
    return trendChart;
  }

  function init() {
    var report = parseReport();
    if (!report) return;
    var section = document.getElementById(window.location.hash.slice(1));
    if (section && section.matches('details.report-section')) section.open = true;
    var fontText = '0123456789.,%−-万本月上月去年同月' + app.homeCurrencySymbol() +
      (report.trend || []).map(function (point) { return point.label; }).join('') +
      (report.merchant_ranking || []).slice(0, 8).map(function (row) { return row.merchant; }).join('') +
      (report.category_comparison || []).slice(0, 8).map(function (row) { return row.category; }).join('');
    app.withChartFonts(fontText, function () {
      renderCharts(report);
      bindExport();
      bindResize(report);
      new MutationObserver(function () { renderCharts(report); }).observe(root, {
        attributes: true, attributeFilter: ['data-theme', 'data-accent'],
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
