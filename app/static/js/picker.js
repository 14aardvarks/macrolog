import { api } from './api.js';
import { h, clear, select, message, show } from './dom.js';
import { fillMacroBar } from './chart.js';
import { microGrid } from './micros.js';
import {
  MEALS, MEAL_LABELS, parseAmount, fmtNum, fmtAmount, indexFromScroll, debounce, guessMeal,
  initialPick, startPreset, convertAmount, gramsFor, SERVING, PCT, amountText, amountLabel, amountValues, withValue,
} from './util.js';

const ROW = 44;
const PAD = 2;  // blank rows above and below, so the chosen row sits in the middle of five

// A vertical scroll-snap wheel. items: [{ text, est }]. onPick(i) runs when the row under the band changes;
// onTap(i, wasSelected) runs when a row is tapped. Programmatic placement is locked so it never reports a pick.
function makeWheel(prefix, label, onPick, onTap) {
  let count = 0;
  let idx = 0;
  let lock = false;
  const el = h('div', { class: 'wheel', tabindex: '0', role: 'listbox', 'aria-label': label,
    style: 'height:' + ROW * (2 * PAD + 1) + 'px', onscroll: () => { if (!lock) pick(indexFromScroll(el.scrollTop, ROW, count)); }, onkeydown: onKey });
  const wrap = h('div', { class: 'wheel-wrap' }, el, h('div', { class: 'wheel-band', 'aria-hidden': 'true' }));
  function blank() { return h('div', { style: 'height:' + ROW + 'px', 'aria-hidden': 'true' }); }
  function mark() {
    el.querySelectorAll('.wheel-item').forEach((row, i) => {
      row.setAttribute('aria-selected', i === idx ? 'true' : 'false');
      row.classList.toggle('on', i === idx);
    });
    el.setAttribute('aria-activedescendant', prefix + idx);
  }
  function pick(i) {
    if (i === idx) return;
    idx = i;
    mark();
    onPick(i);
  }
  function place() {
    lock = true;
    el.scrollTop = idx * ROW;
    setTimeout(() => { el.scrollTop = idx * ROW; }, 0);
    setTimeout(() => { lock = false; }, 150);
  }
  function move(i) {
    const n = Math.max(0, Math.min(count - 1, i));
    el.scrollTop = n * ROW;
    pick(n);
  }
  function onKey(e) {
    const k = { ArrowUp: -1, ArrowDown: 1, PageUp: -5, PageDown: 5 }[e.key];
    if (k !== undefined) move(idx + k);
    else if (e.key === 'Home') move(0);
    else if (e.key === 'End') move(count - 1);
    else return;
    e.preventDefault();
  }
  // Replace all rows and select row i. Never reports a pick.
  function set(items, i) {
    clear(el);
    count = items.length;
    idx = i;
    for (let k = 0; k < PAD; k++) el.appendChild(blank());
    items.forEach((it, k) => el.appendChild(h('div', { class: 'wheel-item', role: 'option', id: prefix + k,
      'aria-selected': 'false', style: 'height:' + ROW + 'px', onclick: () => { const was = k === idx; move(k); onTap(k, was); } },
    it.text, it.est ? h('span', { class: 'est' }, 'est') : null)));
    for (let k = 0; k < PAD; k++) el.appendChild(blank());
    mark();
    place();
  }
  return { el, wrap, set, place, get index() { return idx; } };
}

function macroCell(label, id) {
  return h('div', { class: 'macro' }, h('span', { class: 'macro-v', id }, '-'), h('span', { class: 'macro-l' }, label));
}

// params: { foodId, amount?, unit?, meal? (string or null), entryId? }  ctx: { go, back, settings }
export async function renderPicker(root, params, ctx) {
  const food = await api.food(params.foodId);
  const edit = params.entryId != null;
  const adjust = params.adjust && params.adjust.index != null ? params.adjust.index : null;  // picking for a recipe row
  const units = food.units;
  const st = { amount: 1, unit: '', idx: 0, seq: 0, ref: null, fav: !!food.favorite };
  Object.assign(st, initialPick(units, startPreset(edit || adjust != null, params, food, ctx.settings && ctx.settings.use_last)));
  st.ref = { amount: st.amount, unit: st.unit };  // last amount the user chose; unit changes convert from here so rounding never piles up
  st.idx = Math.max(0, units.findIndex((u) => u.unit === st.unit));

  const meals = [{ value: 'none', label: MEAL_LABELS.none }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))];
  const meal = params.meal !== undefined ? params.meal : (ctx.settings && ctx.settings.default_meal) || guessMeal(new Date().getHours());
  const mealSel = select(meals, meal || 'none', { 'aria-label': 'Meal' });

  const unitWheel = makeWheel('unit-', 'Unit', (i) => pickUnit(i), () => {});
  const amtWheel = makeWheel('amt-', 'Amount', (i) => setAmount(amtValues[i]), (i, was) => { if (was) startTyping(); });
  const amountIn = h('input', { type: 'text', inputmode: 'decimal', class: 'amount-input', 'aria-label': 'Amount', autocomplete: 'off',
    enterkeyhint: 'done', oninput: onType, onblur: () => finishTyping(false), onkeydown: onAmountKey });
  const typeBox = h('div', { class: 'type-box', hidden: '', style: 'height:' + (ROW * (2 * PAD + 1) + 2) + 'px' }, amountIn);
  const typeBtn = h('button', { class: 'type-btn', type: 'button', onclick: startTyping }, '\u270E Type');
  let amtValues = [];
  let typing = false;
  const sub = h('p', { class: 'sub' });
  const baseLine = h('p', { class: 'sub base-line', hidden: '' });
  const gramLine = h('p', { class: 'gram-line', 'aria-live': 'polite' });
  const star = h('button', { class: 'star', type: 'button', onclick: toggleFav });
  const estBadge = h('p', { class: 'badge', hidden: '' }, 'Estimated conversion');
  const status = h('div', { 'aria-live': 'polite' });
  const logBtn = h('button', { class: 'btn primary', type: 'button', onclick: save }, adjust != null ? 'Done' : edit ? 'Save Changes' : 'Log');

  const kcal = h('span', { id: 'pv-kcal' }, '-');
  const display = ctx.display || {};
  const showBar = display.show_macro_bar !== false;
  const mbar = h('div', { class: 'pick-bar' }, h('span', { class: 'macro-bar', role: 'img', hidden: '' }));
  const micros = microGrid(display, (open) => { if (ctx.saveDisplay) ctx.saveDisplay({ micros_open: open }).catch(() => {}); });
  root.appendChild(h('section', { class: 'screen picker' },
    h('div', { class: 'bar' },
      h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back'), h('span', { class: 'spacer' }), adjust != null ? null : star),
    h('h1', null, food.name),
    sub, baseLine,
    h('div', { class: 'pick-row' },
      h('div', { class: 'pick-col' }, h('span', { class: 'pick-cap' }, 'Amount'), amtWheel.wrap, typeBox, typeBtn),
      h('div', { class: 'pick-col' }, h('span', { class: 'pick-cap' }, 'Unit'), unitWheel.wrap)),
    gramLine,
    h('div', { class: 'kcal-big' }, kcal, ' kcal'),
    h('div', { class: 'macros' }, macroCell('Carbs g', 'pv-carbs'), macroCell('Protein g', 'pv-protein'),
      macroCell('Fat g', 'pv-fat'), macroCell('Fiber g', 'pv-fiber')),
    showBar ? mbar : null, micros.el, estBadge,
    adjust != null ? null : h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel),
    status, logBtn,
    edit ? h('button', { class: 'btn danger', type: 'button', onclick: remove }, 'Remove Entry') : null));

  const preview = debounce(runPreview, 180);
  paintStar();
  unitWheel.set(units.map((u) => ({ text: u.label, est: u.estimated })), st.idx);
  buildAmounts();
  paintGrams();
  runPreview();

  function curUnit() { return units.find((u) => u.unit === st.unit) || units[0]; }

  // Rows for the current unit. The chosen amount is always one of them, even when it is off the step grid.
  function buildAmounts() {
    const r = withValue(amountValues(st.unit, curUnit().step, st.amount), st.amount);
    amtValues = r.values;
    amtWheel.set(amtValues.map((v) => ({ text: amountLabel(st.unit, v) })), r.index);
  }
  // Keep the same quantity in the new unit, then refresh macros.
  function pickUnit(idx) {
    if (idx === st.idx && units[idx].unit === st.unit) return;
    const next = units[idx];
    st.amount = convertAmount(units, st.ref.amount, st.ref.unit, next.unit);
    st.unit = next.unit;
    st.idx = idx;
    buildAmounts();
    paintGrams();
    preview();
  }
  function setAmount(v) {
    st.amount = v;
    st.ref = { amount: v, unit: st.unit };
    paintGrams();
    preview();
  }

  function startTyping() {
    if (typing) return;
    typing = true;
    amountIn.value = fmtAmount(st.amount);
    amountIn.setAttribute('aria-invalid', 'false');
    amtWheel.wrap.hidden = true;
    typeBtn.style.visibility = 'hidden';  // keeps the layout still, so a tap on Log still lands
    typeBox.hidden = false;
    amountIn.focus();
    amountIn.select();
  }
  function onType() {
    const v = parseAmount(amountIn.value);
    amountIn.setAttribute('aria-invalid', v != null && v > 0 ? 'false' : 'true');
  }
  // Apply the typed amount (when valid) and go back to the wheel. cancel keeps the old amount.
  function finishTyping(cancel, refocus) {
    if (!typing) return;
    typing = false;
    const v = cancel ? null : parseAmount(amountIn.value);
    typeBox.hidden = true;
    typeBtn.style.visibility = '';
    amtWheel.wrap.hidden = false;
    if (v != null && v > 0) { st.amount = v; st.ref = { amount: v, unit: st.unit }; }
    buildAmounts();
    paintGrams();
    if (v != null && v > 0) preview();
    if (refocus) amtWheel.el.focus();
  }
  function onAmountKey(e) {
    if (e.key === 'Enter') { e.preventDefault(); finishTyping(false, true); }
    else if (e.key === 'Escape') { e.preventDefault(); finishTyping(true, true); }
  }
  function paintSub() {
    const pseudo = st.unit === SERVING || st.unit === PCT;
    const label = food.label_text || '';
    const tail = pseudo ? amountText(st.amount, st.unit) + (label ? ' of ' + label : '') : label;
    sub.textContent = [food.brand, tail].filter(Boolean).join(' - ');
    paintBase();
  }
  // One label serving expressed in the selected unit, shown under the label text (hidden for the label unit, serving and %).
  function paintBase() {
    const u = units.find((x) => x.unit === st.unit);
    const show = u && st.unit !== units[0].unit && st.unit !== SERVING && st.unit !== PCT && u.default_amount > 0;
    baseLine.hidden = !show;
    baseLine.textContent = show ? '1 serving = ' + fmtNum(u.default_amount, u.default_amount >= 10 ? 0 : 2) + ' ' + u.label + (u.estimated ? ' (estimated)' : '') : '';
  }
  function paintGrams() {
    paintSub();
    const g = gramsFor(units, st.amount, st.unit);
    gramLine.textContent = g == null ? '' : '= ' + fmtNum(g, g >= 10 ? 0 : 1) + ' g';
  }

  async function runPreview() {
    const seq = ++st.seq;
    try {
      const p = await api.preview(food.id, st.amount, st.unit);
      if (seq !== st.seq) return;
      root.querySelector('#pv-kcal').textContent = fmtNum(p.kcal, 0);
      root.querySelector('#pv-carbs').textContent = fmtNum(p.carbs, 1);
      root.querySelector('#pv-protein').textContent = fmtNum(p.protein, 1);
      root.querySelector('#pv-fat').textContent = fmtNum(p.fat, 1);
      root.querySelector('#pv-fiber').textContent = p.fiber == null ? '-' : fmtNum(p.fiber, 1);
      fillMacroBar(mbar.firstChild, p);
      micros.update(p);
      estBadge.hidden = !p.estimated;
      if (status.firstChild) clear(status);
    } catch (e) {
      if (seq === st.seq) show(status, message(e.message, 'error'));
    }
  }

  function paintStar() {
    star.textContent = st.fav ? '★' : '☆';
    star.setAttribute('aria-pressed', st.fav ? 'true' : 'false');
    star.setAttribute('aria-label', st.fav ? 'Remove from favorites' : 'Add to favorites');
  }
  async function toggleFav() {
    st.fav = !st.fav;
    paintStar();
    try { await api.favorite(food.id, st.fav); } catch (e) {
      st.fav = !st.fav;
      paintStar();
      show(status, message(e.message, 'error'));
    }
  }

  async function save() {
    const m = mealSel.value === 'none' ? null : mealSel.value;
    finishTyping(false);
    if (adjust != null) { ctx.finishAdjust(adjust, st.amount, st.unit, food); return; }  // hands the pick back, logs nothing
    logBtn.disabled = true;
    try {
      if (edit) await api.patchEntry(params.entryId, { amount: st.amount, unit: st.unit, meal: m });
      else await api.logEntry({ food_id: food.id, amount: st.amount, unit: st.unit, meal: m });
      ctx.go('today', {}, true);
    } catch (e) {
      logBtn.disabled = false;
      show(status, message(e.message, 'error'));
    }
  }
  async function remove() {
    try { await api.deleteEntry(params.entryId); ctx.go('today', {}, true); } catch (e) {
      show(status, message(e.message, 'error'));
    }
  }
}
