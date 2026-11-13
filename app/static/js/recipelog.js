// One recipe log (a recipe logged as one group of ingredient rows): opened from its row on Today, or from Yesterday on Add
// to log it again. Shows the portion, the combined nutrition and the ingredients (read only). Today: change the portion
// (the server rescales every row), move it to another meal, or remove it. Yesterday (params.copy): Log puts a copy on today.
import { api } from './api.js';
import { h, field, message, show, select, sourceBadge, kcalCue } from './dom.js';
import { MEALS, MEAL_LABELS, fmtNum, qtyText, amountText, amountMemo, ingredientText } from './util.js';
import { portionUnits, portionFraction, portionAmount, recipeAmountText, scaledLog, partsText, REMOVE_RECIPE_CONFIRM } from './recipeimport.js';
import { fillMacroBar } from './chart.js';
import { microGrid } from './micros.js';

const cell = (label) => {
  const v = h('span', { class: 'macro-v' }, '-');
  return { v, el: h('div', { class: 'macro' }, v, h('span', { class: 'macro-l' }, label)) };
};

// params: { groupId, copy?, meal? }  ctx: { go, back, display, saveDisplay, defaultMeal }
export async function renderRecipeLog(root, params, ctx) {
  const log = await api.logGroup(params.groupId);
  const copy = !!params.copy;
  const display = ctx.display || {};
  const units = portionUnits(log);
  let unit = units.some((u) => u.unit === log.unit) ? log.unit : 'serving';
  let frac = log.fraction;
  const status = h('div', { 'aria-live': 'polite' });
  const startMeal = copy && params.meal !== undefined ? params.meal : log.meal;
  const mealSel = select([{ value: 'none', label: MEAL_LABELS.none }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))],
    startMeal || 'none', { 'aria-label': 'Meal' });
  const memo = amountMemo(unit === log.unit ? log.amount : null);
  const amount = field('Amount', { inputmode: 'decimal', autocomplete: 'off', value: unit === log.unit ? memo.set(log.amount, unit) : qtyText(log.amount, unit) });
  const unitSel = select(units.map((u) => ({ value: u.unit, label: u.label })), unit, { 'aria-label': 'Amount unit' });
  const portionLine = h('p', { class: 'sub', 'aria-live': 'polite' });
  const kcal = h('span', null, '-');
  const cells = { carbs: cell('Carbs g'), protein: cell('Protein g'), fat: cell('Fat g'), fiber: cell('Fiber g') };
  const bar = display.show_macro_bar !== false ? h('span', { class: 'macro-bar', role: 'img', hidden: '' }) : null;
  const micros = microGrid(display, (open) => { if (ctx.saveDisplay) ctx.saveDisplay({ micros_open: open }).catch(() => {}); });

  function paint(v, amt) {
    portionLine.textContent = (copy ? 'Yesterday ' + recipeAmountText(log.amount, log.unit) : recipeAmountText(amt, unit))
      + ' · ' + partsText((log.parts || []).length);
    kcal.textContent = fmtNum(v.kcal, 0);
    ['carbs', 'protein', 'fat'].forEach((k) => { cells[k].v.textContent = fmtNum(v[k], 1); });
    cells.fiber.v.textContent = v.fiber == null ? '-' : fmtNum(v.fiber, 1);
    if (bar) fillMacroBar(bar, v);
    micros.update(v);
  }
  // The live numbers follow the amount box; nothing is saved until Save Changes (or Log).
  function preview() {
    const r = portionFraction(log, memo.read(amount.input.value), unitSel.value);
    if (r.error) { show(status, message(r.error, 'error')); return null; }
    show(status, null);
    frac = r.fraction;
    unit = unitSel.value;
    paint(scaledLog(log, frac), r.amount);
    return r;
  }
  amount.input.addEventListener('input', preview);
  unitSel.addEventListener('change', () => {  // the same share of the recipe in the new unit
    amount.input.value = memo.set(portionAmount(log, frac, unitSel.value), unitSel.value);
    preview();
  });

  const chosenMeal = () => (mealSel.value === 'none' ? null : mealSel.value);
  const saveBtn = h('button', { class: 'btn primary', type: 'button', onclick: save }, copy ? 'Log' : 'Save Changes');
  async function save() {
    const r = preview();
    if (!r) return;
    const portion = { amount: r.amount, unit: unitSel.value };
    const changed = unitSel.value !== log.unit || Math.abs(r.amount - log.amount) > 1e-9;
    const body = copy ? { ...portion, meal: chosenMeal() } : { ...(changed ? portion : {}), ...(chosenMeal() !== log.meal ? { meal: chosenMeal() } : {}) };
    saveBtn.disabled = true;
    try {
      if (copy) await api.copyGroup(log.group_id, body);
      else if (Object.keys(body).length) await api.patchGroup(log.group_id, body);
      await ctx.go('today', {}, true);
    } catch (e) {
      saveBtn.disabled = false;
      show(status, message(e.message, 'error'));
    }
  }
  const removeStatus = h('div', { 'aria-live': 'polite' });
  async function remove() {
    if (!window.confirm(REMOVE_RECIPE_CONFIRM)) return;
    try { await api.deleteGroup(log.group_id); await ctx.go('today', {}, true); } catch (e) { show(removeStatus, message(e.message, 'error')); }
  }

  const parts = h('ul', { class: 'list recipe-ings' }, (log.parts || []).map((p) => {
    const badge = sourceBadge(p.source, true);
    const name = p.brand ? p.name + ' (' + p.brand + ')' : p.name;
    const bare = !p.unit || p.unit === 'count';  // a count reads "3 carrots", the amount joins the name
    return h('li', { class: 'item' }, h('div', { class: 'item-main' },
      h('span', { class: 'item-title' }, bare ? ingredientText(p.amount, p.unit, name) : name),
      h('span', { class: 'item-sub' }, (bare ? '' : amountText(p.amount, p.unit) + ' - ') + fmtNum(p.kcal, 0) + ' kcal', badge ? ' ' : null, badge, kcalCue(p))));
  }));
  root.appendChild(h('section', { class: 'screen recipe-log-view' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, log.name),
    portionLine,
    h('div', { class: 'kcal-big' }, kcal, ' kcal'),
    h('div', { class: 'macros' }, cells.carbs.el, cells.protein.el, cells.fat.el, cells.fiber.el),
    bar ? h('div', { class: 'pick-bar' }, bar) : null,
    micros.el,
    h('h2', null, copy ? 'Log Again' : 'Change'),
    h('div', { class: 'grid2 recipe-log' }, amount, h('label', { class: 'field' }, h('span', null, 'Of the recipe'), unitSel)),
    h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel),
    status,
    saveBtn,
    h('h2', null, 'Ingredients'),
    parts,
    copy ? null : removeStatus,
    copy ? null : h('button', { class: 'btn danger', type: 'button', onclick: remove }, 'Remove Recipe')));
  paint(log, log.amount);
}
