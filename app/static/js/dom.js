import { sentence, sourceLabel, kcalEstimated, KCAL_ESTIMATE_CUE, isEstimate, sourceNote, CUSTOM_UNIT, CUSTOM_UNIT_LABEL, CUSTOM_UNIT_MAX, CUSTOM_UNIT_HINT, cleanUnitText, unitToSave, checkList, checkSummary, estimateList, estimateSummary, weightTag, tagGrams } from './util.js';

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

// A unit select with a Custom choice that reveals a text box for the user's own unit. choices: [{value, label}] (no blank choice).
// Returns a wrapper that works like a select: .value reads the unit to save ('' when Custom is empty) and can be set, 'change'
// fires on the wrapper when the choice or the typed text changes, .focus() focuses the select.
export function unitControl(choices, value, attrs) {
  const sel = h('select', attrs || {});
  for (const o of choices) sel.appendChild(h('option', { value: o.value }, o.label));
  sel.appendChild(h('option', { value: CUSTOM_UNIT }, CUSTOM_UNIT_LABEL));
  const label = (attrs && attrs['aria-label']) || 'Unit';
  const box = h('input', { type: 'text', class: 'unit-custom', maxlength: CUSTOM_UNIT_MAX, placeholder: CUSTOM_UNIT_HINT, autocomplete: 'off',
    autocapitalize: 'none', enterkeyhint: 'done', 'aria-label': label + ', your own', hidden: '' });
  const wrap = h('div', { class: 'unit-control' }, sel, box);
  const known = (v) => choices.some((o) => o.value === v);
  function put(v) {
    const unit = v == null ? '' : String(v);
    if (known(unit)) { sel.value = unit; box.value = ''; } else { sel.value = CUSTOM_UNIT; box.value = cleanUnitText(unit); }
    box.hidden = sel.value !== CUSTOM_UNIT;
  }
  sel.addEventListener('change', () => { box.hidden = sel.value !== CUSTOM_UNIT; if (!box.hidden) box.focus(); });
  box.addEventListener('input', () => wrap.dispatchEvent(new Event('change', { bubbles: true })));
  Object.defineProperty(wrap, 'value', { get: () => (sel.value === CUSTOM_UNIT ? unitToSave(box.value) : sel.value), set: put });
  wrap.focus = () => sel.focus();
  put(value);
  return wrap;
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

// A tiny text badge naming where a food came from, or null when the source is unknown. The word is always shown, so color is never the only cue.
// Claude foods also get the word Estimate, so a list row says the values are not from a database.
export function sourceBadge(source, withEstimate) {
  const label = sourceLabel(source);
  if (!label) return null;
  const est = withEstimate && isEstimate(source);
  return h('span', { class: 'src-wrap' }, h('span', { class: 'src src-' + source }, label), est ? h('span', { class: 'src-est' }, 'Estimate') : null);
}

// A small cue after calories that the server estimated them from the macros, or null. The words are always shown.
export function kcalCue(x) {
  return kcalEstimated(x) ? h('span', { class: 'src-wrap' }, h('span', { class: 'src-est kcal-cue' }, KCAL_ESTIMATE_CUE)) : null;
}

// The recipe header notes on amounts (issue #45): "2 ingredients need a check" with the first reason under it ("Garlic: no
// standard weight for clove, enter grams"), and "3 amounts are estimated" with the first ingredient and its source ("Garlic: 6 g,
// Typical Weight"); the rest of each list is collapsed. Text says it all, the chip only repeats it. null when there is neither.
function noteList(kind, chipText, summary, list) {
  const [first, ...rest] = list;
  return h('div', { class: 'check-list ' + kind, role: 'note' },
    h('p', { class: 'check-summary' }, h('span', { class: 'match-state ' + (kind === 'checks' ? 'match-check' : 'match-est') }, chipText), ' ', summary),
    h('p', { class: 'sub check-first' }, first.text),
    rest.length ? h('details', { class: 'check-more' }, h('summary', null, 'Show ' + rest.length + ' More'),
      h('ul', { class: 'sub' }, rest.map((x) => h('li', null, x.text)))) : null);
}
export function checkBlock(meal) {
  const checks = checkList(meal).filter((x) => x.check);
  const est = estimateList(meal);
  if (!checks.length && !est.length) return null;
  return h('div', { class: 'check-notes' },
    checks.length ? noteList('checks', 'Check Amount', checkSummary(checks), checks) : null,
    est.length ? noteList('estimates', 'Estimated', estimateSummary(est.length), est) : null);
}

// The Estimated Weight tag (issue #45 step 8): "Estimated Weight 6 g, Typical Weight", the grams a button when onSave is given.
// Tapping the grams swaps them in place for a small grams box with Save and Cancel; onSave(grams) returns a promise, and an error
// keeps the box open with the message. Text names the source, so nothing depends on color.
export function weightTagNode(it, name, onSave) {
  const t = weightTag(it);
  if (!t) return null;
  const grams = fmtGrams(t.grams);
  const tag = h('span', { class: 'weight-tag' + (t.estimated ? ' weight-est' : '') });
  const err = h('span', { class: 'weight-err', role: 'alert' });
  function view(focus) {
    clear(tag);
    const g = onSave ? h('button', { class: 'link-btn weight-grams', type: 'button', 'aria-label': 'Edit grams of ' + name + ', ' + grams + ', ' + t.word,
      onclick: edit }, grams) : h('span', { class: 'weight-grams' }, grams);
    tag.append(h('span', { class: 'weight-label' }, t.label), ' ', g, ' ', h('span', { class: 'weight-src' }, t.word));
    if (focus) g.focus();
  }
  function edit() {
    clear(tag);
    const box = h('input', { class: 'weight-input', inputmode: 'decimal', autocomplete: 'off', value: String(Math.round(t.grams * 10) / 10),
      'aria-label': 'Grams of ' + name, size: '5' });
    const save = async () => {
      const v = tagGrams(box.value);
      if (v == null) { err.textContent = 'Enter grams above zero.'; box.setAttribute('aria-invalid', 'true'); box.focus(); return; }
      ok.disabled = true;
      try { await onSave(v); } catch (e) { ok.disabled = false; err.textContent = e.message || 'Could not save the grams.'; box.focus(); }
    };
    const ok = h('button', { class: 'btn small primary', type: 'button', onclick: save }, 'Save');
    box.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } else if (e.key === 'Escape') { err.textContent = ''; view(true); } });
    tag.append(box, ' g ', ok, ' ',
      h('button', { class: 'btn small ghost', type: 'button', onclick: () => { err.textContent = ''; view(true); } }, 'Cancel'), err);
    box.focus();
    box.select();
  }
  view(false);
  return tag;
}
const fmtGrams = (g) => (g >= 10 ? String(Math.round(g)) : String(Math.round(g * 10) / 10)) + ' g';

// A line for the picker and the food form: the badge, and for Claude foods the estimate note.
export function sourceLine(source) {
  const b = sourceBadge(source);
  return b ? h('p', { class: 'sub src-line' }, 'Source ', b, isEstimate(source) ? ' ' + sourceNote(source) : null) : null;
}

// Link to a page outside the app, opened in a new tab.
export function extLink(href, text) {
  return h('a', { href, target: '_blank', rel: 'noopener noreferrer' }, text);
}
