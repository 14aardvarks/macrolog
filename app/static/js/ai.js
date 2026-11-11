import { api } from './api.js';
import { h, field, message, show, loadImage, sourceBadge } from './dom.js';
import { fitSize, photosText, centsText, sourceNote } from './util.js';
import { confirmClaude } from './notice.js';
import { renderFoodForm } from './foodform.js';

// Re-encode any photo (HEIC, huge phone photos) as a JPEG of at most 1280 px on the long side.
export async function toJpeg(file) {
  const img = await loadImage(file);
  const w = img.naturalWidth || img.width;
  const hgt = img.naturalHeight || img.height;
  const s = fitSize(w, hgt, 1280);
  const canvas = document.createElement('canvas');
  canvas.width = s.w;
  canvas.height = s.h;
  const g = canvas.getContext('2d');
  g.fillStyle = '#fff';
  g.fillRect(0, 0, s.w, s.h);
  g.drawImage(img, 0, 0, s.w, s.h);
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not prepare that photo.'))), 'image/jpeg', 0.8);
  });
}

// params: { barcode? }  ctx: { go, back }
export async function renderAi(root, params, ctx) {
  let st = null;
  try { st = await api.aiStatus(); } catch (e) { st = { enabled: false }; }
  const manualBtn = h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('manual', { barcode: params.barcode }) }, 'Enter Manually');
  if (!st.enabled) {
    root.appendChild(h('section', { class: 'screen' }, h('h1', null, 'Ask Claude ', sourceBadge('ai')),
      message('Claude is not set up on this server. You can still enter the food by hand.'), manualBtn));
    return;
  }
  const files = h('input', { type: 'file', accept: 'image/*', multiple: '', class: 'visually-hidden', onchange: onFiles });
  const list = h('p', { class: 'sub' }, 'No photos chosen.');
  const hint = field('Note for Claude (optional)', { autocomplete: 'off', placeholder: 'e.g. per 1 cup prepared' });
  const code = field('Barcode (optional)', { inputmode: 'numeric', value: params.barcode || '' });
  const status = h('div', { 'aria-live': 'polite' });
  const go = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: send }, 'Read Label');
  let chosen = [];

  root.appendChild(h('section', { class: 'screen' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, 'Ask Claude ', sourceBadge('ai')),
    h('p', { class: 'sub' }, 'This is not a food database search. Claude reads your photo and estimates the values. ' + sourceNote('ai')),
    h('p', { class: 'sub' }, 'Photograph the nutrition label. If you can, get the barcode in the same photo. Up to 3 photos.'),
    h('p', { class: 'sub' }, 'Used ' + st.used_this_month + ' of ' + st.cap + ' this month.'),
    h('label', { class: 'btn' }, 'Choose or Take Photos', files), list, hint, code, status,
    h('div', { class: 'row wrap' }, go, manualBtn)));

  function onFiles() {
    chosen = Array.prototype.slice.call(files.files || [], 0, 3);
    list.textContent = chosen.length ? chosen.length + ' photo(s): ' + chosen.map((f) => f.name).join(', ') : 'No photos chosen.';
    go.disabled = !chosen.length;
  }

  async function send() {
    go.disabled = true;
    if (!(await confirmClaude(ctx.settings, { what: photosText(chosen.length), images: chosen.length }))) { go.disabled = !chosen.length; return; }
    show(status, message('Preparing photos...'));
    try {
      const form = new FormData();
      for (let i = 0; i < chosen.length; i++) form.append('images', await toJpeg(chosen[i]), 'label' + (i + 1) + '.jpg');
      const bc = code.input.value.replace(/\D/g, '');
      if (bc) form.append('barcode', bc);
      if (hint.input.value.trim()) form.append('hint', hint.input.value.trim());
      show(status, message('Claude is reading the label...'));
      const r = await api.aiLabel(form);
      root.textContent = '';
      renderFoodForm(root, { draft: r.draft, warnings: r.warnings, barcode: bc }, ctx);
      const title = root.querySelector('h1');
      if (title && r.cost != null) title.after(h('p', { class: 'sub' }, 'This read cost about ' + centsText(r.cost) + '.'));
    } catch (e) {
      go.disabled = false;
      show(status, message(e.message, 'error'));
    }
  }
}
