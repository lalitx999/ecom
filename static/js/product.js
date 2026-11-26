/* Product page: pick colour / size, then show that variant's price, stock and image */
(function () {
  'use strict';
  const root = document.querySelector('[data-variant-picker]');
  const dataEl = document.getElementById('variant-data');
  if (!root || !dataEl) return;

  const data = JSON.parse(dataEl.textContent);
  const variants = data.variants;
  const $ = (sel) => root.querySelector(sel);
  const $$ = (sel) => Array.from(root.querySelectorAll(sel));

  const colorBtns = $$('[data-color].option-btn');
  const sizeBtns = $$('[data-size].option-btn');
  const hasColor = colorBtns.length > 0;
  const hasSize = sizeBtns.length > 0;
  const state = { color: '', size: '' };

  const addBtn = $('.js-add-to-cart');
  const qty = $('#qty');
  const mainImage = document.getElementById('mainImage');

  const baht = (v) => {
    const n = Number(v);
    return n.toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 });
  };
  const matches = (v, color, size) => (!color || v.color === color) && (!size || v.size === size);
  const buyable = (color, size) => variants.some((v) => matches(v, color, size) && v.stock > 0);

  function current() {
    if ((hasColor && !state.color) || (hasSize && !state.size)) return null;
    return variants.find((v) => v.color === (hasColor ? state.color : '') && v.size === (hasSize ? state.size : '')) || null;
  }

  function showImage(url) {
    if (!url || !mainImage) return;
    mainImage.src = url;
    $$('.thumb-btn').forEach((b) => b.classList.toggle('active', b.dataset.image === url));
  }

  function render() {
    colorBtns.forEach((b) => {
      b.classList.toggle('active', b.dataset.color === state.color);
      b.classList.toggle('sold-out', !buyable(b.dataset.color, state.size));
    });
    sizeBtns.forEach((b) => {
      b.classList.toggle('active', b.dataset.size === state.size);
      const exists = variants.some((v) => matches(v, state.color, b.dataset.size));
      b.hidden = !exists;
      b.classList.toggle('sold-out', !buyable(state.color, b.dataset.size));
    });
    const colorLabel = $('[data-color-label]');
    if (colorLabel) colorLabel.textContent = state.color || 'เลือกสี';
    const sizeLabel = $('[data-size-label]');
    if (sizeLabel) sizeLabel.textContent = state.size || 'เลือกไซซ์';

    const v = current();
    const priceEl = $('[data-price]');
    const compareEl = $('[data-compare]');
    const discountEl = $('[data-discount]');
    const note = $('[data-stock-note]');

    if (v) {
      priceEl.textContent = baht(v.price) + ' บาท';
      compareEl.textContent = v.compare ? baht(v.compare) + ' บาท' : '';
      compareEl.classList.toggle('d-none', !v.compare);
      discountEl.textContent = 'ลด ' + v.discount + '%';
      discountEl.classList.toggle('d-none', !v.compare);
      if (v.stock > 0) {
        note.textContent = (v.stock <= 10 ? 'เหลือ ' + v.stock + ' ชิ้นสุดท้าย' : 'มีสินค้าพร้อมส่ง') + (v.ready ? ' · พร้อมส่ง' : '');
        addBtn.disabled = false;
        addBtn.dataset.variantId = v.id;
        addBtn.textContent = 'เพิ่มลงในตะกร้า';
      } else {
        note.textContent = 'ตัวเลือกนี้สินค้าหมด';
        addBtn.disabled = true;
        addBtn.dataset.variantId = '';
        addBtn.textContent = 'สินค้าหมด';
      }
      qty.max = Math.max(1, v.stock);
      qty.value = Math.min(Math.max(1, parseInt(qty.value, 10) || 1), Math.max(1, v.stock));
    } else {
      const pool = variants.filter((x) => matches(x, state.color, state.size) && x.stock > 0);
      const prices = (pool.length ? pool : variants).map((x) => Number(x.price));
      const lo = Math.min(...prices), hi = Math.max(...prices);
      priceEl.textContent = (lo === hi ? baht(lo) : baht(lo) + ' - ' + baht(hi)) + ' บาท';
      compareEl.classList.add('d-none');
      discountEl.classList.add('d-none');
      note.textContent = 'เลือก' + [hasColor && !state.color ? 'สี' : '', hasSize && !state.size ? 'ไซซ์' : ''].filter(Boolean).join('และ') + 'เพื่อดูราคาและจำนวนสินค้า';
      addBtn.disabled = true;
      addBtn.dataset.variantId = '';
      addBtn.textContent = 'เลือกตัวเลือก';
      qty.max = 1;
      qty.value = 1;
    }
    qty.dispatchEvent(new Event('input', { bubbles: true }));  // let the stepper refresh its +/- buttons
  }

  root.addEventListener('click', (e) => {
    const c = e.target.closest('.option-btn[data-color]');
    if (c) {
      state.color = state.color === c.dataset.color ? '' : c.dataset.color;
      if (state.size && !variants.some((v) => matches(v, state.color, state.size))) state.size = '';
      const img = data.images.find((i) => i.color && i.color === state.color);
      if (img) showImage(img.url);
      render();
      return;
    }
    const s = e.target.closest('.option-btn[data-size]');
    if (s) {
      state.size = state.size === s.dataset.size ? '' : s.dataset.size;
      render();
      return;
    }
    const t = e.target.closest('.thumb-btn');
    if (t) showImage(t.dataset.image);
  });

  // preselect when a dimension has a single choice
  if (colorBtns.length === 1) state.color = colorBtns[0].dataset.color;
  if (sizeBtns.length === 1) state.size = sizeBtns[0].dataset.size;
  if (hasColor || hasSize) render();
})();
