// Saved screen: favorites, recipes and the foods I made, with meal tags, rename, delete and edit.
import { api } from './api.js';
import { h, clear, field, message, show, select, sourceBadge } from './dom.js';
import { refreshAllControl } from './refresh.js';
import { MEALS, MEAL_LABELS, toggleMeal, parseAmount, fmtAmount, unitLabel, fmtNum, amountText, SAVED_FILTERS, SAVED_FILTER_LABELS, filterSavedItems, pageOf, PAGE_SIZE } from './util.js';

const title = (f) => (f.brand ? f.name + ' (' + f.brand + ')' : f.name);

// Toggle chips for the four meals. save(meals) persists the new set, or throws.
export function chips(meals, save, status) {
  let now = meals.slice();
  const box = h('div', { class: 'chips', role: 'group', 'aria-label': 'Meal tags' });
  const paint = () => box.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', now.includes(b.dataset.meal) ? 'true' : 'false'));
  for (const m of MEALS) {
    box.appendChild(h('button', { class: 'chip', type: 'button', 'data-meal': m, onclick: async () => {
      const before = now;
      now = toggleMeal(now, m);
      paint();
      try { await save(now); show(status, null); } catch (e) { now = before; paint(); show(status, message(e.message, 'error')); }
    } }, MEAL_LABELS[m]));
  }
  paint();
  return box;
}

// Favorites have no sub line, so the source gets a small line of its own.
const sourceLine = (food) => { const b = sourceBadge(food.source, true); return b ? h('span', { class: 'item-sub' }, b) : null; };

function favoriteRow(fav, again) {
  const status = h('div', { 'aria-live': 'polite' });
  const remove = h('button', { class: 'btn', type: 'button', onclick: async () => {
    if (!window.confirm('Remove "' + fav.food.name + '" from your favorites, tags, Recent and Yesterday? Your past log stays.')) return;
    try { await api.removeFromLists(fav.food.id); await again(); } catch (e) { show(status, message(e.message, 'error')); }
  } }, 'Remove From My Lists');
  return h('li', { class: 'saved-item' }, h('span', { class: 'item-title' }, title(fav.food)), sourceLine(fav.food),
    chips(fav.meals, async (m) => { await api.favoriteTags(fav.food.id, m); fav.meals = m; }, status), h('div', { class: 'row wrap' }, remove), status);
}

function recipeRow(rec, again) {
  const status = h('div', { 'aria-live': 'polite' });
  const body = h('div');
  const fail = (e) => show(status, message(e.message, 'error'));
  const rename = () => {
    const name = field('Recipe name', { value: rec.name, autocomplete: 'off' });
    show(body, h('form', { class: 'row', onsubmit: async (e) => {
      e.preventDefault();
      if (!name.input.value.trim()) return;
      try { await api.patchMeal(rec.id, { name: name.input.value.trim() }); await again(); } catch (err) { fail(err); }
    } }, name, h('button', { class: 'btn primary', type: 'submit' }, 'Save'), h('button', { class: 'btn ghost', type: 'button', onclick: () => show(body, null) }, 'Cancel')));
    name.input.focus();
  };
  const items = async () => {
    let foods;
    try { foods = await Promise.all(rec.items.map((it) => api.food(it.food_id))); } catch (e) { fail(e); return; }
    const rows = rec.items.map((it, i) => {
      const amt = h('input', { type: 'text', inputmode: 'decimal', value: fmtAmount(it.amount), 'aria-label': 'Amount of ' + it.food.name });
      const unit = select(foods[i].units.map((u) => ({ value: u.unit, label: unitLabel(u.unit) })), it.unit, { 'aria-label': 'Unit of ' + it.food.name });
      const li = h('li', { class: 'item meal-item' }, h('span', { class: 'item-title' }, it.food.name), amt, unit,
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + it.food.name, onclick: () => { li.remove(); row.gone = true; } }, '×'));
      const row = { it, amt, unit, gone: false };
      return { row, li };
    });
    const save = async () => {
      const out = [];
      for (const { row } of rows) {
        if (row.gone) continue;
        const a = parseAmount(row.amt.value);
        if (a == null || a <= 0) { show(status, message('Check the amount for ' + row.it.food.name + '.', 'error')); return; }
        out.push({ food_id: row.it.food_id, amount: a, unit: row.unit.value });
      }
      if (!out.length) { show(status, message('A recipe needs at least one item. Delete the recipe instead.', 'error')); return; }
      try { await api.patchMeal(rec.id, { items: out }); await again(); } catch (e) { fail(e); }
    };
    show(body, h('div', null, h('ul', { class: 'list' }, rows.map((r) => r.li)),
      h('div', { class: 'row' }, h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save Items'),
        h('button', { class: 'btn ghost', type: 'button', onclick: () => show(body, null) }, 'Cancel'))));
  };
  const del = async () => {
    if (!window.confirm('Delete the recipe "' + rec.name + '"?')) return;
    try { await api.deleteMeal(rec.id); await again(); } catch (e) { fail(e); }
  };
  return h('li', { class: 'saved-item' }, h('span', { class: 'item-title' }, rec.name),
    h('span', { class: 'item-sub' }, rec.items.length + ' items - ' + fmtNum(rec.kcal, 0) + ' kcal'),
    chips(rec.meals, async (m) => { await api.patchMeal(rec.id, { meals: m }); rec.meals = m; }, status),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: rename }, 'Rename'),
      h('button', { class: 'btn', type: 'button', onclick: items }, 'Edit Items'), h('button', { class: 'btn', type: 'button', onclick: del }, 'Delete')),
    body, status);
}

function foodRowMine(food, ctx, again) {
  const status = h('div', { 'aria-live': 'polite' });
  const del = async () => {
    if (!window.confirm('Delete the food "' + food.name + '"?')) return;
    try { await api.deleteFood(food.id); await again(); } catch (e) { show(status, message(e.message, 'error')); }
  };
  return h('li', { class: 'saved-item' }, h('span', { class: 'item-title' }, title(food)),
    h('span', { class: 'item-sub' }, amountText(food.serving_amount, food.serving_unit) + ' - ' + fmtNum(food.kcal, 0) + ' kcal', ' ', sourceBadge(food.source, true)),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('editfood', { food }) }, 'Edit'),
      h('button', { class: 'btn', type: 'button', onclick: del }, 'Delete')), status);
}

export async function renderSaved(root, ctx) {
  let data = await api.saved();
  const view = { query: '', meal: 'all', shown: { favorites: PAGE_SIZE, recipes: PAGE_SIZE, foods: PAGE_SIZE } };
  // Remove, delete and rename reload the data and repaint in place, so the search text and filter stay.
  const again = async () => { data = await api.saved(); paint(); };
  const q = h('input', { type: 'search', placeholder: 'Search saved items', 'aria-label': 'Search saved items', autocomplete: 'off', enterkeyhint: 'search' });
  const mealSel = select(SAVED_FILTERS.map((m) => ({ value: m, label: SAVED_FILTER_LABELS[m] })), 'all', { 'aria-label': 'Meal' });
  const lists = h('div');
  const bulk = refreshAllControl(() => data.foods, again);  // one node, so its summary survives repaints
  const reset = () => { view.shown = { favorites: PAGE_SIZE, recipes: PAGE_SIZE, foods: PAGE_SIZE }; paint(); };
  q.addEventListener('input', () => { view.query = q.value; reset(); });
  mealSel.addEventListener('change', () => { view.meal = mealSel.value; reset(); });

  // key names the section. all is the unfiltered list, rows builds the nodes for the visible page.
  const section = (key, name, all, text, rows, empty, tagged, extra) => {
    const items = filterSavedItems(all, view.query, tagged ? view.meal : 'all', text);  // My foods have no tags
    const page = pageOf(items, view.shown[key]);
    const filtering = view.query.trim() !== '' || (tagged && view.meal !== 'all');
    return h('div', null, h('h2', null, name), extra,
      items.length ? h('ul', { class: 'list' }, rows(page.items)) : h('p', { class: 'sub' }, all.length && filtering ? 'Nothing matches.' : empty),
      page.more ? h('button', { class: 'btn', type: 'button', onclick: () => { view.shown[key] += PAGE_SIZE; paint(); } }, 'Show More') : null);
  };
  function paint() {
    clear(lists).append(
      section('favorites', 'Favorites', data.favorites, (f) => title(f.food), (p) => p.map((f) => favoriteRow(f, again)), 'No favorites yet.', true),
      section('recipes', 'Recipes', data.recipes, (r) => r.name, (p) => p.map((r) => recipeRow(r, again)), 'No recipes yet.', true),
      section('foods', 'My Foods', data.foods, (f) => title(f), (p) => p.map((f) => foodRowMine(f, ctx, again)), 'Foods you create by hand or with Claude appear here.', false, bulk.el));
    bulk.update();
  }
  paint();
  root.appendChild(h('section', { class: 'screen saved' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, 'Saved'),
    h('p', { class: 'sub' }, 'Meal tags decide where a favorite or recipe shows on Add. Untagged items show under every meal.'),
    h('div', { class: 'saved-filter', role: 'search' }, q, h('label', { class: 'meal-pick' }, h('span', null, 'Meal'), mealSel)),
    h('p', { class: 'sub' }, 'The meal filter applies to favorites and recipes.'),
    lists));
}
