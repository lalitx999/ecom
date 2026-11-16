/* Ajax cart: add / update / remove without reloading the page */
(function () {
  'use strict';

  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const URLS = { add: '/cart/add/', update: '/cart/update/', remove: '/cart/remove/' };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  async function post(url, data) {
    const body = new URLSearchParams(data);
    const pageBody = $('#cart-page-body');
    if (pageBody) body.set('page', '1');
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body,
      credentials: 'same-origin',
    });
    let json;
    try { json = await res.json(); } catch (e) { json = { ok: false, message: 'เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง' }; }
    return json;
  }

  function showToast(message, { error = false, withCartLink = false } = {}) {
    const host = $('#toastHost');
    const el = document.createElement('div');
    el.className = 'toast app-toast align-items-center' + (error ? ' error' : '');
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.innerHTML =
      '<div class="d-flex"><div class="toast-body"></div>' +
      '<button type="button" class="btn-close btn-close-white m-auto me-3" data-bs-dismiss="toast" aria-label="ปิด"></button></div>';
    const bodyEl = $('.toast-body', el);
    bodyEl.textContent = message;
    if (withCartLink) {
      const a = document.createElement('a');
      a.href = '#';
      a.className = 'ms-2';
      a.textContent = 'ดูตะกร้า';
      a.addEventListener('click', (e) => {
        e.preventDefault();
        bootstrap.Toast.getOrCreateInstance(el).hide();
        const cartPage = $('#cart-page-body');
        if (!cartPage) bootstrap.Offcanvas.getOrCreateInstance($('#cartDrawer')).show();
      });
      bodyEl.appendChild(a);
    }
    host.appendChild(el);
    el.addEventListener('hidden.bs.toast', () => el.remove());
    bootstrap.Toast.getOrCreateInstance(el, { delay: 3000 }).show();
  }

  function applyCart(json) {
    $$('[data-cart-count]').forEach((b) => { b.textContent = json.count; b.dataset.count = json.count; });
    const drawer = $('#cart-drawer-body');
    if (drawer && json.drawer_html !== undefined) drawer.innerHTML = json.drawer_html;
    const page = $('#cart-page-body');
    if (page && json.page_html !== undefined) page.innerHTML = json.page_html;
  }

  // ---- add to cart (product cards and detail page) ----
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.js-add-to-cart');
    if (!btn || btn.disabled) return;
    let qty = parseInt(btn.dataset.qty || '1', 10);
    if (btn.dataset.qtyInput) {
      const input = $(btn.dataset.qtyInput);
      qty = Math.max(1, parseInt(input.value, 10) || 1);
    }
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span>';
    const json = await post(URLS.add, { product_id: btn.dataset.productId, qty });
    btn.disabled = false;
    btn.innerHTML = original;
    applyCart(json);
    showToast(json.message, { error: !json.ok, withCartLink: json.ok });
  });

  // ---- cart line controls (drawer and cart page) ----
  async function updateLine(productId, qty) {
    const json = await post(URLS.update, { product_id: productId, qty });
    applyCart(json);
    if (!json.ok || /สูงสุด/.test(json.message)) showToast(json.message, { error: !json.ok });
  }

  document.addEventListener('click', async (e) => {
    const step = e.target.closest('.js-cart-step');
    if (step) {
      const wrap = step.closest('.stepper');
      const input = $('.js-cart-qty', wrap);
      const next = (parseInt(input.value, 10) || 1) + parseInt(step.dataset.delta, 10);
      $$('button', wrap).forEach((b) => (b.disabled = true));
      await updateLine(wrap.dataset.productId, Math.max(1, next));
      return;
    }
    const rm = e.target.closest('.js-cart-remove');
    if (rm) {
      rm.disabled = true;
      const json = await post(URLS.remove, { product_id: rm.dataset.productId });
      applyCart(json);
      showToast(json.message, { error: !json.ok });
    }
  });

  document.addEventListener('change', async (e) => {
    const input = e.target.closest('.js-cart-qty');
    if (!input) return;
    const wrap = input.closest('.stepper');
    await updateLine(wrap.dataset.productId, Math.max(1, parseInt(input.value, 10) || 1));
  });

  // ---- quantity stepper on the product page (no request, just the field) ----
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-stepper] [data-step]');
    if (!b) return;
    const wrap = b.closest('[data-stepper]');
    const input = $('input', wrap);
    const min = parseInt(input.min, 10) || 1;
    const max = parseInt(input.max, 10) || 99;
    input.value = Math.min(max, Math.max(min, (parseInt(input.value, 10) || min) + parseInt(b.dataset.step, 10)));
    syncStepper(wrap);
  });
  document.addEventListener('input', (e) => {
    const wrap = e.target.closest('[data-stepper]');
    if (wrap) syncStepper(wrap);
  });
  function syncStepper(wrap) {
    const input = $('input', wrap);
    const min = parseInt(input.min, 10) || 1;
    const max = parseInt(input.max, 10) || 99;
    let v = parseInt(input.value, 10);
    if (!isNaN(v)) { v = Math.min(max, Math.max(min, v)); }
    const [minus, plus] = $$('[data-step]', wrap);
    minus.disabled = !(v > min);
    plus.disabled = !(v < max);
  }
})();
