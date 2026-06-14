/* ============================================================
 * validation.js — 前端表单校验与公共工具
 * ============================================================ */
(function (global) {
  'use strict';

  const ClepsydraForms = {};

  function showError(el, message) {
    if (!el) return;
    el.classList.add('error');
    const container = el.closest('.form-group');
    if (container) {
      const errBox = container.querySelector('.form-error');
      if (errBox) errBox.textContent = message || '';
    }
  }

  function clearError(el) {
    if (!el) return;
    el.classList.remove('error');
    const container = el.closest('.form-group');
    if (container) {
      const errBox = container.querySelector('.form-error');
      if (errBox) errBox.textContent = '';
    }
  }

  function validateRequired(el, label) {
    const val = (el.value || '').trim();
    if (val === '' || val === null || val === undefined || Number.isNaN(parseFloat(val)) && el.type === 'number') {
      showError(el, `${label || '该字段'}为必填项`);
      return false;
    }
    clearError(el);
    return true;
  }

  function validateGreaterThan(el, min, label) {
    const v = parseFloat(el.value);
    if (Number.isNaN(v)) { showError(el, `${label}必须是数字`); return false; }
    if (!(v > min)) { showError(el, `${label}必须大于 ${min}`); return false; }
    clearError(el);
    return true;
  }

  function validateRange(el, min, max, label) {
    const v = parseFloat(el.value);
    if (Number.isNaN(v)) { showError(el, `${label}必须是数字`); return false; }
    if (v < min || v > max) {
      showError(el, `${label}必须在 ${min} ~ ${max} 之间`); return false;
    }
    clearError(el);
    return true;
  }

  ClepsydraForms.validateRequired = validateRequired;
  ClepsydraForms.validateGreaterThan = validateGreaterThan;
  ClepsydraForms.validateRange = validateRange;
  ClepsydraForms.showError = showError;
  ClepsydraForms.clearError = clearError;

  ClepsydraForms.initNewProjectForm = function () {
    const form = document.getElementById('new-project-form');
    if (!form) return;
    const name = form.querySelector('#name');

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      let ok = true;
      if (!validateRequired(name, '项目名称')) ok = false;
      if (name && name.value.trim().length < 2) {
        showError(name, '项目名称至少 2 个字符');
        ok = false;
      }
      if (!ok) return;
      form.submit();
    });

    if (name) name.addEventListener('input', () => clearError(name));
  };

  ClepsydraForms.validateConfigForm = function (formEl) {
    const capacity = formEl.querySelector('#capacity');
    const outlet = formEl.querySelector('#outlet_diameter');
    const duration = formEl.querySelector('#target_duration');
    const inlet = formEl.querySelector('#water_inlet_type');
    let ok = true;
    if (!validateGreaterThan(capacity, 0, '漏壶容量')) ok = false;
    if (!validateGreaterThan(outlet, 0, '出水孔径')) ok = false;
    if (!validateGreaterThan(duration, 0, '目标计时时长')) ok = false;
    if (!inlet.value) { showError(inlet, '请选择进水方式'); ok = false; } else clearError(inlet);
    return ok;
  };

  ClepsydraForms.validateRecordForm = function (formEl, ctx) {
    const t = formEl.querySelector('#time_point');
    const w = formEl.querySelector('#water_level');
    const errBox = document.getElementById('record-form-error');
    if (errBox) errBox.textContent = '';

    let ok = true;
    if (!validateRequired(t, '时间节点')) ok = false;
    if (!validateGreaterThan(t, 0, '时间节点')) ok = false;
    if (!validateRequired(w, '实测水位')) ok = false;
    if (!validateGreaterThan(w, 0, '实测水位')) ok = false;

    if (!ok) return false;

    const tp = parseFloat(t.value);
    const wl = parseFloat(w.value);

    if (ctx.capacity && wl > ctx.capacity) {
      if (errBox) errBox.textContent = `实测水位 ${wl} ml 超过漏壶容量 ${ctx.capacity} ml`;
      showError(w, `不能超过 ${ctx.capacity} ml`);
      return false;
    }

    if (ctx.lastTime != null && tp <= ctx.lastTime) {
      if (errBox) errBox.textContent = `时间节点必须递增（当前 ${tp} ≤ 上一节点 ${ctx.lastTime}）`;
      showError(t, '必须大于上一节点');
      return false;
    }

    if (ctx.existingTimes != null && ctx.existingTimes.includes(tp)) {
      if (errBox) errBox.textContent = `时间节点 ${tp} 分钟已存在`;
      showError(t, '时间节点已存在');
      return false;
    }

    return true;
  };

  ClepsydraForms.validateScaleTable = function (tbodyEl, capacity) {
    const rows = Array.from(tbodyEl.querySelectorAll('tr'));
    let prevTime = -Infinity;
    let ok = true;
    const marks = [];

    for (let i = 0; i < rows.length; i++) {
      const tr = rows[i];
      const tInput = tr.querySelector('.target-time');
      const wInput = tr.querySelector('.target-water');
      const t = parseFloat(tInput.value);
      const w = parseFloat(wInput.value);

      tr.querySelectorAll('input').forEach(inp => inp.classList.remove('error'));

      if (Number.isNaN(t)) { tInput.classList.add('error'); ok = false; continue; }
      if (Number.isNaN(w) || w <= 0) { wInput.classList.add('error'); ok = false; continue; }
      if (capacity && w > capacity) { wInput.classList.add('error'); ok = false; continue; }
      if (i > 0 && t <= prevTime) { tInput.classList.add('error'); ok = false; continue; }

      prevTime = t;
      marks.push({
        mark_index: parseInt(tr.dataset.index, 10) || i,
        target_time: +t.toFixed(3),
        target_water_level: +w.toFixed(3),
      });
    }
    return { ok, marks };
  };

  global.ClepsydraForms = ClepsydraForms;
})(window);
