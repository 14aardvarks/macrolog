// Photos on foods and recipes: the Photo section (show, Add Photo, Replace Photo, Remove Photo), small list thumbnails,
// the top photo of the Cooking view and the crop dialog. The math lives in js/photomath.js. Whether photos are on comes
// from GET /api/photo-config (the admin switch Allow Photos, off by default); when off nothing here shows.
import { api } from './api.js';
import { h, clear, show, message, loadImage } from './dom.js';
import { sentence } from './util.js';
import { photoUrl, photoAlt, scaledSize, frameSize, startView, panView, zoomView, reframe, cropRect, viewScale, pointerDistance,
  FRAMES, FRAME_LABELS, ZOOM_MAX, PHOTO_MAX_SIDE } from './photomath.js';

export const REMOVE_PHOTO_CONFIRM = 'Remove This Photo? ' + sentence('The photo is deleted from the server');

let cfg = { enabled: false, max_mb: 5 };
let loaded = 0;

// Fresh switch state at most every 30 seconds (and always when force is true, after an admin save).
export async function loadPhotoConfig(force) {
  if (!force && Date.now() - loaded < 30000) return cfg;
  try { cfg = await api.photoConfig(); loaded = Date.now(); } catch (e) { /* keep the last known state */ }
  return cfg;
}

export function photosOn() { return !!cfg.enabled; }

// A small square thumbnail for list rows, or null. Decorative (the row names the item), lazy, with a fixed size so rows never shift.
export function photoThumb(item, onclick) {
  const url = photosOn() && item ? photoUrl(item.photo) : null;
  if (!url) return null;
  return h('img', { class: 'photo-thumb', src: url, alt: '', 'aria-hidden': 'true', width: '48', height: '48', loading: 'lazy', decoding: 'async',
    onclick: onclick || null, onerror: (e) => { e.currentTarget.hidden = true; } });
}

// The photo in a fixed 4:3 box (the box is there before the image loads), or null without a photo.
export function photoFigure(item, extraClass) {
  const url = photosOn() && item ? photoUrl(item.photo) : null;
  if (!url) return null;
  return h('div', { class: 'photo-frame' + (extraClass ? ' ' + extraClass : '') }, h('div', { class: 'photo-box' },
    h('img', { src: url, alt: photoAlt(item.name), loading: 'lazy', decoding: 'async' })));
}

// Draw the rect of an image into a JPEG of at most PHOTO_MAX_SIDE on its longest side.
export function toPhotoBlob(img, rect) {
  const r = rect || { sx: 0, sy: 0, sw: img.naturalWidth || img.width, sh: img.naturalHeight || img.height };
  const size = scaledSize(r.sw, r.sh, PHOTO_MAX_SIDE);
  const canvas = document.createElement('canvas');
  canvas.width = size.w;
  canvas.height = size.h;
  const g = canvas.getContext('2d');
  g.fillStyle = '#fff';
  g.fillRect(0, 0, size.w, size.h);
  g.drawImage(img, r.sx, r.sy, r.sw, r.sh, 0, 0, size.w, size.h);
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not prepare that photo'))), 'image/jpeg', 0.9);
  });
}

// The crop dialog. Drag (mouse, touch or pen) or the arrow keys move the photo, the slider, the wheel, a pinch or + and -
// zoom, and Square or Original picks the frame. Resolves a JPEG Blob (Use Photo, or Skip Crop for the whole photo
// downscaled), or null on Cancel or Escape. title names the dialog.
export async function cropPhoto(file, title) {
  const img = await loadImage(file);
  const iw = img.naturalWidth || img.width;
  const ih = img.naturalHeight || img.height;
  return new Promise((resolve) => {
    const previous = document.activeElement;
    const maxW = () => Math.max(160, Math.min(440, window.innerWidth - 56));
    let frame = 'square';
    let f = frameSize(frame, iw, ih, maxW());
    let v = startView(iw, ih, f.w, f.h);
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const canvas = h('canvas', { class: 'crop-canvas', tabindex: '0', role: 'img',
      'aria-label': 'Crop area. Drag or use the arrow keys to move the photo, plus and minus to zoom.' });
    const zoom = h('input', { type: 'range', min: '1', max: String(ZOOM_MAX), step: '0.01', value: '1', id: 'crop-zoom' });
    function size() {
      canvas.width = Math.round(v.w * dpr);
      canvas.height = Math.round(v.h * dpr);
      canvas.style.width = v.w + 'px';
      canvas.style.height = v.h + 'px';
    }
    function draw() {
      const g = canvas.getContext('2d');
      const s = viewScale(v);
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, v.w, v.h);
      g.drawImage(img, v.ox, v.oy, iw * s, ih * s);
      zoom.value = String(v.zoom);
    }
    const set = (next) => { v = next; draw(); };
    const frameBox = h('div', { class: 'chips', role: 'group', 'aria-label': 'Frame' });
    const paintFrames = () => frameBox.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.frame === frame ? 'true' : 'false'));
    FRAMES.forEach((k) => frameBox.appendChild(h('button', { class: 'chip', type: 'button', 'data-frame': k, onclick: () => {
      frame = k;
      f = frameSize(frame, iw, ih, maxW());
      v = reframe(v, f.w, f.h);
      size(); draw(); paintFrames();
    } }, FRAME_LABELS[k])));
    paintFrames();
    zoom.addEventListener('input', () => set(zoomView(v, parseFloat(zoom.value))));

    // Pointers: one drags, two pinch around their middle.
    const pts = new Map();
    let pinch = null;
    const local = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    canvas.addEventListener('pointerdown', (e) => {
      canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, local(e));
      pinch = null;
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!pts.has(e.pointerId)) return;
      const p = local(e);
      const before = pts.get(e.pointerId);
      pts.set(e.pointerId, p);
      if (pts.size === 1) { set(panView(v, p.x - before.x, p.y - before.y)); return; }
      const [a, b] = Array.from(pts.values());
      const d = pointerDistance(a, b);
      if (pinch && pinch > 0) set(zoomView(v, v.zoom * d / pinch, (a.x + b.x) / 2, (a.y + b.y) / 2));
      pinch = d;
    });
    const up = (e) => { pts.delete(e.pointerId); pinch = null; };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const p = local(e);
      set(zoomView(v, v.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1), p.x, p.y));
    }, { passive: false });
    canvas.addEventListener('keydown', (e) => {
      const step = e.shiftKey ? 40 : 10;
      const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
      if (moves[e.key]) { e.preventDefault(); set(panView(v, moves[e.key][0], moves[e.key][1])); } else if (e.key === '+' || e.key === '=') { e.preventDefault(); set(zoomView(v, v.zoom * 1.1)); } else if (e.key === '-' || e.key === '_') { e.preventDefault(); set(zoomView(v, v.zoom / 1.1)); }
    });

    const status = h('div', { 'aria-live': 'polite' });
    const finish = async (rect) => {
      buttons.forEach((b) => { b.disabled = true; });
      try { done(await toPhotoBlob(img, rect)); } catch (err) {
        buttons.forEach((b) => { b.disabled = false; });
        show(status, message(err.message, 'error'));
      }
    };
    const use = h('button', { class: 'btn primary', type: 'button', onclick: () => finish(cropRect(v)) }, 'Use Photo');
    const skip = h('button', { class: 'btn', type: 'button', onclick: () => finish(null) }, 'Skip Crop');
    const cancel = h('button', { class: 'btn ghost', type: 'button', onclick: () => done(null) }, 'Cancel');
    const buttons = [use, skip, cancel];
    const box = h('div', { class: 'notice crop', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'crop-title' },
      h('h2', { id: 'crop-title' }, title || 'Crop Photo'),
      h('p', { class: 'sub' }, 'Drag to move the photo and zoom to fit. Skip Crop keeps the whole photo.'),
      frameBox,
      h('div', { class: 'crop-stage' }, canvas),
      h('label', { class: 'field crop-zoom', for: 'crop-zoom' }, h('span', null, 'Zoom'), zoom),
      status,
      h('div', { class: 'row wrap' }, use, skip, cancel));
    const overlay = h('div', { class: 'overlay crop-overlay' }, box);
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); done(null); return; }
      if (e.key !== 'Tab') return;
      const items = Array.prototype.slice.call(box.querySelectorAll('button, input, canvas[tabindex]')).filter((x) => !x.disabled);
      const i = items.indexOf(document.activeElement);
      e.preventDefault();
      items[(i + (e.shiftKey ? items.length - 1 : 1) + items.length) % items.length].focus();
    }
    function done(blob) {
      document.removeEventListener('keydown', onKey, true);
      overlay.remove();
      if (previous && previous.focus && document.body.contains(previous)) previous.focus();
      resolve(blob);
    }
    document.addEventListener('keydown', onKey, true);
    size();
    draw();
    document.body.appendChild(overlay);
    canvas.focus();
  });
}

// Choose a file (camera allowed on phones through the normal chooser), crop it, and resolve the Blob or null.
export function pickPhoto(title) {
  return new Promise((resolve, reject) => {
    const input = h('input', { type: 'file', accept: 'image/*', class: 'visually-hidden', 'aria-hidden': 'true', tabindex: '-1' });
    input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      input.remove();
      if (!file) { resolve(null); return; }
      try { resolve(await cropPhoto(file, title)); } catch (e) { reject(new Error('That photo could not be opened. Try a JPEG or PNG')); }
    });
    document.body.appendChild(input);
    input.click();
  });
}

// The Photo section of the recipe screen and the food form. kind: 'food' or 'meal'. item: { id, name, photo }.
// canEdit adds Add Photo (or Replace Photo) and Remove Photo; the server checks the owner or admin rule again.
// Returns null when photos are off.
export function photoSection(item, kind, canEdit, onChange) {
  if (!photosOn()) return null;
  const box = h('div', { class: 'photo-section' });
  const status = h('div', { 'aria-live': 'polite' });
  const upload = (blob) => (kind === 'food' ? api.foodPhoto(item.id, blob) : api.mealPhoto(item.id, blob));
  const remove = () => (kind === 'food' ? api.deleteFoodPhoto(item.id) : api.deleteMealPhoto(item.id));
  function paint(focus) {
    clear(box);
    const fig = photoFigure(item);
    if (fig) box.appendChild(fig);
    box.hidden = !fig && !canEdit;
    if (!canEdit) return;
    const add = h('button', { class: 'btn', type: 'button', onclick: choose }, item.photo ? 'Replace Photo' : 'Add Photo');
    const del = item.photo ? h('button', { class: 'btn danger-text', type: 'button', onclick: drop }, 'Remove Photo') : null;
    box.appendChild(h('div', { class: 'row wrap' }, add, del));
    if (focus) add.focus();
  }
  async function choose() {
    let blob;
    try { blob = await pickPhoto(item.photo ? 'Replace Photo' : 'Add Photo'); } catch (e) { show(status, message(e.message, 'error')); return; }
    if (!blob) return;
    if (blob.size > cfg.max_mb * 1024 * 1024) { show(status, message('That photo is larger than ' + cfg.max_mb + ' MB.', 'error')); return; }
    show(status, message('Saving photo...'));
    try {
      item.photo = (await upload(blob)).photo;
      show(status, message('Photo saved.'));
      paint(true);
      if (onChange) onChange(item.photo);
    } catch (e) { show(status, message(e.message, 'error')); }
  }
  async function drop() {
    if (!window.confirm(REMOVE_PHOTO_CONFIRM)) return;
    try {
      await remove();
      item.photo = null;
      show(status, message('Photo removed.'));
      paint(true);
      if (onChange) onChange(null);
    } catch (e) { show(status, message(e.message, 'error')); }
  }
  paint(false);
  return h('div', null, h('h2', null, 'Photo'), box, status);
}

// Import Recipe review: offer the imported screenshots as the recipe photo. draft.photoFiles are the chosen Files;
// draft.photoBlob holds the cropped choice until Save and Continue uploads it.
export function importPhotoChoice(draft) {
  if (!photosOn() || !draft.photoFiles || !draft.photoFiles.length) return null;
  const box = h('div');
  const status = h('div', { 'aria-live': 'polite' });
  let preview = null;
  function paint(focus) {
    clear(box);
    if (preview) { URL.revokeObjectURL(preview); preview = null; }
    if (draft.photoBlob) {
      preview = URL.createObjectURL(draft.photoBlob);
      const change = h('button', { class: 'btn', type: 'button', onclick: () => { draft.photoBlob = null; paint(true); } }, 'Do Not Use a Photo');
      box.appendChild(h('div', { class: 'photo-frame' }, h('div', { class: 'photo-box' }, h('img', { src: preview, alt: 'Chosen recipe photo' }))));
      box.appendChild(h('div', { class: 'row wrap' }, change));
      if (focus) change.focus();
      return;
    }
    const many = draft.photoFiles.length > 1;
    const btns = draft.photoFiles.map((file, i) => h('button', { class: 'btn', type: 'button',
      'aria-label': many ? 'Use Photo ' + (i + 1) + ' As Recipe Photo' : null, onclick: async () => {
        try {
          const blob = await cropPhoto(file, 'Use As Recipe Photo');
          if (blob) { draft.photoBlob = blob; paint(true); }
        } catch (e) { show(status, message('That photo could not be opened.', 'error')); }
      } }, many ? 'Use Photo ' + (i + 1) : 'Use As Recipe Photo'));
    box.appendChild(h('div', { class: 'row wrap' }, btns));
    if (focus) btns[0].focus();
  }
  paint(false);
  return h('div', null, h('h2', null, 'Recipe Photo'),
    h('p', { class: 'sub' }, 'Optional. Use a screenshot as the recipe photo and crop it to the dish.'), box, status);
}
