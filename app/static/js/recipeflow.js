// Import Recipe (step 1: source, then a review draft) and Match Ingredients (step 2). The recipe is saved at the end of
// step 1 with every ingredient unmatched, so leaving step 2 at any point keeps what was matched so far.
import { api } from './api.js';
import { h, clear, field, message, show, sourceBadge } from './dom.js';
import { toJpeg } from './ai.js';
import { confirmClaude } from './notice.js';
import { chips } from './saved.js';
import { fmtNum, fmtAmount, amountText, centsText, sentence, parseAmount, MICROS, microValue } from './util.js';
import {
  parseIngredientText, reviewDraft, reviewBody, blankRow, matchState, matchCountText, nextUnmatched, toggleAll, toggleId,
  matchBatch, proposalText, matchWhat, importWhat,
} from './recipeimport.js';

const MAX_PHOTOS = 3;
const MAX_TEXT = 20000;  // same as ai.RECIPE_TEXT_MAX on the server
const bar = (ctx) => h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back'));
const costLine = (cost, what) => (cost == null ? null : h('p', { class: 'sub' }, what + ' cost about ' + centsText(cost) + '.'));

// ---------- step 1: source ----------

// ctx.flow.input keeps { kind, text, note } for the visit, so Back from the review screen finds the text again.
export async function renderImport(root, ctx) {
  const input = ctx.flow.input;
  let st = null;
  try { st = await api.aiStatus(); } catch (e) { st = { enabled: false }; }
  const aiOn = !!st.enabled;
  const status = h('div', { 'aria-live': 'polite' });
  const panel = h('div');
  const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Recipe source' }, [['text', 'Paste Text'], ['photos', 'Photos']].map(([k, label]) =>
    h('button', { type: 'button', role: 'tab', 'data-kind': k, onclick: () => { input.kind = k; paint(); } }, label)));

  const area = h('textarea', { rows: '10', maxlength: String(MAX_TEXT), autocomplete: 'off', placeholder: 'Paste the recipe or just its ingredient list' });
  area.value = input.text || '';
  area.addEventListener('input', () => { input.text = area.value; });
  const note = field('Note for Claude (optional)', { autocomplete: 'off', value: input.note || '', maxlength: '300', placeholder: 'e.g. use the second recipe on the page' });
  note.input.addEventListener('input', () => { input.note = note.input.value; });
  const files = h('input', { type: 'file', accept: 'image/*', multiple: '', class: 'visually-hidden', onchange: onFiles });
  const fileList = h('p', { class: 'sub' }, 'No photos chosen.');
  let chosen = [];

  const readText = h('button', { class: 'btn primary', type: 'button', onclick: sendText }, 'Read With Claude');
  const splitText = h('button', { class: 'btn', type: 'button', onclick: splitLocal }, 'Split Lines Without Claude');
  const readPhotos = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: sendPhotos }, 'Read With Claude');
  const noAi = aiOn ? null : message('Claude is not set up for you, so paste the ingredient list and split the lines without Claude.');

  function paint() {
    tabs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', b.dataset.kind === input.kind ? 'true' : 'false'));
    show(status, null);
    if (input.kind === 'photos') {
      show(panel, h('div', null,
        h('p', { class: 'sub' }, 'Photos or screenshots of the ingredient list, up to 3. Claude reads them and you check the result.'),
        aiOn ? [h('label', { class: 'btn' }, 'Choose or Take Photos', files), fileList, note, h('div', { class: 'row wrap' }, readPhotos)] : noAi));
    } else {
      show(panel, h('div', null,
        h('label', { class: 'field' }, h('span', null, 'Recipe text'), area),
        h('p', { class: 'sub' }, 'Split Lines Without Claude reads one ingredient per line and costs nothing. Claude copes with whole pages.'),
        aiOn ? note : noAi, h('div', { class: 'row wrap' }, aiOn ? readText : null, splitText)));
    }
  }
  function onFiles() {
    chosen = Array.prototype.slice.call(files.files || [], 0, MAX_PHOTOS);
    fileList.textContent = chosen.length ? chosen.length + (chosen.length === 1 ? ' photo: ' : ' photos: ') + chosen.map((f) => f.name).join(', ') : 'No photos chosen.';
    readPhotos.disabled = !chosen.length;
  }
  const done = (recipe, extra) => { ctx.flow.draft = reviewDraft(recipe, extra); ctx.go('importreview'); };
  function splitLocal() {
    const r = parseIngredientText(area.value);
    if (!r.ingredients.length) { show(status, message('Paste at least one ingredient line first.', 'error')); return; }
    done(r, { warnings: [] });
  }
  async function sendText() {
    const text = area.value;
    if (!text.trim()) { show(status, message('Paste the recipe text first.', 'error')); return; }
    readText.disabled = true;
    try {
      if (!(await confirmClaude(ctx.settings, { what: importWhat('text', text.length), query: { recipe_chars: text.length } }))) return;
      show(status, message('Claude is reading the recipe...'));
      const r = await api.recipeFromText(text, note.input.value.trim());
      done(r.recipe, { warnings: r.warnings, cost: r.cost });
    } catch (e) { show(status, message(e.message, 'error')); } finally { readText.disabled = false; }
  }
  async function sendPhotos() {
    readPhotos.disabled = true;
    try {
      if (!(await confirmClaude(ctx.settings, { what: importWhat('photos', chosen.length), query: { recipe_images: chosen.length } }))) return;
      show(status, message('Preparing photos...'));
      const form = new FormData();
      for (let i = 0; i < chosen.length; i++) form.append('images', await toJpeg(chosen[i]), 'recipe' + (i + 1) + '.jpg');
      if (note.input.value.trim()) form.append('hint', note.input.value.trim());
      show(status, message('Claude is reading the recipe...'));
      const r = await api.recipeFromPhotos(form);
      done(r.recipe, { warnings: r.warnings, cost: r.cost });
    } catch (e) { show(status, message(e.message, 'error')); } finally { readPhotos.disabled = !chosen.length; }
  }

  root.appendChild(h('section', { class: 'screen import' }, bar(ctx), h('h1', null, 'Import Recipe'),
    h('p', { class: 'sub' }, 'Step 1 of 2. Bring in the ingredient list, then match each ingredient to a food.'),
    tabs, panel, status));
  paint();
}

// ---------- step 1: review ----------

export function renderReview(root, ctx) {
  const draft = ctx.flow.draft;
  if (!draft) { ctx.go('import', {}, true); return; }
  const status = h('div', { 'aria-live': 'polite' });
  const name = field('Recipe name', { value: draft.name, autocomplete: 'off' });
  name.input.addEventListener('input', () => { draft.name = name.input.value; });
  const servings = field('Servings it makes (optional)', { value: draft.servings, inputmode: 'decimal', autocomplete: 'off' });
  servings.input.addEventListener('input', () => { draft.servings = servings.input.value; });
  const list = h('ol', { class: 'list import-rows' });
  const warns = (draft.warnings || []).map((w) => h('li', null, sentence(w)));

  function rowNode(r, i) {
    const box = (key, label, attrs) => {
      const f = field(label, { value: r[key], autocomplete: 'off', ...(attrs || {}) });
      f.input.addEventListener('input', () => { r[key] = f.input.value; });
      f.classList.add('import-' + key);
      return f;
    };
    return h('li', { class: 'import-row' },
      h('div', { class: 'import-fields' }, box('amount', 'Amount', { inputmode: 'decimal' }), box('unit', 'Unit', { autocapitalize: 'none' }),
        box('name', 'Ingredient'), box('note', 'Note')),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ingredient ' + (i + 1) + (r.name ? ', ' + r.name : ''),
        onclick: () => { draft.rows.splice(i, 1); paintRows(); } }, '×'));
  }
  function paintRows(focusLast) {
    clear(list);
    draft.rows.forEach((r, i) => list.appendChild(rowNode(r, i)));
    if (!draft.rows.length) list.appendChild(h('li', { class: 'sub' }, 'No ingredients yet.'));
    if (focusLast) { const last = list.querySelector('li:last-child .import-name input'); if (last) last.focus(); }
  }
  const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const r = reviewBody(draft);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    save.disabled = true;
    try { const meal = await api.importMeal(r.body); ctx.flow.saved(meal); } catch (e) { save.disabled = false; show(status, message(e.message, 'error')); }
  } }, 'Save and Continue');

  root.appendChild(h('section', { class: 'screen import' }, bar(ctx), h('h1', null, 'Check the Recipe'),
    h('p', { class: 'sub' }, 'Step 1 of 2. Fix anything that looks wrong. Nothing is saved until you tap Save and Continue.'),
    costLine(draft.cost, 'This read'),
    warns.length ? h('ul', { class: 'warnings', role: 'alert' }, warns) : null,
    name, servings,
    h('h2', null, 'Ingredients'), list,
    h('button', { class: 'btn', type: 'button', onclick: () => { draft.rows.push(blankRow()); paintRows(true); } }, 'Add Ingredient'),
    h('h2', null, 'Meal Tags'),
    h('p', { class: 'sub' }, 'Tags decide where the recipe shows on Add. Untagged recipes show under every meal.'),
    chips(draft.meals, (m) => { draft.meals = m; }, status),
    status,
    h('div', { class: 'row wrap' }, save, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.flow.cancel }, 'Cancel'))));
  paintRows();
}

// ---------- step 2: match ingredients ----------

const NUTRIENT_ROWS = [['kcal', 'Calories', ''], ['carbs', 'Carbs', 'g'], ['protein', 'Protein', 'g'], ['fat', 'Fat', 'g'],
  ...MICROS.map((m) => [m.key, m.label, m.unit])];

function totalsTable(meal) {
  const per = meal.per_serving;
  return h('table', { class: 'match-totals' },
    h('caption', { class: 'visually-hidden' }, 'Nutrition per serving'),
    h('tbody', null, NUTRIENT_ROWS.map(([k, label, unit]) => h('tr', null, h('th', { scope: 'row' }, label),
      h('td', null, per[k] == null ? '-' : k === 'kcal' ? fmtNum(per[k], 0) : microValue(per[k], unit) + ' ' + unit)))));
}

function foodLine(it) {
  const f = it.food;
  return h('span', { class: 'item-sub' }, (f.brand ? f.name + ' (' + f.brand + ')' : f.name) + ' ', sourceBadge(f.source, true),
    ' - ' + amountText(it.amount, it.unit) + ' - ' + fmtNum(it.kcal, 0) + ' kcal');
}

// params: { mealId, saved? (just saved by Import, shows Step 2 of 2) }
export async function renderMatch(root, params, ctx) {
  let meal = await api.meal(params.mealId);
  let st = null;
  try { st = await api.aiStatus(); } catch (e) { st = { enabled: false }; }
  const aiOn = !!st.enabled;
  const props = ctx.flow.proposals(meal.id);  // Claude proposals waiting for Accept, kept while the user searches
  let selected = ctx.flow.selection(meal.id).filter((id) => meal.items.some((i) => i.id === id && !i.skipped));
  let current = meal.items.findIndex((i) => i.id === ctx.flow.takeFocus());
  const status = h('div', { 'aria-live': 'polite' });
  const count = h('p', { class: 'match-count', 'aria-live': 'polite' });
  const list = h('ul', { class: 'list match-list' });
  const totals = h('div');
  const allBox = h('input', { type: 'checkbox', id: 'match-all', onchange: () => { selected = toggleAll(meal.items, selected); keepSel(); paintRows(); } });
  const matchBtn = h('button', { class: 'btn', type: 'button', onclick: () => runMatch(selected) }, 'Match Selected With Claude');
  const servings = field('Servings it makes', { value: fmtAmount(meal.servings), inputmode: 'decimal', autocomplete: 'off' });
  servings.input.addEventListener('change', async () => {
    const v = parseAmount(servings.input.value);
    if (v == null || v <= 0 || v > 1000) { show(status, message('Servings must be a number above zero.', 'error')); return; }
    try { meal = await api.patchMeal(meal.id, { servings: v }); paintTotals(); } catch (e) { show(status, message(e.message, 'error')); }
  });
  const keepSel = () => ctx.flow.setSelection(meal.id, selected);
  const fail = (e) => show(status, message(e.message, 'error'));

  async function apply(itemId, body) {
    try {
      meal = await api.matchItem(meal.id, itemId, body);
      delete props[itemId];
      selected = selected.filter((x) => x !== itemId);
      keepSel();
      paintAll(itemId);
    } catch (e) { fail(e); }
  }
  async function accept(item, p) {
    try {
      const food = p.food.id ? p.food : await api.createFood(p.food);  // a Claude estimate becomes a food only now
      await apply(item.id, { food_id: food.id, amount: p.amount, unit: p.unit });
    } catch (e) { fail(e); }
  }
  async function runMatch(ids) {
    const b = matchBatch(ids);
    if (!b.send.length) { show(status, message('Tick at least one ingredient first.', 'error')); return; }
    matchBtn.disabled = true;
    try {
      if (!(await confirmClaude(ctx.settings, { what: matchWhat(b.send.length), query: { match_rows: b.send.length } }))) return;
      show(status, message('Claude is matching ' + b.send.length + (b.send.length === 1 ? ' ingredient...' : ' ingredients...')));
      const r = await api.matchIngredients(meal.id, b.send);
      r.proposals.forEach((p) => { props[p.item_id] = p; });
      selected = selected.filter((id) => b.send.indexOf(id) < 0);
      keepSel();
      paintRows();
      const left = b.rest.length ? ' ' + b.rest.length + ' more are still ticked. Tap Match Selected With Claude again for them.' : '';
      show(status, message('Check each suggestion, then tap Accept.' + (r.cost != null ? ' This cost about ' + centsText(r.cost) + '.' : '') + left));
    } catch (e) { fail(e); } finally { matchBtn.disabled = false; }
  }

  function proposalBox(item, p) {
    const est = p.kind === 'estimate';
    const kcal = p.preview ? ' - ' + fmtNum(p.preview.kcal, 0) + ' kcal' : '';
    return h('div', { class: 'proposal', role: 'group', 'aria-label': 'Claude suggestion' },
      h('p', { class: 'proposal-head' }, 'Claude Suggests ', p.food ? sourceBadge(p.food.source, true) : null,
        p.kind === 'candidate' ? h('span', { class: 'src-est' }, ' Database Match') : null),
      h('p', null, proposalText(p) + (p.food ? kcal : '')),
      p.food && p.note ? h('p', { class: 'sub' }, sentence(p.note)) : null,
      est ? h('p', { class: 'sub' }, 'No database food fitted, so this is an estimate. Accept saves it as a Claude food.') : null,
      p.warnings && p.warnings.length ? h('ul', { class: 'warnings' }, p.warnings.map((w) => h('li', null, sentence(w)))) : null,
      h('div', { class: 'row wrap' },
        p.food ? h('button', { class: 'btn primary', type: 'button', onclick: () => accept(item, p) }, 'Accept') : null,
        h('button', { class: 'btn', type: 'button', onclick: () => { delete props[item.id]; ctx.flow.find(meal, item, 'search'); } }, p.food ? 'Change' : 'Search'),
        p.food ? null : h('button', { class: 'btn', type: 'button', onclick: () => apply(item.id, { skipped: true }) }, 'Skip')));
  }

  function rowNode(item, i) {
    const state = matchState(item);
    const label = (item.src && item.src.text) || (item.food && item.food.name) || 'Ingredient';
    const box = aiOn && !item.skipped ? h('input', { type: 'checkbox', checked: selected.indexOf(item.id) >= 0, 'aria-label': 'Select ' + label,
      onchange: () => { selected = toggleId(selected, item.id); keepSel(); paintHead(); } }) : null;
    const stateNode = state === 'matched' ? foodLine(item)
      : h('span', { class: 'item-sub' }, h('span', { class: 'match-state match-' + state }, state === 'skipped' ? 'Skipped' : 'Unmatched'));
    const p = props[item.id];
    return h('li', { class: 'match-row' + (i === current ? ' current' : ''), id: 'ing-' + item.id, tabindex: '-1',
      'aria-current': i === current ? 'true' : null },
    h('div', { class: 'match-top' }, box, h('div', { class: 'match-text' }, h('span', { class: 'item-title' }, label), stateNode)),
    h('div', { class: 'row wrap match-actions' },
      h('button', { class: 'btn small', type: 'button', onclick: () => ctx.flow.find(meal, item, 'search') }, 'Search'),
      h('button', { class: 'btn small', type: 'button', onclick: () => ctx.flow.find(meal, item, 'scan') }, 'Scan Barcode'),
      aiOn ? h('button', { class: 'btn small', type: 'button', onclick: () => runMatch([item.id]) }, 'Ask Claude') : null,
      h('button', { class: 'btn small', type: 'button', 'aria-pressed': item.skipped ? 'true' : 'false',
        onclick: () => apply(item.id, { skipped: !item.skipped }) }, item.skipped ? 'Unskip' : 'Skip')),
    p ? proposalBox(item, p) : null);
  }

  function paintHead() {
    count.textContent = matchCountText(meal);
    const open = meal.items.filter((i) => matchState(i) === 'unmatched').map((i) => i.id);
    allBox.checked = open.length > 0 && open.every((id) => selected.indexOf(id) >= 0);
    matchBtn.disabled = !selected.length;
  }
  function paintRows() {
    clear(list);
    meal.items.forEach((it, i) => list.appendChild(rowNode(it, i)));
    paintHead();
  }
  function paintTotals() {
    show(totals, h('div', null,
      h('h2', null, 'Per Serving'),
      h('p', { class: 'sub' }, meal.complete ? 'For 1 of ' + fmtAmount(meal.servings) + ' servings.'
        : 'For 1 of ' + fmtAmount(meal.servings) + ' servings, counting matched ingredients only.'),
      totalsTable(meal),
      meal.complete ? message('Every ingredient is matched or skipped. Log the recipe from Add, then Recipes.') : null));
  }
  function paintAll(focusId) {
    paintRows();
    paintTotals();
    if (focusId != null) { const el = document.getElementById('ing-' + focusId); if (el) el.focus(); }
  }
  function saveAndNext() {
    const next = nextUnmatched(meal.items, current < 0 ? null : current);
    if (next < 0) { show(status, message('Every ingredient is matched or skipped.')); return; }
    current = next;
    paintRows();
    const el = document.getElementById('ing-' + meal.items[next].id);
    if (el) { el.scrollIntoView({ block: 'center' }); el.focus({ preventScroll: true }); }
  }

  root.appendChild(h('section', { class: 'screen match' }, bar(ctx), h('h1', null, 'Match Ingredients'),
    params.saved ? h('p', { class: 'saved-note', role: 'status' }, h('span', { class: 'saved-tag' }, 'Saved'), h('span', null, 'Step 2 of 2')) : null,
    h('p', { class: 'sub' }, 'The recipe is saved. Match each ingredient to a food. Progress is kept as you go, so you can leave and come back from Recipes.'),
    h('h2', null, meal.name), count,
    aiOn ? h('div', { class: 'row wrap match-bulk' }, h('label', { class: 'check', for: 'match-all' }, allBox, ' Select All'), matchBtn)
      : h('p', { class: 'sub' }, 'Claude is not set up for you, so use Search or Scan Barcode for each ingredient.'),
    status, list, servings, totals,
    h('div', { class: 'row wrap match-foot' },
      h('button', { class: 'btn primary', type: 'button', onclick: saveAndNext }, 'Save and Next'),
      h('button', { class: 'btn', type: 'button', onclick: ctx.flow.exit }, 'Save and Exit'))));
  paintRows();
  paintTotals();
  if (current >= 0) {
    const id = meal.items[current].id;
    root.addEventListener('mounted', () => { const el = document.getElementById('ing-' + id); if (el) { el.scrollIntoView({ block: 'center' }); el.focus({ preventScroll: true }); } });
  }
}
