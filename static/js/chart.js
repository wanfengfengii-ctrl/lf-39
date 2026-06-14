/* ============================================================
 * chart.js — Plotly.js 图表封装：水位曲线 + 误差柱状图
 * ============================================================ */
(function (global) {
  'use strict';

  const PALETTE = [
    '#5C4033', '#4A7C59', '#C23B22', '#B8860B',
    '#4E6BA0', '#8B4E8D', '#2F8F6F', '#C9742D'
  ];

  const ClepsydraCharts = {};

  const paperBg = 'rgba(255,255,255,0)';
  const plotBg = '#FFFBF2';
  const gridColor = 'rgba(139, 105, 20, 0.15)';
  const axisColor = '#6B5441';

  function baseLayout(title, xLabel, yLabel, height) {
    return {
      height: height || 360,
      paper_bgcolor: paperBg,
      plot_bgcolor: plotBg,
      margin: { l: 58, r: 20, t: 42, b: 46 },
      font: {
        family: '"Noto Sans SC", "PingFang SC", sans-serif',
        size: 12,
        color: axisColor
      },
      title: {
        text: title,
        font: { family: '"Noto Serif SC", serif', size: 14, color: '#5C4033' },
        x: 0.02,
        xanchor: 'left',
        pad: { t: 2, l: 4 }
      },
      xaxis: {
        title: { text: xLabel, font: { size: 12 } },
        gridcolor: gridColor,
        zerolinecolor: gridColor,
        linecolor: gridColor,
        tickcolor: axisColor,
        showline: true
      },
      yaxis: {
        title: { text: yLabel, font: { size: 12 } },
        gridcolor: gridColor,
        zerolinecolor: gridColor,
        linecolor: gridColor,
        tickcolor: axisColor,
        showline: true
      },
      legend: {
        orientation: 'h',
        y: -0.24,
        x: 0,
        font: { size: 11 },
        bgcolor: 'rgba(255,255,255,.5)'
      },
      hovermode: 'closest',
      dragmode: false
    };
  }

  ClepsydraCharts.renderWaterLevel = function (elId, experiments, scheme, cfg, selectedIds) {
    const el = document.getElementById(elId);
    if (!el) return;
    const capacity = cfg ? cfg.capacity : 1000;
    const targetDuration = cfg ? cfg.target_duration : 60;

    const traces = [];

    if (scheme && scheme.marks && scheme.marks.length > 1) {
      const xs = scheme.marks.map(m => m.target_time);
      const ys = scheme.marks.map(m => m.target_water_level);
      traces.push({
        x: xs, y: ys,
        mode: 'lines+markers',
        name: '理论刻度',
        line: { color: '#8B6914', width: 2.2, dash: 'dashdot' },
        marker: { symbol: 'diamond-open', size: 8, color: '#8B6914', line: { width: 1.5 } },
        hovertemplate: '<b>理论刻度</b><br>时间: %{x} 分<br>水位: %{y} ml<extra></extra>'
      });
    }

    const exps = (experiments || []).filter(e =>
      (!selectedIds || selectedIds.length === 0 || selectedIds.includes(e.id)) &&
      e.records && e.records.length > 0
    );

    exps.forEach((e, idx) => {
      const color = PALETTE[(idx + 1) % PALETTE.length];
      const xs = [0].concat(e.records.map(r => r.time_point));
      const ys = [capacity].concat(e.records.map(r => r.water_level));
      const name = `第${e.round_number}轮${e.needs_recheck ? ' ⚠' : ''}`;
      traces.push({
        x: xs, y: ys,
        mode: 'lines+markers',
        name,
        line: { color, width: 2.4, shape: 'spline', smoothing: 0.2 },
        marker: { size: 6, color, line: { width: 1, color: '#fff' } },
        hovertemplate: `<b>${name}</b><br>时间: %{x} 分<br>水位: %{y} ml<extra></extra>`
      });
    });

    if (exps.length === 0 && (!scheme || !scheme.marks || scheme.marks.length === 0)) {
      Plotly.react(el, [{
        x: [0, targetDuration], y: [capacity, 0],
        mode: 'lines',
        name: '初始参考',
        line: { color: '#D9C7AE', width: 1.4, dash: 'dashed' },
        hoverinfo: 'skip'
      }], baseLayout('水位变化曲线', '时间（分钟）', '水位（ml）'), { displayModeBar: false, responsive: true });
      return;
    }

    const layout = baseLayout(
      '水位变化曲线（理论刻度 vs 实测数据）',
      '时间（分钟）', '水位（ml）'
    );
    layout.shapes = [{
      type: 'line',
      x0: 0, x1: targetDuration || Math.max(...(traces.flatMap(t => t.x || [0]))),
      y0: 0, y1: 0,
      xref: 'x', yref: 'y',
      line: { color: 'rgba(194, 59, 34, 0.25)', width: 1, dash: 'dot' }
    }];

    Plotly.react(el, traces, layout, {
      displayModeBar: false,
      responsive: true,
      scrollZoom: false,
      doubleClick: false
    });
  };

  ClepsydraCharts.renderErrorBars = function (elId, analysis) {
    const el = document.getElementById(elId);
    if (!el) return;

    if (!analysis || !analysis.interval_errors || analysis.interval_errors.length === 0) {
      Plotly.react(el, [], {
        ...baseLayout('区间误差率分布图', '刻度区间', '误差率（%）', 220),
        annotations: [{
          text: '暂无误差分析数据<br><span style="font-size:11px;color:#9C8876">完成一轮实验后显示</span>',
          showarrow: false,
          xref: 'paper', yref: 'paper',
          x: 0.5, y: 0.5,
          font: { size: 13, color: '#9C8876' },
          align: 'center'
        }]
      }, { displayModeBar: false, responsive: true });
      return;
    }

    const errors = analysis.interval_errors;
    const xs = errors.map(e => e.interval);
    const ys = errors.map(e => e.error_percent);
    const threshold = analysis.threshold_percent || 5;
    const colors = errors.map(e => Math.abs(e.error_percent) > threshold ? '#C23B22' : (e.error_percent > 0 ? '#4A7C59' : '#4E6BA0'));

    const trace = {
      x: xs, y: ys,
      type: 'bar',
      marker: {
        color: colors,
        line: { width: 0.5, color: '#fff' }
      },
      text: ys.map(v => `${v > 0 ? '+' : ''}${v.toFixed(2)}%`),
      textposition: 'outside',
      hovertemplate: '<b>%{x}</b><br>误差率: %{y:.3f}%<extra></extra>'
    };

    const layout = baseLayout('区间误差率分布图（红色为超限 ±' + threshold + '%）', '刻度区间', '误差率（%）', 220);
    layout.shapes = [
      {
        type: 'line', x0: -0.5, x1: xs.length - 0.5,
        y0: threshold, y1: threshold, xref: 'x', yref: 'y',
        line: { color: '#C23B22', width: 1.2, dash: 'dash' }
      },
      {
        type: 'line', x0: -0.5, x1: xs.length - 0.5,
        y0: -threshold, y1: -threshold, xref: 'x', yref: 'y',
        line: { color: '#C23B22', width: 1.2, dash: 'dash' }
      },
      {
        type: 'line', x0: -0.5, x1: xs.length - 0.5,
        y0: 0, y1: 0, xref: 'x', yref: 'y',
        line: { color: '#6B5441', width: 0.8 }
      }
    ];
    layout.margin = { l: 58, r: 20, t: 38, b: 56 };

    Plotly.react(el, [trace], layout, { displayModeBar: false, responsive: true });
  };

  global.ClepsydraCharts = ClepsydraCharts;
})(window);
