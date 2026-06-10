/* v0.9 /web/reports - ECharts view layer.
 * The backend still returns plain report data; this script only renders the
 * server-injected JSON from #reports-overview-data.
 */
(function () {
  'use strict';

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
    return {
      series: [
        cssVar('--chart-series-1', '#245d78'),
        cssVar('--chart-series-2', '#d5a35d'),
        cssVar('--chart-series-3', '#185b4f'),
        cssVar('--chart-series-4', '#a86a52'),
        cssVar('--chart-series-5', '#3e92ae'),
        cssVar('--chart-series-6', '#6b7f4d'),
        cssVar('--chart-series-7', '#b87a48'),
        cssVar('--chart-series-8', '#5a4e78'),
      ],
      axis: cssVar('--chart-axis', '#8fa1a6'),
      axisLabel: cssVar('--chart-axis-label', '#52646a'),
      grid: cssVar('--chart-grid', 'rgba(159, 180, 187, 0.2)'),
      tooltipBg: cssVar('--chart-tooltip-bg', '#112a35'),
      tooltipFg: cssVar('--chart-tooltip-fg', '#f1f6f7'),
      surface: cssVar('--surface-card', '#ffffff'),
      overspend: cssVar('--chart-overspend', '#b04a3c'),
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

  function yuan(cents) {
    var amount = Number(cents || 0) / 100;
    return amount.toLocaleString('zh-CN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function compactYuan(cents) {
    var yuanValue = Number(cents || 0) / 100;
    var abs = Math.abs(yuanValue);
    if (abs >= 10000) return (yuanValue / 10000).toFixed(1) + '万';
    if (abs >= 1000) return Math.round(yuanValue).toString();
    return yuanValue.toFixed(0);
  }

  function homeCurrencySymbol() {
    return root.getAttribute('data-home-currency-symbol') ||
      root.getAttribute('data-home-currency') ||
      '';
  }

  function homeMoneyCents(cents) {
    return homeCurrencySymbol() + yuan(cents);
  }

  function homeCompactCents(cents) {
    return homeCurrencySymbol() + compactYuan(cents);
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
      textStyle: { color: colors.tooltipFg, fontSize: 12 },
      extraCssText: 'box-shadow:0 8px 24px rgba(15,23,42,.22);border-radius:8px;',
    };
  }

  function markRendered(container, chart) {
    var panel = container.closest('.reports-panel');
    if (panel) panel.classList.add('is-chart-rendered');
    chartInstances.push(chart);
    return chart;
  }

  function renderTrend(report, colors) {
    var container = document.getElementById('reports-trend-chart');
    var points = report && report.trend ? report.trend : [];
    var hasData = points.some(function (point) {
      return Number(point.amount_cents || 0) > 0 || Number(point.count || 0) > 0;
    });
    if (!container || !hasData) return null;

    var chart = window.echarts.init(container);
    var lineColor = colors.series[0];
    chart.setOption({
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
        axisLabel: { color: colors.axisLabel, fontSize: 11, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: colors.axisLabel,
          fontSize: 11,
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
      animationDuration: 600,
      animationEasing: 'cubicOut',
    });
    return markRendered(container, chart);
  }

  function renderMerchant(report, colors) {
    var container = document.getElementById('reports-merchant-chart');
    var rows = report && report.merchant_ranking ? report.merchant_ranking.slice(0, 8) : [];
    if (!container || !rows.length) return null;

    var metric = report.ranking_metric === 'count' ? 'count' : 'amount';
    var reversedRows = rows.slice().reverse();
    var chart = window.echarts.init(container);
    chart.setOption({
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
          fontSize: 11,
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
        axisLabel: { color: colors.axisLabel, fontSize: 12 },
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
          fontSize: 11,
          formatter: function (item) {
            return metric === 'count' ? item.value + ' 笔' : homeCompactCents(item.value);
          },
        },
      }],
      animationDuration: 500,
    });
    return markRendered(container, chart);
  }

  function renderCategory(report, colors) {
    var container = document.getElementById('reports-category-chart');
    var rows = report && report.category_comparison ? report.category_comparison.slice(0, 8) : [];
    if (!container || !rows.length) return null;

    var chart = window.echarts.init(container);
    chart.setOption({
      color: [colors.series[0], rgba(colors.series[2], 0.55)],
      legend: {
        data: ['本月', '上月'],
        top: 0,
        textStyle: { color: colors.axisLabel, fontSize: 12 },
      },
      tooltip: Object.assign(baseTooltipColors(colors), {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (items) {
          if (!items || !items.length) return '';
          var row = rows[items[0].dataIndex];
          var delta = Number(row.delta_amount_cents || 0);
          var prefix = delta > 0 ? '+' : '';
          return row.category + '<br>本月 ' + homeMoneyCents(row.amount_cents)
            + '<br>上月 ' + homeMoneyCents(row.previous_amount_cents)
            + '<br>环比 ' + prefix + homeMoneyCents(delta);
        },
      }),
      grid: { left: 58, right: 22, top: 36, bottom: 44 },
      xAxis: {
        type: 'category',
        data: rows.map(function (row) { return truncate(row.category || '未分类', 8); }),
        axisLine: { lineStyle: { color: colors.axis } },
        axisTick: { show: false },
        axisLabel: { color: colors.axisLabel, fontSize: 11, interval: 0, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: colors.axisLabel,
          fontSize: 11,
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
      }],
      animationDuration: 500,
    });
    return markRendered(container, chart);
  }

  function bindExport(trendChart, colors) {
    var button = document.getElementById('reports-export-png');
    var dialog = document.getElementById('reports-export-dialog');
    var image = document.getElementById('reports-export-image');
    if (!button || !dialog || !image) return;
    button.addEventListener('click', function () {
      if (!trendChart) {
        window.alert('还没有趋势图可导出。');
        return;
      }
      var dataUrl = trendChart.getDataURL({
        type: 'png',
        pixelRatio: 2,
        backgroundColor: colors.surface,
      });
      image.src = dataUrl;
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        window.open(dataUrl, '_blank');
      }
    });
  }

  function bindResize() {
    window.addEventListener('resize', function () {
      chartInstances.forEach(function (chart) { chart.resize(); });
    });
    if (typeof window.ResizeObserver === 'function') {
      var observer = new ResizeObserver(function () {
        chartInstances.forEach(function (chart) { chart.resize(); });
      });
      chartInstances.forEach(function (chart) {
        observer.observe(chart.getDom());
      });
    }
  }

  function init() {
    var report = parseReport();
    if (!report) return;
    var colors = palette();
    var trendChart = renderTrend(report, colors);
    renderMerchant(report, colors);
    renderCategory(report, colors);
    bindExport(trendChart, colors);
    bindResize();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
