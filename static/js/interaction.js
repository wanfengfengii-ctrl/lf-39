/* ============================================================
 * interaction.js — 全局交互逻辑、API 调用、状态管理
 * ============================================================ */
(function (global) {
  'use strict';

  const Toast = {
    show(message, type = 'info', duration = 2800) {
      const box = document.getElementById('toast-container');
      if (!box) return;
      const el = document.createElement('div');
      el.className = `toast ${type}`;
      el.textContent = message;
      box.appendChild(el);
      setTimeout(() => {
        el.classList.add('fade-out');
        setTimeout(() => el.remove(), 260);
      }, duration);
    },
    success(m) { this.show(m, 'success'); },
    error(m) { this.show(m, 'error'); },
    warn(m) { this.show(m, 'warn'); }
  };
  global.__Toast = Toast;

  async function apiJson(url, options = {}) {
    const resp = await fetch(url, {
      headers: { 'Accept': 'application/json' },
      ...options,
      body: options.body instanceof FormData || options.body == null
        ? options.body
        : (typeof options.body === 'string' ? options.body : JSON.stringify(options.body))
    });
    let payload = null;
    try { payload = await resp.json(); } catch (_) {}
    return { ok: resp.ok, status: resp.status, data: payload };
  }

  async function submitForm(url, formEl) {
    const body = new FormData(formEl);
    return apiJson(url, { method: 'POST', body });
  }

  /* ---------- Collapsible panels ---------- */
  function initCollapsible() {
    document.querySelectorAll('.collapsible .panel-header[data-toggle]').forEach(h => {
      h.addEventListener('click', () => {
        const card = h.closest('.collapsible');
        if (card) card.classList.toggle('open');
      });
    });
  }

  /* ---------- Delete project ---------- */
  function initDeleteProject(projectId) {
    const btn = document.getElementById('delete-project-btn');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      if (!confirm('确认删除此项目？所有实验数据将被永久删除。')) return;
      const { ok } = await apiJson(`/api/projects/${projectId}`, { method: 'DELETE' });
      if (ok) {
        Toast.success('项目已删除');
        setTimeout(() => location.assign('/'), 600);
      } else {
        Toast.error('删除失败，请重试');
      }
    });
  }

  /* ---------- Config form ---------- */
  function initConfigForm(ctx) {
    const form = document.getElementById('config-form');
    if (!form) return;
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!ClepsydraForms.validateConfigForm(form)) return;
      const submitBtn = form.querySelector('button[type="submit"]');
      const originalLabel = submitBtn.textContent;
      submitBtn.disabled = true; submitBtn.textContent = '保存中…';
      try {
        const { status, data } = await submitForm(`/api/projects/${ctx.projectId}/config`, form);
        if (status === 422) {
          Toast.error(data?.error || '参数有误');
          return;
        }
        if (data?.ok) {
          if (data.params_changed) {
            Toast.warn('结构参数已更新，所有历史实验结论已标记为「待复核」');
          } else {
            Toast.success('结构配置已保存');
          }
          ctx.config = data.config;
          ctx.capacity = data.config.capacity;
          ctx.targetDuration = data.config.target_duration;
          document.getElementById('water_level').max = ctx.capacity;
          document.querySelector('#water_level').placeholder = `≤${ctx.capacity} ml`;
          setTimeout(() => location.reload(), 650);
        } else {
          Toast.error(data?.error || '保存失败');
        }
      } catch (err) {
        Toast.error('网络错误，保存失败');
      } finally {
        submitBtn.disabled = false; submitBtn.textContent = originalLabel;
      }
    });
  }

  /* ---------- Scale designer ---------- */
  function initScaleDesigner(ctx) {
    const tbody = document.getElementById('scale-tbody');
    const countInput = document.getElementById('scale-count-input');
    const regenBtn = document.getElementById('regen-scale-btn');
    const form = document.getElementById('scale-form');
    if (!tbody || !ctx.config) return;

    const render = (marks) => {
      tbody.innerHTML = '';
      marks.forEach((m, i) => {
        const tr = document.createElement('tr');
        tr.dataset.index = m.mark_index ?? i;
        tr.innerHTML = `
          <td>#${m.mark_index ?? i}</td>
          <td><input type="number" step="0.01" min="0" class="target-time" value="${m.target_time}"></td>
          <td><input type="number" step="0.01" min="0.01" class="target-water" value="${m.target_water_level}"></td>
        `;
        tbody.appendChild(tr);
      });
      syncScaleVisual(marks);
    };

    const syncScaleVisual = (marks) => {
      const vis = document.getElementById('scale-visual');
      if (!vis || !ctx.config) return;
      vis.innerHTML = '';
      const capacity = ctx.config.capacity;
      marks.forEach(m => {
        const pct = Math.max(0, Math.min(100, (m.target_water_level / capacity) * 100));
        const div = document.createElement('div');
        div.className = 'scale-mark-line';
        div.style.left = pct + '%';
        div.innerHTML = `<div class="tick"></div><div class="mark-label">#${m.mark_index}<br>${m.target_time}分</div>`;
        vis.appendChild(div);
      });
    };

    const regenerate = () => {
      const n = Math.max(2, Math.min(60, parseInt(countInput.value || '11', 10)));
      const marks = [];
      const duration = ctx.config.target_duration;
      const capacity = ctx.config.capacity;
      for (let i = 0; i < n; i++) {
        const ratio = i / (n - 1);
        marks.push({
          mark_index: i,
          target_time: +(duration * ratio).toFixed(2),
          target_water_level: +(capacity * (1 - ratio)).toFixed(2)
        });
      }
      render(marks);
    };

    render((ctx.scheme && ctx.scheme.marks) || []);
    if (regenBtn) regenBtn.addEventListener('click', regenerate);
    if (countInput) countInput.addEventListener('change', regenerate);

    tbody.addEventListener('input', () => {
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const marks = rows.map((tr, i) => ({
        mark_index: parseInt(tr.dataset.index, 10) || i,
        target_time: parseFloat(tr.querySelector('.target-time').value) || 0,
        target_water_level: parseFloat(tr.querySelector('.target-water').value) || 0
      }));
      syncScaleVisual(marks);
    });

    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const { ok, marks } = ClepsydraForms.validateScaleTable(tbody, ctx.config.capacity);
        if (!ok) {
          const extraMsg = window.__scale_first_time_error
            ? '；' + window.__scale_first_time_error
            : '';
          Toast.error('刻度数据有误：请检查时间必须递增、水位必须在容量范围内' + extraMsg);
          return;
        }
        const btn = form.querySelector('button[type="submit"]');
        const label = btn.textContent;
        btn.disabled = true; btn.textContent = '保存中…';
        try {
          const { data } = await apiJson(`/api/projects/${ctx.projectId}/scale`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: { marks }
          });
          if (data?.ok) {
            Toast.success('刻度方案已保存');
            ctx.scheme = data.scheme;
            if (data.scheme?.marks) render(data.scheme.marks);
            ClepsydraCharts.renderWaterLevel('water-level-chart',
              ctx.experiments, ctx.scheme, ctx.config, ctx.selectedExperimentIds);
          } else {
            Toast.error(data?.error || '保存失败');
          }
        } finally {
          btn.disabled = false; btn.textContent = label;
        }
      });
    }
  }

  /* ---------- Experiments ---------- */
  function roundStatusText(s) {
    if (s === 'recording') return '采集中';
    if (s === 'finalized') return '已完成';
    return s;
  }

  function initExperiments(ctx) {
    const tabsBox = document.getElementById('round-tabs');
    const summary = document.getElementById('current-exp-summary');
    const recordsTbody = document.getElementById('records-tbody');
    const recordForm = document.getElementById('record-form');
    const finalizeBtn = document.getElementById('finalize-btn');
    const toggleRecheckBtn = document.getElementById('toggle-recheck-btn');
    const compareBox = document.getElementById('compare-checkboxes');

    const renderTabs = () => {
      if (!tabsBox) return;
      tabsBox.innerHTML = '';
      if (ctx.experiments.length === 0) {
        const span = document.createElement('span');
        span.className = 'hint-empty';
        span.textContent = '尚未开始任何实验';
        tabsBox.appendChild(span);
        return;
      }
      ctx.experiments.forEach(e => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'round-tab' + (e.id === ctx.currentExpId ? ' active' : '');
        btn.dataset.expId = e.id;
        btn.innerHTML = `
          <span>第${e.round_number}轮</span>
          ${e.needs_recheck ? '<span class="tab-dot warn" title="待复核"></span>' : ''}
          ${e.status === 'recording' ? '<span class="tab-dot recording" title="采集中"></span>' :
            e.status === 'finalized' ? '<span class="tab-dot done" title="已完成"></span>' : ''}
        `;
        btn.addEventListener('click', () => {
          ctx.currentExpId = e.id;
          ctx.selectedExperimentIds = [e.id];
          renderAll();
        });
        tabsBox.appendChild(btn);
      });
    };

    const current = () => ctx.experiments.find(e => e.id === ctx.currentExpId) || null;

    const renderSummary = () => {
      if (!summary) return;
      const e = current();
      if (!e) { summary.innerHTML = '<span class="hint-empty">请先创建新一轮实验</span>'; return; }
      const n = e.records.length;
      const last = n > 0 ? e.records[n - 1] : null;
      summary.innerHTML = `
        <div class="summary-item"><span class="summary-label">状态</span><span class="summary-value">${roundStatusText(e.status)}</span></div>
        <div class="summary-item"><span class="summary-label">已录入节点</span><span class="summary-value">${n}</span></div>
        <div class="summary-item"><span class="summary-label">最后节点</span><span class="summary-value">${last ? `${last.time_point}分 / ${last.water_level}ml` : '—'}</span></div>
      `;
    };

    const renderRecords = () => {
      if (!recordsTbody) return;
      recordsTbody.innerHTML = '';
      const e = current();
      if (!e || e.records.length === 0) {
        recordsTbody.innerHTML = `<tr><td colspan="5" class="placeholder-cell">尚未录入数据</td></tr>`;
        return;
      }
      e.records.forEach(r => {
        const tr = document.createElement('tr');
        const exceeded = r.time_error != null && Math.abs(r.time_error) > (ctx.errorThreshold || 5);
        if (exceeded) tr.classList.add('row-danger');
        tr.innerHTML = `
          <td>${r.time_point}</td>
          <td>${r.water_level}</td>
          <td>${r.computed_flow_rate != null ? r.computed_flow_rate.toFixed(3) : '—'}</td>
          <td class="error-cell ${r.time_error < 0 ? 'negative' : ''} ${exceeded ? 'exceeded' : ''}">
            ${r.time_error != null ? (r.time_error > 0 ? '+' : '') + r.time_error.toFixed(2) + '%' : '—'}
          </td>
          <td>
            ${e.status === 'recording'
              ? `<button type="button" class="btn-icon-delete" data-record-id="${r.id}" title="删除">✕</button>`
              : ''}
          </td>
        `;
        recordsTbody.appendChild(tr);
      });

      recordsTbody.querySelectorAll('.btn-icon-delete').forEach(btn => {
        btn.addEventListener('click', async () => {
          const rid = parseInt(btn.dataset.recordId, 10);
          if (!confirm(`删除第${e.round_number}轮中该时间节点记录？`)) return;
          const { data } = await apiJson(`/api/projects/${ctx.projectId}/experiments/${e.id}/records/${rid}`, {
            method: 'DELETE'
          });
          if (data?.ok) {
            e.records = e.records.filter(r => r.id !== rid);
            Toast.success('已删除该记录');
            renderAll();
          } else {
            Toast.error(data?.error || '删除失败');
          }
        });
      });
    };

    const renderComparePicker = () => {
      if (!compareBox) return;
      compareBox.innerHTML = '';
      if (ctx.experiments.length === 0) return;
      ctx.experiments.forEach(e => {
        const label = document.createElement('label');
        const checked = ctx.selectedExperimentIds.includes(e.id);
        label.innerHTML = `
          <input type="checkbox" data-exp-id="${e.id}" ${checked ? 'checked' : ''}>
          第${e.round_number}轮
        `;
        const input = label.querySelector('input');
        input.addEventListener('change', () => {
          const ids = Array.from(compareBox.querySelectorAll('input:checked'))
            .map(i => parseInt(i.dataset.expId, 10));
          ctx.selectedExperimentIds = ids;
          ClepsydraCharts.renderWaterLevel(
            'water-level-chart',
            ctx.experiments, ctx.scheme, ctx.config, ids
          );
        });
        compareBox.appendChild(label);
      });
    };

    const renderCharts = () => {
      ClepsydraCharts.renderWaterLevel(
        'water-level-chart',
        ctx.experiments, ctx.scheme, ctx.config, ctx.selectedExperimentIds
      );
      if (current() && current().status === 'finalized') {
        loadAndRenderAnalysis();
      } else {
        renderAnalysisPlaceholder();
      }
    };

    const renderAnalysisPlaceholder = () => {
      document.getElementById('kpi-avg').textContent = '--';
      document.getElementById('kpi-max').textContent = '--';
      document.getElementById('kpi-exceed').textContent = '--';
      document.getElementById('kpi-threshold').textContent = `±${ctx.errorThreshold}%`;
      ClepsydraCharts.renderErrorBars('error-bar-chart', null);
      const tbody = document.getElementById('interval-error-tbody');
      if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="placeholder-cell">完成一轮实验后显示分析结果</td></tr>`;
      const recs = document.getElementById('recommendations-list');
      if (recs) recs.innerHTML = `<div class="placeholder-cell">暂无超差区间，无需调整</div>`;
      const meta = document.getElementById('analysis-meta');
      if (meta) meta.textContent = '';
    };

    const loadAndRenderAnalysis = async () => {
      const e = current();
      if (!e) return;
      const { data } = await apiJson(`/api/projects/${ctx.projectId}/analysis?exp_id=${e.id}`);
      if (data?.ok && data.analysis) renderAnalysis(data.analysis);
    };

    const renderAnalysis = (analysis) => {
      document.getElementById('kpi-avg').textContent = analysis.avg_error + '%';
      document.getElementById('kpi-max').textContent = '±' + analysis.max_error + '%';
      const exceeded = (analysis.interval_errors || []).filter(i => i.exceeded).length;
      const exceedEl = document.getElementById('kpi-exceed');
      exceedEl.textContent = exceeded;
      exceedEl.classList.toggle('danger', exceeded > 0);
      document.getElementById('kpi-threshold').textContent = `±${analysis.threshold_percent}%`;

      const meta = document.getElementById('analysis-meta');
      if (meta) {
        const e = current();
        if (e) meta.textContent = `当前分析：第${e.round_number}轮 ${e.needs_recheck ? '· ⚠ 待复核' : ''}`;
      }

      ClepsydraCharts.renderErrorBars('error-bar-chart', analysis);

      const tbody = document.getElementById('interval-error-tbody');
      if (tbody) {
        const items = analysis.interval_errors || [];
        if (items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="6" class="placeholder-cell">无区间数据</td></tr>`;
        } else {
          tbody.innerHTML = items.map(i => `
            <tr class="${i.exceeded ? 'row-exceed' : ''}">
              <td>${i.interval}</td>
              <td>${i.start_time} – ${i.end_time}</td>
              <td>${i.expected_level}</td>
              <td>${i.actual_level}</td>
              <td class="error-cell ${i.error > 0 ? 'positive' : 'negative'}">${i.error > 0 ? '+' : ''}${i.error}</td>
              <td class="error-cell ${i.error_percent > 0 ? 'positive' : 'negative'} ${i.exceeded ? 'exceeded' : ''}">
                ${i.error_percent > 0 ? '+' : ''}${i.error_percent}%${i.exceeded ? ' ⚠' : ''}
              </td>
            </tr>
          `).join('');
        }
      }

      const recs = document.getElementById('recommendations-list');
      if (recs) {
        const items = analysis.adjustment_recommendations || [];
        if (items.length === 0) {
          recs.innerHTML = `<div class="placeholder-cell">各区间误差均在阈值内，当前刻度方案合理</div>`;
        } else {
          const seen = new Set();
          const uniq = items.filter(r => !seen.has(r.mark_index) && seen.add(r.mark_index));
          recs.innerHTML = uniq.map(r => `
            <div class="recommendation-item">
              <div class="rec-icon">${r.mark_index}</div>
              <div class="rec-body">
                <div class="rec-title">刻度 #${r.mark_index}（目标 ${r.target_time} 分钟）建议 ${r.direction}</div>
                <div class="rec-reason">${r.reason}</div>
              </div>
              <div class="rec-action">
                原 ${r.original_level} →<br><b>${r.suggested_level} ml</b>
              </div>
            </div>
          `).join('');
        }
      }
    };

    const renderFooterButtons = () => {
      const e = current();
      if (finalizeBtn) {
        const recording = e && e.status === 'recording';
        finalizeBtn.disabled = !(recording && e.records.length >= 2);
        finalizeBtn.title = !e ? '请选择实验' :
          (e.status !== 'recording' ? '已完成' :
            (e.records.length < 2 ? '至少需要 2 个时间节点' : '完成本轮并分析误差'));
      }
      if (toggleRecheckBtn) {
        if (e && e.status === 'finalized') {
          toggleRecheckBtn.style.display = '';
          toggleRecheckBtn.textContent = e.needs_recheck ? '✓ 标记为已复核' : '⚠ 标记为待复核';
        } else {
          toggleRecheckBtn.style.display = 'none';
        }
      }
    };

    const renderAll = () => {
      renderTabs();
      renderSummary();
      renderRecords();
      renderComparePicker();
      renderFooterButtons();
      renderCharts();
    };

    /* 初始状态：选中最后一轮 */
    if (ctx.experiments.length > 0 && !ctx.currentExpId) {
      ctx.currentExpId = ctx.experiments[ctx.experiments.length - 1].id;
      ctx.selectedExperimentIds = [ctx.currentExpId];
    }
    renderAll();

    /* 记录表单 */
    if (recordForm) {
      recordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const cur = current();
        if (!cur) { Toast.warn('请先创建新一轮实验'); return; }
        if (cur.status !== 'recording') { Toast.warn('此轮实验已完成，无法继续录入'); return; }

        const existingTimes = cur.records.map(r => r.time_point);
        const lastTime = existingTimes.length ? existingTimes[existingTimes.length - 1] : null;
        const vctx = {
          capacity: ctx.capacity,
          lastTime,
          existingTimes
        };
        if (!ClepsydraForms.validateRecordForm(recordForm, vctx)) return;

        const btn = recordForm.querySelector('button[type="submit"]');
        const label = btn.textContent;
        btn.disabled = true; btn.textContent = '录入中…';
        try {
          const { data } = await submitForm(
            `/api/projects/${ctx.projectId}/experiments/${cur.id}/records`,
            recordForm
          );
          if (data?.ok) {
            Toast.success(`已录入节点：${data.record.time_point} 分 / ${data.record.water_level} ml`);
            cur.records.push(data.record);
            recordForm.reset();
            renderAll();
          } else {
            Toast.error(data?.error || '录入失败');
          }
        } finally {
          btn.disabled = false; btn.textContent = label;
        }
      });
    }

    /* 完成本轮 */
    if (finalizeBtn) {
      finalizeBtn.addEventListener('click', async () => {
        const cur = current();
        if (!cur) return;
        if (cur.records.length < 2) { Toast.warn('至少录入 2 个节点才能完成分析'); return; }
        if (!confirm('确认结束本轮实验？结束后无法继续录入数据，系统将自动计算误差并给出调整建议。')) return;
        finalizeBtn.disabled = true;
        try {
          const { data } = await apiJson(
            `/api/projects/${ctx.projectId}/experiments/${cur.id}/finalize`,
            { method: 'POST' }
          );
          if (data?.ok) {
            cur.status = 'finalized';
            cur.total_error = data.avg_error;
            cur.records = data.records || cur.records;
            if (data.project_status) {
              ctx.project.status = data.project_status;
              const topBadge = document.querySelector('.project-topbar .status-badge');
              if (topBadge) {
                const statusMap = {
                  draft: '草稿', configured: '已配置', ready: '待实验',
                  experimenting: '实验中', completed: '已完成'
                };
                topBadge.className = 'status-badge status-' + data.project_status;
                topBadge.textContent = statusMap[data.project_status] || data.project_status;
              }
              const project = document.querySelector('.project-topbar');
            }
            Toast.success(`实验分析完成 · 平均误差 ${data.avg_error}%（${data.record_count} 个节点）`);
            renderAll();
          } else {
            Toast.error(data?.error || '分析失败');
          }
        } finally {
          finalizeBtn.disabled = false;
        }
      });
    }

    /* 切换待复核 */
    if (toggleRecheckBtn) {
      toggleRecheckBtn.addEventListener('click', async () => {
        const cur = current();
        if (!cur) return;
        const newVal = !cur.needs_recheck;
        const { data } = await apiJson(
          `/api/projects/${ctx.projectId}/experiments/${cur.id}/recheck`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: { needs_recheck: newVal } }
        );
        if (data?.ok) {
          cur.needs_recheck = newVal;
          Toast.success(newVal ? '已标记为待复核' : '已确认复核通过');
          renderAll();
        } else {
          Toast.error(data?.error || '操作失败');
        }
      });
    }
  }

  /* ---------- App init ---------- */
  const ClepsydraApp = {};
  ClepsydraApp.initProjectDetail = function () {
    initCollapsible();

    const raw = global.__APP_DATA__ || {};
    const ctx = {
      projectId: raw.project?.id,
      project: raw.project,
      config: raw.config,
      scheme: raw.scheme,
      experiments: raw.experiments || [],
      capacity: raw.config?.capacity,
      targetDuration: raw.config?.target_duration,
      errorThreshold: raw.errorThreshold || 5.0,
      currentExpId: null,
      selectedExperimentIds: []
    };

    if (!ctx.projectId) return;

    initDeleteProject(ctx.projectId);
    initConfigForm(ctx);
    initScaleDesigner(ctx);
    initExperiments(ctx);

    global.__CTX__ = ctx;
  };

  /* 首页初始化 */
  if (document.getElementById('new-project-form')) {
    initCollapsible();
  }
  if (document.querySelector('.index-hero')) {
    initCollapsible();
  }

  global.ClepsydraApp = ClepsydraApp;
  global.__apiJson = apiJson;
  global.__submitForm = submitForm;
})(window);
