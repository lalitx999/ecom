/* Back-office: inline stock / visibility editing (Ajax) and image preview */
(function () {
  'use strict';
  const csrf = document.querySelector('meta[name="csrf-token"]').content;

  async function quick(url, data) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: new URLSearchParams(data),
      credentials: 'same-origin',
    });
    try { return await res.json(); } catch (e) { return { ok: false, message: 'เกิดข้อผิดพลาด กรุณาลองใหม่' }; }
  }

  function toast(message, error) {
    const host = document.getElementById('toastHost');
    const el = document.createElement('div');
    el.className = 'toast app-toast align-items-center' + (error ? ' error' : '');
    el.setAttribute('role', 'status');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"></div><button type="button" class="btn-close btn-close-white m-auto me-3" data-bs-dismiss="toast" aria-label="ปิด"></button></div>';
    el.querySelector('.toast-body').textContent = message;
    host.appendChild(el);
    el.addEventListener('hidden.bs.toast', () => el.remove());
    bootstrap.Toast.getOrCreateInstance(el, { delay: 2200 }).show();
  }

  document.addEventListener('change', async (e) => {
    const stock = e.target.closest('.js-stock');
    if (stock) {
      const json = await quick(stock.dataset.url, { stock: stock.value });
      if (json.ok) {
        stock.value = json.stock;
        stock.classList.toggle('low', json.stock <= parseInt(stock.dataset.low, 10));
        stock.classList.add('saved');
        setTimeout(() => stock.classList.remove('saved'), 1200);
        toast('บันทึกสต็อกแล้ว');
      } else {
        stock.value = json.stock !== undefined ? json.stock : stock.defaultValue;
        toast(json.message, true);
      }
      return;
    }
    const active = e.target.closest('.js-active');
    if (active) {
      const json = await quick(active.dataset.url, { is_active: active.checked ? '1' : '0' });
      if (json.ok) { toast(json.is_active ? 'แสดงสินค้าในร้านแล้ว' : 'ซ่อนสินค้าจากร้านแล้ว'); }
      else { active.checked = !active.checked; toast(json.message, true); }
      return;
    }
    const tileInput = e.target.closest('.image-tile input[type="file"]');
    if (tileInput && tileInput.files[0]) {
      tileInput.closest('.image-tile').querySelector('.img-preview').src = URL.createObjectURL(tileInput.files[0]);
      return;
    }
    const file = e.target.closest('.js-image-input');
    if (file && file.files[0]) {
      const img = document.getElementById(file.dataset.preview);
      if (img) img.src = URL.createObjectURL(file.files[0]);
    }
  });
})();
