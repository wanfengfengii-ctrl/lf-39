/* ============================================================
 * robustness.js — 环境扰动模拟与稳健性评估模块
 * ============================================================ */
(function (global) {
  'use strict';

  const RobustnessApp = {};
  let ctx = null;

  const PARAM_LABELS = {
    temperature: '环境温度',
    viscosity: '液体黏度',
    inflow_amplitude: '注水波动幅度',
    orifice_wear: '孔径磨损程度',
    tilt_angle: '容器倾斜角度'
  };

  RobustnessApp.init = function (context) {
    ctx = context;
    ctx.robustnessConfig = null;
    ctx.robustnessAssessment = null;
    ctx.robustnessScenarios = [];
    ctx.robustnessIsMulti = false;
    RobustnessApp.bindEvents();
    RobustnessApp.loadConfig();
  };

  RobustnessApp.bindEvents = function () {
    const runBtn = document.getElementById('robustness-run-btn');
    if (runBtn) {
      runBtn.addEventListener('click', () => RobustnessApp.runSimulation());
    }
    const saveCfgBtn = document.getElementById('robustness-save-config-btn');
    if (saveCfgBtn) {
      saveCfgBtn.addEventListener('click', () => RobustnessApp.saveConfig());
    }
    const multiToggle = document.getElementById('robustness-multi-toggle');
    if (multiToggle) {
      multiToggle.addEventListener('change', (e) => {
        ctx.robustnessIsMulti = e.target.checked;
        RobustnessApp.loadAssessment();
      });
    }
    const scenarioSelect = document.getElementById('robustness-scenario-select');
    if (scenarioSelect) {
      scenarioSelect.addEventListener('change', (e) => {
        if (e.target.value) {
          RobustnessApp.loadScenarioDetail(parseInt(e.target.value));
        }
      });
    }
  };

  RobustnessApp.apiUrl = function (path) {
    return `/api/projects/${ctx.projectId}${path}`;
  };

  RobustnessApp.loadConfig = async function () {
    const { ok, data } = await __apiJson(RobustnessApp.apiUrl('/robustness/config'));
    if (ok && data?.ok) {
      ctx.robustnessConfig = data.config;
      RobustnessApp.renderConfigForm(data.config);
    }
    RobustnessApp.loadAssessment();
  };

  RobustnessApp.renderConfigForm = function (cfg) {
    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el && val != null) el.value = val;
    };
    const setChecked = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.checked = !!val;
    };
    setVal('rb-temperature-min', cfg.temperature_min);
    setVal('rb-temperature-max', cfg.temperature_max);
    setVal('rb-temperature-baseline', cfg.temperature_baseline);
    setChecked('rb-temperature-enabled', cfg.temperature_enabled);

    setVal('rb-viscosity-min', cfg.viscosity_min);
    setVal('rb-viscosity-max', cfg.viscosity_max);
    setVal('rb-viscosity-baseline', cfg.viscosity_baseline);
    setChecked('rb-viscosity-enabled', cfg.viscosity_enabled);

    setVal('rb-inflow-amplitude', cfg.inflow_fluctuation_amplitude);
    setVal('rb-inflow-frequency', cfg.inflow_fluctuation_frequency);
    setChecked('rb-inflow-enabled', cfg.inflow_fluctuation_enabled);

    setVal('rb-orifice-wear-rate', cfg.orifice_wear_rate);
    setVal('rb-orifice-wear-max', cfg.orifice_wear_max);
    setChecked('rb-orifice-enabled', cfg.orifice_wear_enabled);

    setVal('rb-tilt-min', cfg.tilt_angle_min);
    setVal('rb-tilt-max', cfg.tilt_angle_max);
    setVal('rb-tilt-baseline', cfg.tilt_angle_baseline);
    setChecked('rb-tilt-enabled', cfg.tilt_enabled);

    setVal('rb-duration', cfg.simulation_duration);
    setVal('rb-timestep', cfg.time_step);
    setVal('rb-scenario-count', cfg.scenario_count);
  };

  RobustnessApp.saveConfig = async function () {
    const getVal = (id) => {
      const el = document.getElementById(id);
      return el ? parseFloat(el.value) : null;
    };
    const getChecked = (id) => {
      const el = document.getElementById(id);
      return el ? el.checked : false;
    };
    const payload = {
      temperature_min: getVal('rb-temperature-min'),
      temperature_max: getVal('rb-temperature-max'),
      temperature_baseline: getVal('rb-temperature-baseline'),
      temperature_enabled: getChecked('rb-temperature-enabled'),
      viscosity_min: getVal('rb-viscosity-min'),
      viscosity_max: getVal('rb-viscosity-max'),
      viscosity_baseline: getVal('rb-viscosity-baseline'),
      viscosity_enabled: getChecked('rb-viscosity-enabled'),
      inflow_fluctuation_amplitude: getVal('rb-inflow-amplitude'),
      inflow_fluctuation_frequency: getVal('rb-inflow-frequency'),
      inflow_fluctuation_enabled: getChecked('rb-inflow-enabled'),
      orifice_wear_rate: getVal('rb-orifice-wear-rate'),
      orifice_wear_max: getVal('rb-orifice-wear-max'),
      orifice_wear_enabled: getChecked('rb-orifice-enabled'),
      tilt_angle_min: getVal('rb-tilt-min'),
      tilt_angle_max: getVal('rb-tilt-max'),
      tilt_angle_baseline: getVal('rb-tilt-baseline'),
      tilt_enabled: getChecked('rb-tilt-enabled'),
      simulation_duration: getVal('rb-duration'),
      time_step: getVal('rb-timestep'),
      scenario_count: getVal('rb-scenario-count'),
    };
    const btn = document.getElementById('robustness-save-config-btn');
    if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
    const { ok, data } = await __apiJson(RobustnessApp.apiUrl('/robustness/config'), {
      method: 'POST', body: payload
    });
    if (btn) { btn.disabled = false; btn.textContent = '保存扰动配置'; }
    if (ok && data?.ok) {
      ctx.robustnessConfig = data.config;
      __Toast.success('扰动配置已保存');
    } else {
      __Toast.error(data?.error || '保存失败');
    }
  };

  RobustnessApp.runSimulation = async function () {
    await RobustnessApp.saveConfig();
    const btn = document.getElementById('robustness-run-btn');
    if (btn) { btn.disabled = true; btn.textContent = '模拟中，请稍候…'; }
    const isMulti = ctx.robustnessIsMulti;
    const scenarioCount = ctx.robustnessConfig?.scenario_count || 50;
    const { ok, data } = await __apiJson(RobustnessApp.apiUrl('/robustness/simulate'), {
      method: 'POST', body: { is_multi_vessel: isMulti, scenario_count: scenarioCount }
    });
    if (btn) { btn.disabled = false; btn.textContent = '▶ 运行批量模拟'; }
    if (ok && data?.ok) {
      __Toast.success(`模拟完成：${data.result.completed}/${data.result.total_scenarios} 个场景`);
      await RobustnessApp.loadAssessment();
    } else {
      __Toast.error(data?.error || '模拟失败');
    }
  };

  RobustnessApp.loadScenarios = async function () {
    const isMulti = ctx.robustnessIsMulti;
    const { ok, data } = await __apiJson(
      RobustnessApp.apiUrl(`/robustness/scenarios?is_multi_vessel=${isMulti}`)
    );
    if (ok && data?.ok) {
      ctx.robustnessScenarios = data.scenarios;
      RobustnessApp.renderScenarioList(data.scenarios);
    }
  };

  RobustnessApp.renderScenarioList = function (scenarios) {
    const sel = document.getElementById('robustness-scenario-select');
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 选择场景查看详情 --</option>' +
      scenarios.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
  };

  RobustnessApp.loadScenarioDetail = async function (scenarioId) {
    const { ok, data } = await __apiJson(`/api/robustness/scenarios/${scenarioId}`);
    if (ok && data?.ok) {
      RobustnessApp.renderScenarioDetail(data.detail);
    }
  };

  RobustnessApp.renderScenarioDetail = function (detail) {
    const scenario = detail.scenario;
    const container = document.getElementById('robustness-scenario-detail');
    if (!container) return;
    let html = `<div class="scenario-meta"><strong>${scenario.name}</strong>`;
    const parts = [];
    if (scenario.temperature != null) parts.push(`温度 ${scenario.temperature}°C`);
    if (scenario.viscosity != null) parts.push(`黏度 x${scenario.viscosity}`);
    if (scenario.inflow_amplitude != null) parts.push(`注水波动 ±${(scenario.inflow_amplitude*100).toFixed(0)}%`);
    if (scenario.orifice_wear != null) parts.push(`孔径磨损 ${(scenario.orifice_wear*100).toFixed(0)}%`);
    if (scenario.tilt_angle != null) parts.push(`倾斜 ${scenario.tilt_angle}°`);
    html += ` <span class="muted">${parts.join(' · ')}</span></div>`;
    container.innerHTML = html;

    if (detail.vessel_results) {
      const traces = [];
      const names = Object.keys(detail.vessel_results);
      names.forEach((name, idx) => {
        const pts = detail.vessel_results[name];
        const color = ['#5C4033','#4A7C59','#C23B22','#B8860B','#4E6BA0'][idx % 5];
        traces.push({
          x: pts.map(p => p.time_point),
          y: pts.map(p => p.water_level),
          type: 'scatter', mode: 'lines', name: `${name} 水位`,
          line: { color, width: 2 }
        });
        if (pts.some(p => p.expected_level != null)) {
          traces.push({
            x: pts.map(p => p.time_point),
            y: pts.map(p => p.expected_level),
            type: 'scatter', mode: 'lines', name: `${name} 理论值`,
            line: { color, width: 1, dash: 'dash' }
          });
        }
      });
      const layout = __makeChartLayout('各容器水位曲线', '时间(分)', '水位(ml)', 340);
      Plotly.newPlot('robustness-scenario-chart', traces, layout, { displayModeBar: false, responsive: true });
    } else if (detail.results && detail.results.length) {
      const pts = detail.results;
      const traces = [{
        x: pts.map(p => p.time_point),
        y: pts.map(p => p.water_level),
        type: 'scatter', mode: 'lines', name: '实际水位',
        line: { color: '#5C4033', width: 2 }
      }];
      if (pts.some(p => p.expected_level != null)) {
        traces.push({
          x: pts.map(p => p.time_point),
          y: pts.map(p => p.expected_level),
          type: 'scatter', mode: 'lines', name: '理论水位',
          line: { color: '#4A7C59', width: 1, dash: 'dash' }
        });
      }
      const layout = __makeChartLayout('单壶水位变化曲线', '时间(分)', '水位(ml)', 340);
      Plotly.newPlot('robustness-scenario-chart', traces, layout, { displayModeBar: false, responsive: true });
    }
  };

  RobustnessApp.loadAssessment = async function () {
    const isMulti = ctx.robustnessIsMulti;
    await RobustnessApp.loadScenarios();
    const { ok, data } = await __apiJson(
      RobustnessApp.apiUrl(`/robustness/assessment?is_multi_vessel=${isMulti}`)
    );
    if (ok && data?.ok) {
      ctx.robustnessAssessment = data.assessment;
      RobustnessApp.renderAssessment(data.assessment);
    } else {
      RobustnessApp.renderEmptyAssessment();
    }
  };

  RobustnessApp.renderEmptyAssessment = function () {
    const scoreEl = document.getElementById('rb-score');
    if (scoreEl) scoreEl.textContent = '--';
    const gradeEl = document.getElementById('rb-grade');
    if (gradeEl) gradeEl.textContent = '未评估';
    ['rb-avg-err','rb-max-err','rb-err-std','rb-fail-rate'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = '--';
    });
    const summary = document.getElementById('rb-summary');
    if (summary) summary.innerHTML = '<div class="placeholder-cell">请先点击"运行批量模拟"生成评估结果</div>';
    const sensContainer = document.getElementById('rb-sensitivity');
    if (sensContainer) sensContainer.innerHTML = '<div class="placeholder-cell">暂无敏感度数据</div>';
    const rankingContainer = document.getElementById('rb-ranking');
    if (rankingContainer) rankingContainer.innerHTML = '<div class="placeholder-cell">暂无参数排序</div>';
    const adviceContainer = document.getElementById('rb-advice');
    if (adviceContainer) adviceContainer.innerHTML = '<div class="placeholder-cell">暂无校准建议</div>';
    RobustnessApp.renderScenariosChart([]);
  };

  RobustnessApp.renderAssessment = function (assessment) {
    const score = assessment.overall_stability_score || 0;
    const scoreEl = document.getElementById('rb-score');
    if (scoreEl) {
      scoreEl.textContent = score.toFixed(1);
      scoreEl.style.color = score >= 70 ? 'var(--c-accent)' : (score >= 50 ? 'var(--c-warn)' : 'var(--c-danger)');
    }
    const gradeEl = document.getElementById('rb-grade');
    if (gradeEl) {
      let grade = '较差';
      if (score >= 85) grade = '优秀';
      else if (score >= 70) grade = '良好';
      else if (score >= 50) grade = '一般';
      gradeEl.textContent = grade;
    }
    const setText = (id, val, suffix = '') => {
      const el = document.getElementById(id);
      if (el) el.textContent = val != null ? val.toFixed(2) + suffix : '--';
    };
    setText('rb-avg-err', assessment.avg_error, '%');
    setText('rb-max-err', assessment.max_error, '%');
    setText('rb-err-std', assessment.error_std, '%');
    const failEl = document.getElementById('rb-fail-rate');
    if (failEl) failEl.textContent = assessment.failure_rate != null ? (assessment.failure_rate * 100).toFixed(1) + '%' : '--';

    const summary = document.getElementById('rb-summary');
    if (summary) {
      summary.innerHTML = `<div class="assessment-summary">${assessment.summary || ''}</div>`;
    }

    RobustnessApp.renderSensitivityChart(assessment.sensitivity_scores || []);
    RobustnessApp.renderParameterRanking(assessment.parameter_ranking || []);
    RobustnessApp.renderCalibrationAdvice(assessment.calibration_advice || []);
    RobustnessApp.renderScenariosChart(assessment.scenario_summaries || []);
  };

  RobustnessApp.renderSensitivityChart = function (scores) {
    const container = document.getElementById('rb-sensitivity');
    if (!container) return;
    if (!scores.length) {
      container.innerHTML = '<div class="placeholder-cell">暂无敏感度数据</div>';
      return;
    }
    const labels = scores.map(s => s.parameter_label);
    const values = scores.map(s => s.score);
    const colors = scores.map(s => s.score >= 50 ? 'rgba(194,59,34,0.8)' : (s.score >= 25 ? 'rgba(180,112,26,0.8)' : 'rgba(74,124,89,0.8)'));
    const trace = {
      x: values,
      y: labels,
      type: 'bar',
      orientation: 'h',
      marker: { color: colors },
      text: values.map(v => v.toFixed(1)),
      textposition: 'auto',
    };
    const layout = __makeChartLayout('参数敏感度评分', '敏感度得分', '', 240 + scores.length * 28);
    layout.xaxis.range = [0, 100];
    Plotly.newPlot('rb-sensitivity', [trace], layout, { displayModeBar: false, responsive: true });
  };

  RobustnessApp.renderParameterRanking = function (ranking) {
    const container = document.getElementById('rb-ranking');
    if (!container) return;
    if (!ranking.length) {
      container.innerHTML = '<div class="placeholder-cell">暂无参数排序</div>';
      return;
    }
    let html = '<table class="interval-error-table"><thead><tr><th>排名</th><th>参数</th><th>类别</th><th>敏感度</th><th>说明</th></tr></thead><tbody>';
    ranking.forEach(r => {
      html += `<tr>
        <td><strong>#${r.rank}</strong></td>
        <td>${r.parameter_label}</td>
        <td><span class="badge badge-subtle">${r.category}</span></td>
        <td>${r.sensitivity_score.toFixed(1)}</td>
        <td class="muted">${r.description}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  };

  RobustnessApp.renderCalibrationAdvice = function (advice) {
    const container = document.getElementById('rb-advice');
    if (!container) return;
    if (!advice.length) {
      container.innerHTML = '<div class="placeholder-cell">系统对当前扰动范围不敏感，无需特殊校准措施</div>';
      return;
    }
    let html = '';
    advice.forEach(a => {
      const pClass = a.priority === 'high' ? 'danger' : (a.priority === 'medium' ? 'warn' : 'subtle');
      const pLabel = a.priority === 'high' ? '高优先级' : (a.priority === 'medium' ? '中优先级' : '低优先级');
      html += `<div class="advice-card priority-${a.priority}">
        <div class="advice-header">
          <span class="badge badge-${pClass}">${pLabel}</span>
          <strong>${a.parameter_label}</strong>
          <span class="muted">预期改善 ${a.expected_improvement.toFixed(1)}%</span>
        </div>
        <div class="advice-action">${a.action}</div>
        <div class="advice-target">目标范围：${a.target_range}</div>
        <div class="advice-reason muted">${a.reason}</div>
      </div>`;
    });
    container.innerHTML = html;
  };

  RobustnessApp.renderScenariosChart = function (summaries) {
    const container = document.getElementById('rb-scenarios-chart');
    if (!container) return;
    if (!summaries.length) {
      container.innerHTML = '<div class="placeholder-cell">暂无场景数据</div>';
      return;
    }
    const sorted = [...summaries].sort((a, b) => a.avg_error - b.avg_error);
    const labels = sorted.map(s => s.name.length > 20 ? s.name.substring(0, 20) + '…' : s.name);
    const avgErrors = sorted.map(s => s.avg_error);
    const maxErrors = sorted.map(s => s.max_error);
    const colors = sorted.map(s => s.failed ? 'rgba(194,59,34,0.8)' : 'rgba(74,124,89,0.6)');
    const traces = [
      {
        x: labels, y: avgErrors, type: 'bar', name: '平均误差(%)',
        marker: { color: colors }
      },
      {
        x: labels, y: maxErrors, type: 'scatter', mode: 'markers',
        name: '最大误差(%)', marker: { color: '#C23B22', size: 8 }
      }
    ];
    const layout = __makeChartLayout('各场景误差对比', '场景', '误差(%)', 360);
    layout.xaxis.tickangle = -30;
    Plotly.newPlot('rb-scenarios-chart', traces, layout, { displayModeBar: false, responsive: true });
  };

  global.RobustnessApp = RobustnessApp;
})(window);
