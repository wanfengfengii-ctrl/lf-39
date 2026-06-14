/* ============================================================
 * inversion.js — 真实实验—扰动仿真联合反演模块
 * ============================================================ */
(function (global) {
  'use strict';

  const InversionApp = {};
  let ctx = null;

  const ALGO_LABELS = {
    'hybrid_pso_grid': '粒子群+网格搜索（推荐）',
    'pso': '粒子群优化（PSO）',
    'grid_search': '网格搜索',
    'nelder_mead': 'Nelder-Mead 单纯形'
  };

  const PARAM_LABELS = {
    temperature: '环境温度',
    viscosity: '液体黏度',
    inflow_amplitude: '注水波动幅度',
    orifice_wear: '孔径磨损程度',
    tilt_angle: '容器倾斜角度'
  };

  const PARAM_UNITS = {
    temperature: '°C',
    viscosity: 'mPa·s',
    inflow_amplitude: '',
    orifice_wear: '',
    tilt_angle: '°'
  };

  InversionApp.init = function (context) {
    ctx = context;
    ctx.inversionParamRanges = [];
    ctx.inversionExperiments = [];
    ctx.inversionResults = [];
    ctx.currentInversionResult = null;
    ctx.inversionIsMulti = false;
    InversionApp.bindEvents();
    InversionApp.loadMeta();
  };

  InversionApp.bindEvents = function () {
    const runBtn = document.getElementById('inversion-run-btn');
    if (runBtn) {
      runBtn.addEventListener('click', () => InversionApp.runInversion());
    }
    const multiToggle = document.getElementById('inversion-multi-toggle');
    if (multiToggle) {
      multiToggle.addEventListener('change', (e) => {
        ctx.inversionIsMulti = e.target.checked;
        InversionApp.loadMeta();
      });
    }
    const historySelect = document.getElementById('inversion-history-select');
    if (historySelect) {
      historySelect.addEventListener('change', (e) => {
        if (e.target.value) {
          InversionApp.loadResult(parseInt(e.target.value));
        }
      });
    }
  };

  InversionApp.apiUrl = function (path) {
    return `/api/projects/${ctx.projectId}${path}`;
  };

  InversionApp.loadMeta = async function () {
    const { ok, data } = await __apiJson(InversionApp.apiUrl('/inversion/param-ranges'));
    if (ok && data?.ok) {
      ctx.inversionParamRanges = data.param_ranges || [];
      ctx.inversionExperiments = (data.experiments || []).filter(
        (e) => e.is_multi_vessel === ctx.inversionIsMulti
      );
      InversionApp.renderParamRanges(ctx.inversionParamRanges);
      InversionApp.renderExperimentOptions(ctx.inversionExperiments);
    }
    InversionApp.loadHistory();
  };

  InversionApp.renderParamRanges = function (ranges) {
    const container = document.getElementById('inversion-param-ranges');
    if (!container) return;
    container.innerHTML = '';

    ranges.forEach((r) => {
      const row = document.createElement('div');
      row.className = 'inversion-param-row';
      row.innerHTML = `
        <div class="inversion-param-head">
          <label class="inversion-param-label">
            <input type="checkbox" class="inversion-param-enabled" data-param="${r.parameter}" ${r.enabled ? 'checked' : ''}>
            <span>${r.parameter_label}${r.unit ? ' (' + r.unit + ')' : ''}</span>
          </label>
        </div>
        <div class="inversion-param-inputs">
          <div class="inversion-input-group">
            <label>最小值</label>
            <input type="number" step="any" class="inversion-param-min" data-param="${r.parameter}" value="${r.min_value}">
          </div>
          <div class="inversion-input-group">
            <label>最大值</label>
            <input type="number" step="any" class="inversion-param-max" data-param="${r.parameter}" value="${r.max_value}">
          </div>
          <div class="inversion-input-group">
            <label>基准值</label>
            <input type="number" step="any" class="inversion-param-baseline" data-param="${r.parameter}" value="${r.baseline}" readonly>
          </div>
        </div>
      `;
      container.appendChild(row);
    });
  };

  InversionApp.renderExperimentOptions = function (experiments) {
    const select = document.getElementById('inversion-experiment-select');
    if (!select) return;
    select.innerHTML = '<option value="">自动选择最新完成的实验</option>';
    experiments.forEach((e) => {
      const opt = document.createElement('option');
      opt.value = e.id;
      const errText = e.total_error != null ? `，误差 ${e.total_error.toFixed(2)}%` : '';
      opt.textContent = `第 ${e.round_number} 轮${errText}`;
      select.appendChild(opt);
    });
  };

  InversionApp.loadHistory = async function () {
    const { ok, data } = await __apiJson(InversionApp.apiUrl('/inversion/results'));
    const select = document.getElementById('inversion-history-select');
    if (select) {
      select.innerHTML = '<option value="">— 选择历史反演结果 —</option>';
      if (ok && data?.ok && data.results?.length) {
        ctx.inversionResults = data.results;
        const filtered = data.results.filter((r) => r.is_multi_vessel === ctx.inversionIsMulti);
        filtered.forEach((r) => {
          const opt = document.createElement('option');
          opt.value = r.id;
          const r2 = r.r_squared != null ? ` R²=${r.r_squared.toFixed(4)}` : '';
          const date = r.created_at ? new Date(r.created_at).toLocaleString() : '';
          opt.textContent = `#${r.id} ${ALGO_LABELS[r.algorithm] || r.algorithm}${r2} — ${date}`;
          select.appendChild(opt);
        });
        if (filtered.length > 0) {
          const latest = filtered[0];
          InversionApp.loadResult(latest.id);
        }
      }
    }
  };

  InversionApp.collectCustomRanges = function () {
    const ranges = [];
    const enabledEls = document.querySelectorAll('.inversion-param-enabled');
    enabledEls.forEach((el) => {
      const param = el.dataset.param;
      const enabled = el.checked;
      const minEl = document.querySelector(`.inversion-param-min[data-param="${param}"]`);
      const maxEl = document.querySelector(`.inversion-param-max[data-param="${param}"]`);
      const baseEl = document.querySelector(`.inversion-param-baseline[data-param="${param}"]`);
      const meta = ctx.inversionParamRanges.find((r) => r.parameter === param) || {};
      ranges.push({
        parameter: param,
        parameter_label: PARAM_LABELS[param] || param,
        min_value: parseFloat(minEl?.value) ?? meta.min_value,
        max_value: parseFloat(maxEl?.value) ?? meta.max_value,
        baseline: parseFloat(baseEl?.value) ?? meta.baseline,
        enabled: enabled,
        unit: PARAM_UNITS[param] || ''
      });
    });
    return ranges;
  };

  InversionApp.runInversion = async function () {
    const customRanges = InversionApp.collectCustomRanges();
    const enabledCount = customRanges.filter((r) => r.enabled).length;
    if (enabledCount === 0) {
      __Toast.error('请至少启用一个扰动参数进行反演');
      return;
    }

    const errors = [];
    customRanges.forEach((r) => {
      if (!r.enabled) return;
      if (r.min_value == null || isNaN(r.min_value)) errors.push(`${r.parameter_label} 最小值无效`);
      if (r.max_value == null || isNaN(r.max_value)) errors.push(`${r.parameter_label} 最大值无效`);
      if (r.min_value > r.max_value) errors.push(`${r.parameter_label} 最小值不能大于最大值`);
    });
    if (errors.length) {
      __Toast.error(errors.join('<br>'));
      return;
    }

    const expSelect = document.getElementById('inversion-experiment-select');
    const algoSelect = document.getElementById('inversion-algorithm-select');
    const particleInput = document.getElementById('inversion-particles');
    const iterInput = document.getElementById('inversion-iterations');
    const gridInput = document.getElementById('inversion-grid-density');

    const experiment_id = expSelect?.value ? parseInt(expSelect.value) : null;
    const algorithm = algoSelect?.value || 'hybrid_pso_grid';
    const particle_count = parseInt(particleInput?.value || '30');
    const iteration_count = parseInt(iterInput?.value || '50');
    const grid_density = parseInt(gridInput?.value || '5');

    if (particle_count < 10 || particle_count > 200) {
      __Toast.error('粒子数必须在 10-200 之间');
      return;
    }
    if (iteration_count < 5 || iteration_count > 500) {
      __Toast.error('迭代次数必须在 5-500 之间');
      return;
    }
    if (grid_density < 2 || grid_density > 15) {
      __Toast.error('网格密度必须在 2-15 之间');
      return;
    }

    const btn = document.getElementById('inversion-run-btn');
    if (btn) { btn.disabled = true; btn.textContent = '反演计算中…（可能需要数秒到数十秒）'; }

    const payload = {
      experiment_id,
      is_multi_vessel: ctx.inversionIsMulti,
      algorithm,
      particle_count,
      iteration_count,
      grid_density,
      confidence_level: 0.95,
      custom_ranges: customRanges,
    };

    const { ok, data } = await __apiJson(InversionApp.apiUrl('/inversion/run'), {
      method: 'POST', body: payload,
    });

    if (btn) { btn.disabled = false; btn.textContent = '开始联合反演'; }

    if (ok && data?.ok) {
      __Toast.success('联合反演完成！');
      InversionApp.renderResult(data.result);
      InversionApp.loadHistory();
    } else {
      const err = data?.error || '反演失败，请检查配置';
      __Toast.error(err);
    }
  };

  InversionApp.loadResult = async function (resultId) {
    const { ok, data } = await __apiJson(`/api/inversion/results/${resultId}`);
    if (ok && data?.ok) {
      InversionApp.renderResult(data.result);
    }
  };

  InversionApp.renderResult = function (result) {
    ctx.currentInversionResult = result;
    InversionApp.renderOptimalParams(result);
    InversionApp.renderFitMetrics(result);
    InversionApp.renderConfidenceIntervals(result);
    InversionApp.renderTopCandidates(result);
    InversionApp.renderConvergence(result);
    InversionApp.renderAlignedChart(result);
    InversionApp.renderCalibrationAdvice(result);
    InversionApp.renderSummary(result);
  };

  InversionApp.renderOptimalParams = function (r) {
    const container = document.getElementById('inversion-optimal-params');
    if (!container) return;
    const params = [
      { key: 'temperature', label: '环境温度', value: r.optimal_temperature, unit: '°C' },
      { key: 'viscosity', label: '液体黏度', value: r.optimal_viscosity, unit: 'mPa·s', prefix: '×' },
      { key: 'inflow_amplitude', label: '注水波动幅度', value: r.optimal_inflow_amplitude, unit: '', pct: true },
      { key: 'orifice_wear', label: '孔径磨损程度', value: r.optimal_orifice_wear, unit: '', pct: true },
      { key: 'tilt_angle', label: '容器倾斜角度', value: r.optimal_tilt_angle, unit: '°' },
    ];
    container.innerHTML = params.map((p) => {
      const v = p.value != null ? Number(p.value).toFixed(4) : '—';
      const display = p.pct ? `${(Number(p.value) * 100).toFixed(2)}%` : `${p.prefix || ''}${v}${p.unit ? ' ' + p.unit : ''}`;
      return `
        <div class="optimal-param-card">
          <div class="optimal-param-label">${p.label}</div>
          <div class="optimal-param-value">${display}</div>
        </div>
      `;
    }).join('');
  };

  InversionApp.renderFitMetrics = function (r) {
    const container = document.getElementById('inversion-fit-metrics');
    if (!container) return;
    const r2 = r.r_squared != null ? Number(r.r_squared) : 0;
    let grade = '较差', gradeClass = 'grade-poor';
    if (r2 >= 0.95) { grade = '优秀'; gradeClass = 'grade-excellent'; }
    else if (r2 >= 0.85) { grade = '良好'; gradeClass = 'grade-good'; }
    else if (r2 >= 0.7) { grade = '一般'; gradeClass = 'grade-fair'; }

    container.innerHTML = `
      <div class="fit-metric-card ${gradeClass}">
        <div class="fit-metric-label">拟合等级</div>
        <div class="fit-metric-value">${grade}</div>
      </div>
      <div class="fit-metric-card">
        <div class="fit-metric-label">R² 决定系数</div>
        <div class="fit-metric-value">${r.r_squared != null ? Number(r.r_squared).toFixed(4) : '—'}</div>
      </div>
      <div class="fit-metric-card">
        <div class="fit-metric-label">RMSE (ml)</div>
        <div class="fit-metric-value">${r.rmse != null ? Number(r.rmse).toFixed(4) : '—'}</div>
      </div>
      <div class="fit-metric-card">
        <div class="fit-metric-label">最大误差</div>
        <div class="fit-metric-value">${r.best_fit_error != null ? Number(r.best_fit_error).toFixed(2) + '%' : '—'}</div>
      </div>
      <div class="fit-metric-card">
        <div class="fit-metric-label">平均误差</div>
        <div class="fit-metric-value">${r.avg_fit_error != null ? Number(r.avg_fit_error).toFixed(2) + '%' : '—'}</div>
      </div>
      <div class="fit-metric-card">
        <div class="fit-metric-label">误差标准差</div>
        <div class="fit-metric-value">${r.error_std != null ? Number(r.error_std).toFixed(4) : '—'}</div>
      </div>
    `;
  };

  InversionApp.renderConfidenceIntervals = function (r) {
    const container = document.getElementById('inversion-confidence-intervals');
    if (!container || !r.confidence_intervals?.length) {
      if (container) container.innerHTML = '<div class="empty-hint">暂无置信区间数据</div>';
      return;
    }
    container.innerHTML = r.confidence_intervals.map((ci) => {
      const mid = Number(ci.best);
      const lo = Number(ci.low);
      const hi = Number(ci.high);
      const range = Math.max(hi - lo, 1e-9);
      const minDisp = Math.min(lo, mid) - range * 0.1;
      const maxDisp = Math.max(hi, mid) + range * 0.1;
      const dispRange = maxDisp - minDisp;
      const loPct = ((lo - minDisp) / dispRange) * 100;
      const hiPct = ((hi - minDisp) / dispRange) * 100;
      const midPct = ((mid - minDisp) / dispRange) * 100;
      let display;
      if (ci.parameter === 'inflow_amplitude' || ci.parameter === 'orifice_wear') {
        display = {
          lo: (lo * 100).toFixed(2) + '%',
          best: (mid * 100).toFixed(2) + '%',
          hi: (hi * 100).toFixed(2) + '%'
        };
      } else {
        const u = ci.unit || '';
        display = {
          lo: lo.toFixed(3) + (u ? ' ' + u : ''),
          best: mid.toFixed(3) + (u ? ' ' + u : ''),
          hi: hi.toFixed(3) + (u ? ' ' + u : '')
        };
      }
      return `
        <div class="ci-row">
          <div class="ci-head">
            <span class="ci-label">${ci.parameter_label}</span>
            <span class="ci-width">区间宽度 ${Number(ci.width_percent).toFixed(1)}%</span>
          </div>
          <div class="ci-range-info">
            <span class="ci-bound ci-low">${display.lo}</span>
            <span class="ci-best">最优 ${display.best}</span>
            <span class="ci-bound ci-high">${display.hi}</span>
          </div>
          <div class="ci-bar-container">
            <div class="ci-bar" style="left:${loPct}%;width:${hiPct - loPct}%"></div>
            <div class="ci-marker" style="left:${midPct}%"></div>
          </div>
        </div>
      `;
    }).join('');
  };

  InversionApp.renderTopCandidates = function (r) {
    const container = document.getElementById('inversion-top-candidates');
    if (!container || !r.top_candidates?.length) {
      if (container) container.innerHTML = '<div class="empty-hint">暂无候选解</div>';
      return;
    }
    const rows = r.top_candidates.map((c) => `
      <tr>
        <td>#${c.rank}</td>
        <td>${Number(c.temperature).toFixed(2)}°C</td>
        <td>×${Number(c.viscosity).toFixed(3)}</td>
        <td>±${(Number(c.inflow_amplitude) * 100).toFixed(2)}%</td>
        <td>${(Number(c.orifice_wear) * 100).toFixed(2)}%</td>
        <td>${Number(c.tilt_angle).toFixed(2)}°</td>
        <td class="${Number(c.fit_error) < 2 ? 'text-green' : (Number(c.fit_error) < 5 ? 'text-amber' : 'text-red')}">${Number(c.fit_error).toFixed(4)}</td>
        <td>${Number(c.rmse).toFixed(4)}</td>
      </tr>
    `).join('');
    container.innerHTML = `
      <table class="inversion-table">
        <thead>
          <tr>
            <th>排名</th>
            <th>温度</th>
            <th>黏度</th>
            <th>注水波动</th>
            <th>孔径磨损</th>
            <th>倾斜角</th>
            <th>目标误差</th>
            <th>RMSE</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  };

  InversionApp.renderConvergence = function (r) {
    const container = document.getElementById('inversion-convergence-chart');
    if (!container || !r.convergence_history?.length) {
      if (container) container.innerHTML = '<div class="empty-hint">暂无收敛历史</div>';
      return;
    }
    const traceBest = {
      x: r.convergence_history.map((p) => p.iteration),
      y: r.convergence_history.map((p) => Number(p.best_error)),
      type: 'scatter',
      mode: 'lines+markers',
      name: '最优误差',
      line: { color: '#4A7C59', width: 2 },
      marker: { size: 4 }
    };
    const traceAvg = {
      x: r.convergence_history.map((p) => p.iteration),
      y: r.convergence_history.map((p) => Number(p.avg_error)),
      type: 'scatter',
      mode: 'lines',
      name: '平均误差',
      line: { color: '#8B6914', width: 2, dash: 'dash' }
    };
    const layout = {
      title: '优化收敛曲线',
      xaxis: { title: '迭代次数' },
      yaxis: { title: '目标函数值', type: 'log' },
      margin: { t: 40, r: 20, b: 50, l: 60 },
      height: 320,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      legend: { orientation: 'h' }
    };
    Plotly.newPlot(container, [traceBest, traceAvg], layout, { displayModeBar: false, responsive: true });
  };

  InversionApp.renderAlignedChart = function (r) {
    const container = document.getElementById('inversion-aligned-chart');
    if (!container || !r.aligned_experiment_points?.length) {
      if (container) container.innerHTML = '<div class="empty-hint">暂无拟合对比数据</div>';
      return;
    }
    const traceExp = {
      x: r.aligned_experiment_points.map((p) => p.time_point),
      y: r.aligned_experiment_points.map((p) => p.experiment_level),
      type: 'scatter',
      mode: 'markers+lines',
      name: '实测水位',
      line: { color: '#5C4033', width: 2 },
      marker: { size: 6, symbol: 'circle' }
    };
    const traceSim = {
      x: r.aligned_experiment_points.map((p) => p.time_point),
      y: r.aligned_experiment_points.map((p) => p.simulated_level),
      type: 'scatter',
      mode: 'lines',
      name: '最优拟合仿真',
      line: { color: '#4A7C59', width: 2.5, dash: 'solid' }
    };
    const traceErr = {
      x: r.aligned_experiment_points.map((p) => p.time_point),
      y: r.aligned_experiment_points.map((p) => p.level_difference),
      type: 'bar',
      name: '水位差 (ml)',
      yaxis: 'y2',
      marker: { color: p => (p.y > 0 ? '#C23B22' : '#2E86AB'), opacity: 0.6 }
    };
    const layout = {
      title: '真实实验 vs 最优仿真拟合',
      xaxis: { title: '时间（分钟）' },
      yaxis: { title: '水位（ml）' },
      yaxis2: { title: '水位差（ml）', overlaying: 'y', side: 'right' },
      margin: { t: 40, r: 60, b: 50, l: 60 },
      height: 380,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      legend: { orientation: 'h' }
    };
    Plotly.newPlot(container, [traceExp, traceSim, traceErr], layout, { displayModeBar: false, responsive: true });
  };

  InversionApp.renderCalibrationAdvice = function (r) {
    const container = document.getElementById('inversion-calibration-advice');
    if (!container || !r.calibration_advice?.length) {
      if (container) container.innerHTML = '<div class="empty-hint">暂无校准建议</div>';
      return;
    }
    container.innerHTML = r.calibration_advice.map((a) => {
      const priorityClass = { high: 'priority-high', medium: 'priority-medium', low: 'priority-low' }[a.priority] || 'priority-low';
      const priorityText = { high: '高', medium: '中', low: '低' }[a.priority] || '低';
      let currentDisp;
      if (a.parameter === 'inflow_amplitude' || a.parameter === 'orifice_wear') {
        currentDisp = (Number(a.current_estimated) * 100).toFixed(2) + '%';
      } else {
        const u = PARAM_UNITS[a.parameter] || '';
        currentDisp = Number(a.current_estimated).toFixed(3) + (u ? ' ' + u : '');
      }
      return `
        <div class="calibration-card ${priorityClass}">
          <div class="calibration-head">
            <span class="priority-badge">优先级：${priorityText}</span>
            <span class="calibration-category">${a.category}</span>
            <span class="calibration-param">${a.parameter_label}</span>
          </div>
          <div class="calibration-body">
            <div class="calibration-row"><strong>当前估计：</strong>${currentDisp}</div>
            <div class="calibration-row"><strong>推荐范围：</strong>${a.recommended_range}</div>
            <div class="calibration-row"><strong>改进措施：</strong>${a.action}</div>
            <div class="calibration-row"><strong>预期改善：</strong>约 ${Number(a.expected_improvement_percent).toFixed(1)}%</div>
            <div class="calibration-rationale">${a.rationale}</div>
          </div>
        </div>
      `;
    }).join('');
  };

  InversionApp.renderSummary = function (r) {
    const container = document.getElementById('inversion-summary');
    if (!container || !r.summary) return;
    container.innerHTML = r.summary.split('\n').map((line) => {
      if (line.startsWith('【高优先级校准】') || line.startsWith('【中优先级校准】')) {
        return `<div class="summary-heading">${line}</div>`;
      }
      if (line.startsWith('  · ')) {
        return `<div class="summary-item">${line.slice(4)}</div>`;
      }
      if (line.trim() === '') return `<div class="summary-spacer"></div>`;
      return `<div class="summary-line">${line}</div>`;
    }).join('');
  };

  global.__InversionApp = InversionApp;
})(window);
