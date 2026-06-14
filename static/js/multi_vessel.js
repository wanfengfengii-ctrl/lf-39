/* ============================================================
 * multi_vessel.js — 多级漏刻联动校准：UI 交互与数据管理
 * ============================================================ */
(function (global) {
  'use strict';

  const MultiVesselApp = {};

  /* ---------- 工具函数 ---------- */
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

  /* ---------- 容器配置管理 ---------- */
  function initVesselConfig(ctx) {
    const vesselsList = document.getElementById('vessels-list');
    const addVesselBtn = document.getElementById('add-vessel-btn');
    const vesselModal = document.getElementById('vessel-modal');
    const vesselForm = document.getElementById('vessel-form');

    if (!vesselsList) return;

    const renderVessels = () => {
      const vessels = ctx.multiConfig?.vessels || [];
      if (vessels.length === 0) {
        vesselsList.innerHTML = `
          <div class="placeholder-cell small">
            尚未配置容器，点击「＋ 添加容器」开始配置多级漏刻结构
          </div>`;
        return;
      }

      const sorted = [...vessels].sort((a, b) => a.level_index - b.level_index);
      vesselsList.innerHTML = sorted.map(v => `
        <div class="vessel-card" data-vessel-id="${v.id}">
          <div class="vessel-card-header">
            <div class="vessel-name">${v.name}</div>
            <div class="vessel-badge role-${v.role}">第${v.level_index}级 · ${roleLabel(v.role)}</div>
          </div>
          <div class="vessel-card-body">
            <div class="vessel-meta-row">
              <span>容量：${v.capacity} ml</span>
              <span>孔径：${v.outlet_diameter} mm</span>
            </div>
            <div class="vessel-meta-row">
              <span>进水：${inletLabel(v.water_inlet_type)}</span>
              <span>时长：${v.target_duration || '—'} 分</span>
            </div>
          </div>
          <div class="vessel-card-actions">
            <button class="btn btn-sm btn-secondary" data-action="edit-vessel" data-id="${v.id}">编辑</button>
            <button class="btn btn-sm btn-ghost" data-action="scale-vessel" data-id="${v.id}">刻度</button>
            <button class="btn btn-sm btn-danger-ghost" data-action="delete-vessel" data-id="${v.id}">删除</button>
          </div>
        </div>
      `).join('');

      vesselsList.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          const action = btn.dataset.action;
          const id = parseInt(btn.dataset.id, 10);
          if (action === 'edit-vessel') openVesselModal(id);
          else if (action === 'delete-vessel') deleteVessel(id);
          else if (action === 'scale-vessel') openScalePanel(id);
        });
      });
    };

    const roleLabel = (r) => {
      const map = { top: '上壶', middle: '中壶', bottom: '下壶', reservoir: '蓄水池' };
      return map[r] || r;
    };

    const inletLabel = (t) => {
      const map = { gravity: '重力式', constant: '恒压式', manual: '人工' };
      return map[t] || t;
    };

    const openVesselModal = (vesselId) => {
      const modal = document.getElementById('vessel-modal');
      const form = document.getElementById('vessel-form');
      const title = document.getElementById('vessel-modal-title');
      if (!modal || !form) return;

      const vessel = vesselId
        ? (ctx.multiConfig?.vessels || []).find(v => v.id === vesselId)
        : null;

      title.textContent = vessel ? '编辑容器' : '添加容器';
      form.dataset.vesselId = vesselId || '';

      form.level_index.value = vessel ? vessel.level_index :
        ((ctx.multiConfig?.vessels?.length || 0));
      form.name.value = vessel ? vessel.name : '';
      form.role.value = vessel ? vessel.role : 'middle';
      form.capacity.value = vessel ? vessel.capacity : 500;
      form.water_inlet_type.value = vessel ? vessel.water_inlet_type : 'gravity';
      form.outlet_diameter.value = vessel ? vessel.outlet_diameter : 3;
      form.target_duration.value = vessel ? (vessel.target_duration || 60) : 60;
      form.initial_level.value = vessel ? (vessel.initial_level || '') : '';

      modal.style.display = 'flex';
    };

    const closeVesselModal = () => {
      const modal = document.getElementById('vessel-modal');
      if (modal) modal.style.display = 'none';
    };

    const deleteVessel = async (vesselId) => {
      if (!confirm('确认删除此容器？相关刻度和实验记录将被删除。')) return;
      const { data } = await apiJson(
        `/api/projects/${ctx.projectId}/multi-vessel/vessels/${vesselId}`,
        { method: 'DELETE' }
      );
      if (data?.ok) {
        __Toast.success('已删除容器');
        await reloadMultiConfig(ctx);
        renderVessels();
      } else {
        __Toast.error(data?.error || '删除失败');
      }
    };

    const openScalePanel = (vesselId) => {
      ctx.currentVesselId = vesselId;
      loadVesselScale(ctx, vesselId);
      const tab = document.querySelector('[data-tab="vessel-scale"]');
      if (tab) tab.click();
    };

    if (addVesselBtn) {
      addVesselBtn.addEventListener('click', () => openVesselModal(null));
    }

    if (vesselModal) {
      vesselModal.querySelector('.modal-close')?.addEventListener('click', closeVesselModal);
      vesselModal.addEventListener('click', (e) => {
        if (e.target === vesselModal) closeVesselModal();
      });
    }

    if (vesselForm) {
      vesselForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const vesselId = vesselForm.dataset.vesselId;
        const payload = {
          level_index: parseInt(vesselForm.level_index.value, 10),
          name: vesselForm.name.value.trim(),
          role: vesselForm.role.value,
          capacity: parseFloat(vesselForm.capacity.value),
          water_inlet_type: vesselForm.water_inlet_type.value,
          outlet_diameter: parseFloat(vesselForm.outlet_diameter.value),
          target_duration: parseFloat(vesselForm.target_duration.value) || null,
          initial_level: vesselForm.initial_level.value ? parseFloat(vesselForm.initial_level.value) : null,
        };

        const url = vesselId
          ? `/api/projects/${ctx.projectId}/multi-vessel/vessels/${vesselId}`
          : `/api/projects/${ctx.projectId}/multi-vessel/vessels`;
        const method = vesselId ? 'PUT' : 'POST';

        const { data } = await apiJson(url, {
          method,
          headers: { 'Content-Type': 'application/json' },
          body: payload
        });

        if (data?.ok) {
          __Toast.success(vesselId ? '已更新容器' : '已添加容器');
          closeVesselModal();
          await reloadMultiConfig(ctx);
          renderVessels();
        } else {
          __Toast.error(data?.error || '保存失败');
        }
      });
    }

    renderVessels();
    ctx.renderVessels = renderVessels;
  }

  /* ---------- 流量关系配置 ---------- */
  function initFlowRelations(ctx) {
    const relationsList = document.getElementById('relations-list');
    const addRelationBtn = document.getElementById('add-relation-btn');
    const relationModal = document.getElementById('relation-modal');
    const relationForm = document.getElementById('relation-form');

    if (!relationsList) return;

    const renderRelations = () => {
      const vessels = ctx.multiConfig?.vessels || [];
      const relations = ctx.multiConfig?.flow_relations || [];

      if (vessels.length < 2) {
        relationsList.innerHTML = `
          <div class="placeholder-cell small">
            至少需要 2 个容器才能配置流量关系
          </div>`;
        return;
      }

      if (relations.length === 0) {
        relationsList.innerHTML = `
          <div class="placeholder-cell small">
            尚未配置流量关系，点击「＋ 添加关系」配置级间传递
          </div>`;
        return;
      }

      const vMap = {};
      vessels.forEach(v => { vMap[v.id] = v; });

      relationsList.innerHTML = relations.map(r => {
        const up = vMap[r.upstream_vessel_id];
        const down = vMap[r.downstream_vessel_id];
        const typeMap = { series: '串联', parallel: '并联', bypass: '旁通' };
        return `
          <div class="relation-card" data-relation-id="${r.id}">
            <div class="relation-flow">
              <span class="vessel-chip">${up?.name || '?'}</span>
              <span class="relation-arrow">→</span>
              <span class="vessel-chip">${down?.name || '?'}</span>
            </div>
            <div class="relation-meta">
              <span class="relation-type">${typeMap[r.relation_type] || r.relation_type}</span>
              <span>系数：${r.flow_coefficient}</span>
              <span>延迟：${r.delay_seconds}s</span>
            </div>
            <button class="btn-icon-delete" data-action="delete-relation" data-id="${r.id}">✕</button>
          </div>`;
      }).join('');

      relationsList.querySelectorAll('[data-action="delete-relation"]').forEach(btn => {
        btn.addEventListener('click', () => {
          deleteRelation(parseInt(btn.dataset.id, 10));
        });
      });
    };

    const openRelationModal = () => {
      const modal = document.getElementById('relation-modal');
      const form = document.getElementById('relation-form');
      if (!modal || !form) return;

      const vessels = ctx.multiConfig?.vessels || [];
      const upSel = form.upstream_vessel_id;
      const downSel = form.downstream_vessel_id;

      upSel.innerHTML = vessels.map(v =>
        `<option value="${v.id}">${v.name}（第${v.level_index}级）</option>`
      ).join('');
      downSel.innerHTML = vessels.map(v =>
        `<option value="${v.id}">${v.name}（第${v.level_index}级）</option>`
      ).join('');

      if (vessels.length >= 2) {
        upSel.value = vessels[0].id;
        downSel.value = vessels[1]?.id || vessels[0].id;
      }

      form.flow_coefficient.value = 1.0;
      form.delay_seconds.value = 0;
      form.relation_type.value = 'series';

      modal.style.display = 'flex';
    };

    const closeRelationModal = () => {
      const modal = document.getElementById('relation-modal');
      if (modal) modal.style.display = 'none';
    };

    const deleteRelation = async (relId) => {
      if (!confirm('确认删除此流量关系？')) return;
      const { data } = await apiJson(
        `/api/projects/${ctx.projectId}/multi-vessel/relations/${relId}`,
        { method: 'DELETE' }
      );
      if (data?.ok) {
        __Toast.success('已删除流量关系');
        await reloadMultiConfig(ctx);
        renderRelations();
      } else {
        __Toast.error(data?.error || '删除失败');
      }
    };

    if (addRelationBtn) {
      addRelationBtn.addEventListener('click', openRelationModal);
    }

    if (relationModal) {
      relationModal.querySelector('.modal-close')?.addEventListener('click', closeRelationModal);
      relationModal.addEventListener('click', (e) => {
        if (e.target === relationModal) closeRelationModal();
      });
    }

    if (relationForm) {
      relationForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const submitBtn = relationForm.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        try {
          const upId = parseInt(relationForm.upstream_vessel_id.value, 10);
          const downId = parseInt(relationForm.downstream_vessel_id.value, 10);

          if (upId === downId) {
            __Toast.warn('上游和下游容器不能相同');
            return;
          }

          const existRel = (ctx.multiConfig?.flow_relations || []).find(
            r => r.upstream_vessel_id === upId && r.downstream_vessel_id === downId
          );
          if (existRel) {
            __Toast.warn('该上下游流量关系已存在');
            return;
          }

          const payload = {
            upstream_vessel_id: upId,
            downstream_vessel_id: downId,
            flow_coefficient: parseFloat(relationForm.flow_coefficient.value),
            delay_seconds: parseFloat(relationForm.delay_seconds.value),
            relation_type: relationForm.relation_type.value,
          };

          const { data } = await apiJson(
            `/api/projects/${ctx.projectId}/multi-vessel/relations`,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: payload
            }
          );

          if (data?.ok) {
            __Toast.success('已添加流量关系');
            closeRelationModal();
            await reloadMultiConfig(ctx);
            renderRelations();
          } else {
            __Toast.error(data?.error || '添加失败');
          }
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }

    renderRelations();
    ctx.renderRelations = renderRelations;
  }

  /* ---------- 容器刻度方案 ---------- */
  function initVesselScale(ctx) {
    const scaleVesselSelect = document.getElementById('scale-vessel-select');
    const scaleCountInput = document.getElementById('vessel-scale-count');
    const regenBtn = document.getElementById('vessel-scale-regen');
    const scaleTbody = document.getElementById('vessel-scale-tbody');
    const scaleForm = document.getElementById('vessel-scale-form');

    if (!scaleVesselSelect) return;

    const refreshVesselSelect = () => {
      const vessels = ctx.multiConfig?.vessels || [];
      scaleVesselSelect.innerHTML = vessels.map(v =>
        `<option value="${v.id}">${v.name}（第${v.level_index}级）</option>`
      ).join('');
      if (vessels.length > 0 && !ctx.currentVesselId) {
        ctx.currentVesselId = vessels[0].id;
      }
      if (ctx.currentVesselId) {
        scaleVesselSelect.value = ctx.currentVesselId;
      }
    };

    const renderScale = (scheme, vessel) => {
      if (!scheme || !scheme.marks) {
        scaleTbody.innerHTML = '<tr><td colspan="3" class="placeholder-cell">暂无刻度方案</td></tr>';
        return;
      }
      const marks = [...scheme.marks].sort((a, b) => a.mark_index - b.mark_index);
      scaleTbody.innerHTML = marks.map(m => `
        <tr data-index="${m.mark_index}">
          <td>#${m.mark_index}</td>
          <td><input type="number" step="0.01" min="0" class="target-time" value="${m.target_time}"></td>
          <td><input type="number" step="0.01" min="0.01" class="target-water" value="${m.target_water_level}"></td>
        </tr>
      `).join('');
      if (scaleCountInput) scaleCountInput.value = marks.length;
    };

    const loadScale = async (vesselId) => {
      const { data } = await apiJson(
        `/api/projects/${ctx.projectId}/multi-vessel/vessels/${vesselId}/scale`
      );
      const vessel = (ctx.multiConfig?.vessels || []).find(v => v.id === vesselId);
      if (data?.ok && data.scheme) {
        ctx.currentVesselScale = data.scheme;
        renderScale(data.scheme, vessel);
      } else {
        ctx.currentVesselScale = null;
        renderScale(null, vessel);
      }
    };

    scaleVesselSelect.addEventListener('change', () => {
      ctx.currentVesselId = parseInt(scaleVesselSelect.value, 10);
      loadScale(ctx.currentVesselId);
    });

    if (regenBtn) {
      regenBtn.addEventListener('click', () => {
        const vessel = (ctx.multiConfig?.vessels || []).find(v => v.id === ctx.currentVesselId);
        if (!vessel) return;
        const n = Math.max(2, Math.min(60, parseInt(scaleCountInput?.value || '11', 10)));
        const duration = vessel.target_duration || 60;
        const capacity = vessel.capacity;
        const marks = [];
        for (let i = 0; i < n; i++) {
          const ratio = i / (n - 1);
          marks.push({
            mark_index: i,
            target_time: +(duration * ratio).toFixed(2),
            target_water_level: +(capacity * (1 - ratio)).toFixed(2)
          });
        }
        renderScale({ marks }, vessel);
      });
    }

    if (scaleForm) {
      scaleForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const rows = Array.from(scaleTbody.querySelectorAll('tr'));
        const marks = rows.map((tr, i) => ({
          mark_index: parseInt(tr.dataset.index, 10) || i,
          target_time: parseFloat(tr.querySelector('.target-time').value) || 0,
          target_water_level: parseFloat(tr.querySelector('.target-water').value) || 0
        }));

        const { data } = await apiJson(
          `/api/projects/${ctx.projectId}/multi-vessel/vessels/${ctx.currentVesselId}/scale`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: { marks }
          }
        );

        if (data?.ok) {
          __Toast.success('刻度方案已保存');
          ctx.currentVesselScale = data.scheme;
        } else {
          __Toast.error(data?.error || '保存失败');
        }
      });
    }

    refreshVesselSelect();
    if (ctx.currentVesselId) {
      loadScale(ctx.currentVesselId);
    }

    ctx.loadVesselScale = loadScale;
    ctx.refreshVesselSelect = refreshVesselSelect;
  }

  /* ---------- 多级实验数据录入 ---------- */
  function initMultiExperiments(ctx) {
    const expTabs = document.getElementById('multi-exp-tabs');
    const newExpBtn = document.getElementById('multi-new-exp-btn');
    const recordForm = document.getElementById('multi-record-form');
    const recordsTable = document.getElementById('multi-records-table');
    const finalizeBtn = document.getElementById('multi-finalize-btn');

    if (!expTabs) return;

    const renderTabs = () => {
      const exps = (ctx.multiExperiments || []);
      if (exps.length === 0) {
        expTabs.innerHTML = '<span class="hint-empty">尚未开始多级实验</span>';
        return;
      }
      expTabs.innerHTML = exps.map(e => `
        <button class="round-tab ${e.id === ctx.currentMultiExpId ? 'active' : ''}"
                data-exp-id="${e.id}" data-status="${e.status}">
          <span>第${e.round_number}轮</span>
          ${e.status === 'recording' ? '<span class="tab-dot recording"></span>' :
            e.status === 'finalized' ? '<span class="tab-dot done"></span>' : ''}
        </button>
      `).join('');

      expTabs.querySelectorAll('.round-tab').forEach(btn => {
        btn.addEventListener('click', () => {
          ctx.currentMultiExpId = parseInt(btn.dataset.expId, 10);
          renderAll();
        });
      });
    };

    const currentExp = () =>
      (ctx.multiExperiments || []).find(e => e.id === ctx.currentMultiExpId) || null;

    const renderVesselInputs = () => {
      const vesselsBox = document.getElementById('multi-record-vessels');
      if (!vesselsBox) return;
      const vessels = ctx.multiConfig?.vessels || [];
      if (vessels.length === 0) {
        vesselsBox.innerHTML = '<div class="hint-empty">请先配置容器</div>';
        return;
      }
      vesselsBox.innerHTML = vessels.map(v => `
        <div class="vessel-record-input">
          <label class="vessel-input-label">
            <span class="vessel-dot" style="background:${getVesselColor(v.level_index)}"></span>
            ${v.name}
          </label>
          <div class="input-with-unit">
            <input type="number" step="0.01" min="0" max="${v.capacity}"
                   name="vessel_${v.id}" data-vessel-id="${v.id}"
                   placeholder="≤${v.capacity} ml">
            <span class="unit">ml</span>
          </div>
        </div>
      `).join('');
    };

    const getVesselColor = (idx) => {
      const palette = ['#5C4033', '#4A7C59', '#C23B22', '#B8860B', '#4E6BA0', '#8B4E8D'];
      return palette[idx % palette.length];
    };

    const renderRecords = () => {
      const thead = document.querySelector('#multi-records-table thead tr');
      const tbody = document.getElementById('multi-records-tbody');
      if (!tbody) return;
      const exp = currentExp();
      const vessels = ctx.multiConfig?.vessels || [];
      const sortedVessels = [...vessels].sort((a, b) => a.level_index - b.level_index);

      if (thead) {
        thead.innerHTML = '<th>时间(分)</th>' +
          sortedVessels.map(v => `<th>${v.name}(ml)</th>`).join('');
      }

      if (!exp || !exp.vessel_records || exp.vessel_records.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${sortedVessels.length + 1}" class="placeholder-cell">尚未录入数据</td></tr>`;
        return;
      }

      const timePoints = [...new Set(exp.vessel_records.map(r => r.time_point))].sort((a, b) => a - b);
      const recMap = {};
      exp.vessel_records.forEach(r => {
        if (!recMap[r.time_point]) recMap[r.time_point] = {};
        recMap[r.time_point][r.vessel_id] = r;
      });

      tbody.innerHTML = timePoints.map(t => {
        const cells = sortedVessels.map(v => {
          const r = recMap[t]?.[v.id];
          if (!r) return '<td>—</td>';
          let cls = '';
          if (r.time_error != null && Math.abs(r.time_error) > (ctx.errorThreshold || 5)) {
            cls = ' class="row-danger"';
          }
          return `<td${cls}>${r.water_level}</td>`;
        }).join('');
        return `<tr><td>${t}</td>${cells}</tr>`;
      }).join('');
    };

    const renderCharts = async () => {
      const exp = currentExp();
      if (!exp || exp.status !== 'finalized') {
        ClepsydraCharts.renderMultiVesselWaterLevel('multi-water-chart', null, null, null);
        ClepsydraCharts.renderInterVesselFlowError('multi-flow-error-chart', null);
        ClepsydraCharts.renderErrorAmplification('multi-error-amp-chart', null);
        renderAnalysisPlaceholder();
        return;
      }

      const { data } = await apiJson(
        `/api/projects/${ctx.projectId}/multi-vessel/analysis?exp_id=${exp.id}`
      );

      if (data?.ok && data.analysis) {
        ctx.multiAnalysis = data.analysis;
        const vessels = ctx.multiConfig?.vessels || [];
        const schemes = data.vessel_scale_schemes || [];
        if (schemes.length > 0) {
          ctx.cachedVesselSchemes = schemes;
        }

        ClepsydraCharts.renderMultiVesselWaterLevel('multi-water-chart', data.analysis, vessels, schemes);
        ClepsydraCharts.renderInterVesselFlowError('multi-flow-error-chart', data.analysis);
        ClepsydraCharts.renderErrorAmplification('multi-error-amp-chart', data.analysis);
        renderAnalysisDetail(data.analysis);
        await loadJointAdjustment(ctx, exp.id);
      }
    };

    const renderAnalysisPlaceholder = () => {
      const kpiAvg = document.getElementById('multi-kpi-avg');
      const kpiMax = document.getElementById('multi-kpi-max');
      const kpiExceed = document.getElementById('multi-kpi-exceed');
      if (kpiAvg) kpiAvg.textContent = '--';
      if (kpiMax) kpiMax.textContent = '--';
      if (kpiExceed) kpiExceed.textContent = '--';
    };

    const renderAnalysisDetail = (analysis) => {
      const stages = analysis.error_amplification_stages || [];
      const ampCount = stages.filter(s => s.is_amplification_stage).length;
      const avgErr = stages.length
        ? (stages.reduce((s, v) => s + v.avg_error_percent, 0) / stages.length).toFixed(2)
        : 0;
      const maxErr = stages.length
        ? Math.max(...stages.map(s => s.max_error_percent)).toFixed(2)
        : 0;

      const kpiAvg = document.getElementById('multi-kpi-avg');
      const kpiMax = document.getElementById('multi-kpi-max');
      const kpiAmp = document.getElementById('multi-kpi-amp');
      if (kpiAvg) kpiAvg.textContent = avgErr + '%';
      if (kpiMax) kpiMax.textContent = '±' + maxErr + '%';
      if (kpiAmp) kpiAmp.textContent = ampCount;

      const stagesTbody = document.getElementById('error-stages-tbody');
      if (stagesTbody) {
        stagesTbody.innerHTML = stages.map(s => `
          <tr class="${s.is_amplification_stage ? 'row-danger' : ''}">
            <td>${s.vessel_name}</td>
            <td>第${s.level_index}级</td>
            <td>${s.avg_error_percent}%</td>
            <td>${s.max_error_percent}%</td>
            <td>${s.error_gain}x</td>
            <td>${s.is_amplification_stage ? '<span class="badge badge-danger">误差放大</span>' : '<span class="badge badge-success">正常</span>'}</td>
          </tr>
        `).join('');
      }
    };

    const loadJointAdjustment = async (ctx, expId) => {
      const { data } = await apiJson(
        `/api/projects/${ctx.projectId}/multi-vessel/joint-adjustment?exp_id=${expId}`
      );
      if (data?.ok && data.adjustment) {
        ctx.jointAdjustment = data.adjustment;
        renderJointAdjustment(data.adjustment);
      }
    };

    const renderJointAdjustment = (adjustment) => {
      const stepsBox = document.getElementById('joint-adjustment-steps');
      if (!stepsBox) return;
      const steps = adjustment.adjustment_steps || [];
      if (steps.length === 0) {
        stepsBox.innerHTML = '<div class="placeholder-cell small">暂无联合调整建议</div>';
        return;
      }
      stepsBox.innerHTML = steps.map(s => `
        <div class="joint-step priority-${s.priority}">
          <div class="joint-step-header">
            <div class="step-order">第 ${s.step_order} 步</div>
            <div class="step-title">${s.vessel_name}（第${s.level_index}级）</div>
            <div class="step-priority">${priorityLabel(s.priority)}</div>
          </div>
          <div class="joint-step-body">
            <div class="step-meta">
              <span>当前平均误差：${s.current_avg_error}%</span>
              <span>预期改善：${s.expected_improvement}%</span>
            </div>
            <div class="step-rationale">${s.rationale}</div>
            ${s.details && s.details.length > 0 ? `
              <div class="step-details">
                <div class="details-title">具体调整项：</div>
                <ul class="details-list">
                  ${s.details.map(d => `
                    <li>
                      刻度 #${d.mark_index}（${d.target_time}分）：
                      原 ${d.original_level} ml → 建议 ${d.suggested_level} ml
                      （${d.direction}）
                    </li>
                  `).join('')}
                </ul>
              </div>
            ` : ''}
          </div>
        </div>
      `).join('');

      const overall = document.getElementById('joint-overall');
      if (overall) {
        overall.innerHTML = `
          <div class="joint-overall-card">
            <div class="overall-title">整体调整方案</div>
            <div class="overall-rationale">${adjustment.overall_rationale || ''}</div>
            <div class="overall-summary">
              <span>涉及容器：${adjustment.total_vessels} 个</span>
              <span>预期总改善：${adjustment.total_expected_improvement}%</span>
            </div>
          </div>
        `;
      }
    };

    const priorityLabel = (p) => {
      const map = { high: '高优先级', medium: '中优先级', low: '低优先级' };
      return map[p] || p;
    };

    const renderAll = () => {
      renderTabs();
      renderVesselInputs();
      renderRecords();
      renderCharts();
      updateButtons();
    };

    const updateButtons = () => {
      const exp = currentExp();
      if (finalizeBtn) {
        const recording = exp && exp.status === 'recording';
        const hasRecords = exp && exp.vessel_records && exp.vessel_records.length >= 2;
        finalizeBtn.disabled = !(recording && hasRecords);
      }
    };

    if (newExpBtn) {
      newExpBtn.addEventListener('click', async () => {
        const { data } = await apiJson(
          `/api/projects/${ctx.projectId}/multi-vessel/experiments`,
          { method: 'POST' }
        );
        if (data?.ok && data.experiment) {
          const newExp = data.experiment;
          if (!newExp.vessel_records) newExp.vessel_records = [];
          ctx.multiExperiments.push(newExp);
          ctx.currentMultiExpId = newExp.id;
          __Toast.success('已创建新一轮多级实验');
          renderAll();
        } else {
          __Toast.error(data?.error || '创建失败');
        }
      });
    }

    if (recordForm) {
      recordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const exp = currentExp();
        if (!exp) { __Toast.warn('请先创建实验'); return; }

        const timePoint = parseFloat(recordForm.time_point.value);
        if (isNaN(timePoint) || timePoint < 0) {
          __Toast.warn('请输入有效的时间节点');
          return;
        }
        const existingTimes = (exp.vessel_records || [])
          .map(r => r.time_point)
          .filter((v, i, a) => a.indexOf(v) === i);
        if (existingTimes.length > 0) {
          const maxTime = Math.max(...existingTimes);
          if (timePoint <= maxTime) {
            __Toast.warn(`时间节点必须递增，当前最大已录时间为 ${maxTime} 分钟`);
            return;
          }
        }
        const inputs = recordForm.querySelectorAll('[data-vessel-id]');
        const records = [];
        inputs.forEach(input => {
          const vid = parseInt(input.dataset.vesselId, 10);
          const val = parseFloat(input.value);
          if (!isNaN(val)) {
            records.push({ vessel_id: vid, time_point: timePoint, water_level: val });
          }
        });

        if (records.length === 0) {
          __Toast.warn('请至少录入一个容器的水位');
          return;
        }

        const { data } = await apiJson(
          `/api/projects/${ctx.projectId}/multi-vessel/experiments/${exp.id}/records`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: { time_point: timePoint, records }
          }
        );

        if (data?.ok && data.records) {
          __Toast.success(`已录入节点：${timePoint} 分`);
          data.records.forEach(r => {
            exp.vessel_records.push(r);
          });
          recordForm.reset();
          renderAll();
        } else {
          __Toast.error(data?.error || '录入失败');
        }
      });
    }

    if (finalizeBtn) {
      finalizeBtn.addEventListener('click', async () => {
        const exp = currentExp();
        if (!exp) return;
        if (!confirm('确认结束本轮多级实验？结束后将自动分析级间误差并给出联合调整建议。')) return;
        finalizeBtn.disabled = true;
        try {
          const { data } = await apiJson(
            `/api/projects/${ctx.projectId}/multi-vessel/experiments/${exp.id}/finalize`,
            { method: 'POST' }
          );
          if (data?.ok) {
            exp.status = 'finalized';
            exp.total_error = data.avg_error;
            if (data.vessel_records) {
              exp.vessel_records = data.vessel_records;
            }
            if (data.project_status && ctx.project) {
              ctx.project.status = data.project_status;
            }
            if (data.analysis) {
              ctx.multiAnalysis = data.analysis;
            }
            if (data.vessel_scale_schemes && data.vessel_scale_schemes.length > 0) {
              ctx.cachedVesselSchemes = data.vessel_scale_schemes;
            }
            __Toast.success(`分析完成 · 平均误差 ${data.avg_error}%`);
            renderAll();
          } else {
            __Toast.error(data?.error || '分析失败');
          }
        } finally {
          finalizeBtn.disabled = false;
        }
      });
    }

    renderAll();
  }

  /* ---------- Tab 切换 ---------- */
  function initTabs(ctx) {
    const tabButtons = document.querySelectorAll('[data-tab]');
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const tabId = btn.dataset.tab;
        tabButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        const panel = document.getElementById(tabId + '-panel');
        if (panel) panel.classList.add('active');
      });
    });
  }

  /* ---------- 辅助：重新加载配置 ---------- */
  async function reloadMultiConfig(ctx) {
    const { data } = await apiJson(`/api/projects/${ctx.projectId}/multi-vessel`);
    if (data?.ok) {
      ctx.multiConfig = data.config;
    }
    return ctx.multiConfig;
  }

  async function loadMultiExperiments(ctx) {
    const exps = (ctx.experiments || []).filter(e => e.is_multi_vessel);
    ctx.multiExperiments = exps;
    if (exps.length > 0 && !ctx.currentMultiExpId) {
      ctx.currentMultiExpId = exps[exps.length - 1].id;
    }

    for (const exp of ctx.multiExperiments) {
      if (!exp.vessel_records) {
        exp.vessel_records = [];
      }
    }
  }

  async function loadVesselScale(ctx, vesselId) {
    const { data } = await apiJson(
      `/api/projects/${ctx.projectId}/multi-vessel/vessels/${vesselId}/scale`
    );
    if (data?.ok) {
      ctx.currentVesselScale = data.scheme;
      if (ctx.loadVesselScale) {
        // 已在 initVesselScale 中处理
      }
    }
  }

  /* ---------- 初始化入口 ---------- */
  MultiVesselApp.init = function (ctx) {
    initTabs(ctx);
    initVesselConfig(ctx);
    initFlowRelations(ctx);
    initVesselScale(ctx);
    loadMultiExperiments(ctx).then(() => {
      initMultiExperiments(ctx);
    });
  };

  global.MultiVesselApp = MultiVesselApp;
  global.__reloadMultiConfig = reloadMultiConfig;
})(window);
