import { h, field } from './dom.js';
import { MICROS, shownMicros, microValue, microText, microNote, microOver, barWidth, toggleMicro, parseDecimal, fmtAmount } from './util.js';
import { VIEWS, VIEW_LABELS, todayView } from './tablemodel.js';

let seq = 0;

// A heading with a small arrow button that shows or hides body. onToggle(open) runs after each tap.
export function collapsible(title, open, body, onToggle, tag = 'h2') {
  const id = 'fold-' + (++seq);
  body.id = id;
  body.hidden = !open;
  const btn = h('button', { class: 'fold-btn', type: 'button', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': id, onclick: () => {
    const now = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', now ? 'true' : 'false');
    body.hidden = !now;
    if (onToggle) onToggle(now);
  } }, h('span', { class: 'fold-arrow', 'aria-hidden': 'true' }), title);
  return h('div', { class: 'fold' }, h(tag, { class: 'fold-head' }, btn), body);
}

// Today: one bar row per shown nutrient. d is the /api/day payload. Returns null when nothing is shown.
export function microSection(d, display, onToggle) {
  const list = shownMicros(display);
  if (!list.length || !d.micros) return null;
  const rows = list.map((meta) => {
    const m = d.micros[meta.key];
    const text = microText(m, meta.unit);
    const note = microNote(m);
    const kind = meta.kind === 'limit' ? 'Limit' : 'Goal';
    return h('div', { class: 'bar-row micro-row' },
      h('div', { class: 'bar-head' }, h('span', null, meta.label), h('span', null, text)),
      h('div', { class: 'track thin', role: 'progressbar', 'aria-label': meta.label + ' (' + kind.toLowerCase() + ')', 'aria-valuemin': '0', 'aria-valuemax': '100',
        'aria-valuenow': String(barWidth(m.percent)), 'aria-valuetext': text + (note ? ', ' + note : '') },
      h('div', { class: 'fill' + (microOver(m) ? ' over' : ''), style: 'width:' + barWidth(m.percent) + '%' })),
      h('div', { class: 'bar-left' }, kind + (note ? ' · ' + note : '')));
  });
  return collapsible('Micro Nutrients', !!(display && display.micros_open), h('div', { class: 'bars micro-bars' }, rows), onToggle);
}

// Picker: small cells for the shown nutrients (fiber already sits with the macros). update(p) fills them from a preview.
export function microGrid(display, onToggle) {
  const list = shownMicros(display).filter((m) => m.key !== 'fiber');
  if (!list.length) return { el: null, update() {} };
  const cells = {};
  const grid = h('div', { class: 'macros micro-cells' }, list.map((m) => {
    cells[m.key] = h('span', { class: 'macro-v' }, '-');
    return h('div', { class: 'macro' }, cells[m.key], h('span', { class: 'macro-l' }, m.label + ' ' + m.unit));
  }));
  return {
    el: collapsible('Micro Nutrients', !!(display && display.micros_open), grid, onToggle, 'h2'),
    update(p) { list.forEach((m) => { cells[m.key].textContent = microValue(p[m.key], m.unit); }); },
  };
}

function switchRow(id, label, checked, onChange) {
  const box = h('input', { type: 'checkbox', id, checked, onchange: () => {
    const on = box.checked;
    Promise.resolve(onChange(on)).catch(() => { box.checked = !on; });
  } });
  return h('div', { class: 'switch-row' }, h('label', { for: id }, box, h('span', null, label)));
}

// Settings, Display: every change is saved at once through save(patch), which returns the new display settings.
export function displaySection(display, save) {
  let shown = display.micros_shown.slice();
  const flags = [['show_macros', 'Macro Nutrients bars'], ['show_micros', 'Micro Nutrients section'],
    ['show_split', 'Calorie Split chart'], ['show_macro_bar', 'Macro balance bar on foods']];
  const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Micro nutrients to show' }, MICROS.map((m) => {
    const chip = h('button', { class: 'chip', type: 'button', 'aria-pressed': shown.includes(m.key) ? 'true' : 'false', onclick: async () => {
      const next = toggleMicro(shown, m.key);
      chip.setAttribute('aria-pressed', next.includes(m.key) ? 'true' : 'false');
      try { shown = (await save({ micros_shown: next })).micros_shown; } catch (e) { chip.setAttribute('aria-pressed', shown.includes(m.key) ? 'true' : 'false'); }
    } }, m.label);
    return chip;
  }));
  let view = todayView(display);
  const viewBtns = VIEWS.map((v) => {
    const btn = h('button', { class: 'chip', type: 'button', 'aria-pressed': v === view ? 'true' : 'false', onclick: async () => {
      if (v === view) return;
      const prev = view;
      view = v;
      viewBtns.forEach((b, i) => b.setAttribute('aria-pressed', VIEWS[i] === view ? 'true' : 'false'));
      try { view = todayView(await save({ today_view: v })); } catch (e) { view = prev; }
      viewBtns.forEach((b, i) => b.setAttribute('aria-pressed', VIEWS[i] === view ? 'true' : 'false'));
    } }, VIEW_LABELS[v]);
    return btn;
  });
  return h('div', { class: 'display-sec' }, h('h2', null, 'Display'),
    h('p', { class: 'sub' }, 'Choose what Today, the lists and the picker show. Changes apply at once.'),
    flags.map(([k, label]) => switchRow('disp-' + k, label, display[k] !== false, (on) => save({ [k]: on }))),
    h('p', { class: 'field-cap' }, 'Today View'),
    h('div', { class: 'chips', role: 'group', 'aria-label': 'Today view' }, viewBtns),
    h('p', { class: 'field-cap' }, 'Micro nutrients to show'), chips);
}

// Settings, Goals: one field per nutrient. read() returns { targets } or { error }.
export function microTargets(list) {
  const fields = list.map((m) => [m, field(m.label + ' ' + m.unit + (m.kind === 'limit' ? ' (limit)' : ' (goal)'),
    { inputmode: 'decimal', value: fmtAmount(m.target), autocomplete: 'off' })]);
  return {
    node: h('div', null, h('h3', { class: 'sub-head' }, 'Micro Nutrients'),
      h('p', { class: 'sub' }, 'Goals are amounts to reach. Limits are amounts to stay under.'),
      h('div', { class: 'grid3 micro-targets' }, fields.map((f) => f[1]))),
    read() {
      const targets = {};
      for (const [m, f] of fields) {
        const v = parseDecimal(f.input.value);
        f.input.setAttribute('aria-invalid', v > 0 ? 'false' : 'true');
        if (!(v > 0) || v > 100000) return { error: 'Enter a ' + m.label.toLowerCase() + ' target above zero.' };
        targets[m.key] = v;
      }
      return { targets };
    },
  };
}
