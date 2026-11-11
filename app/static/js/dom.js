import { sentence } from './util.js';

// Tiny DOM helpers. Text always goes through textContent / text nodes, never innerHTML.

// h('button', {class: 'btn', onclick: fn, 'aria-label': 'x'}, 'Text', childNode)
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const k of Object.keys(attrs || {})) {
    const v = attrs[k];
    if (v == null || v === false) continue;
    if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.appendChild(typeof kid === 'object' ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function select(options, value, attrs) {
  const sel = h('select', attrs || {});
  for (const o of options) sel.appendChild(h('option', { value: o.value, selected: o.value === value }, o.label));
  sel.value = value;
  return sel;
}

// A labelled text input. Returns the wrapper; wrapper.input is the input element.
export function field(label, attrs) {
  const input = h('input', { type: 'text', ...(attrs || {}) });
  const wrap = h('label', { class: 'field' }, h('span', null, label), input);
  wrap.input = input;
  return wrap;
}

export function message(text, kind) {
  return h('p', { class: 'msg ' + (kind || ''), role: kind === 'error' ? 'alert' : 'status' }, sentence(text));
}

// Replace all children of el with node (or nothing).
export function show(el, node) {
  clear(el);
  if (node) el.appendChild(node);
  return el;
}

export function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('That photo could not be opened')); };
    img.src = url;
  });
}

const SVG_NS = 'http://www.w3.org/2000/svg';

// svg('path', {d: '...'}, childNode). Attributes only, never markup strings.
export function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const k of Object.keys(attrs || {})) if (attrs[k] != null && attrs[k] !== false) el.setAttribute(k, attrs[k]);
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.appendChild(typeof kid === 'object' ? kid : document.createTextNode(String(kid)));
  return el;
}

export function cameraIcon() {
  return svg('svg', { viewBox: '0 0 24 24', width: '22', height: '22', fill: 'none', stroke: 'currentColor', 'stroke-width': '2',
    'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false', class: 'icon' },
  svg('path', { d: 'M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z' }),
  svg('circle', { cx: '12', cy: '13', r: '3.5' }));
}
