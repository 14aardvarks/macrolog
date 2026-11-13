// Saved screen: favorites, recipes and the foods I made, with meal tags, rename, delete and edit.
import { api } from './api.js';
import { h, clear, field, message, show, select, sourceBadge, kcalCue } from './dom.js';
import { refreshAllControl } from './refresh.js';
import { recipeSubText } from './recipeimport.js';
import { DELETE_FOOD_CONFIRM, MEALS, MEAL_LABELS, toggleMeal, fmtNum, amountText, SAVED_FILTERS, SAVED_FILTER_LABELS, filterSavedItems, pageOf, PAGE_SIZE } from './util.js';

const title = (f) => (f.brand ? f.name + ' (' + f.brand + ')' : f.name);

// Toggle chips for the meals. save(meals) persists the new set, or throws.
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
  const del = h('button', { class: 'btn', type: 'button', onclick: async () => {
    if (!window.confirm(DELETE_FOOD_CONFIRM)) return;
    try { await api.deleteFood(fav.food.id); await again(); } catch (e) { show(status, message(e.message, 'error')); }
  } }, 'Delete Food');
  return h('li', { class: 'saved-item' }, h('span', { class: 'item-title' }, title(fav.food)), sourceLine(fav.food),
    chips(fav.meals, async (m) => { await api.favoriteTags(fav.food.id, m); fav.meals = m; }, status), h('div', { class: 'row wrap' }, remove, del), status);
}

// Asks Delete This Recipe?, then deletes through the same route Saved uses. Resolves true when deleted, false when cancelled.
export async function deleteRecipe(rec) {
  if (!window.confirm('Delete This Recipe? "' + rec.name + '" is removed for good. Entries already in your log stay.')) return false;
  await api.deleteMeal(rec.id);
  return true;
}

// The Rename form of a recipe, shown in `body`. again() runs after a save; fail(error) shows a problem.
export function renameRecipe(rec, body, again, fail) {
  const name = field('Recipe name', { value: rec.name, autocomplete: 'off' });
  show(body, h('form', { class: 'row', onsubmit: async (e) => {
    e.preventDefault();
    if (!name.input.value.trim()) return;
    try { await api.patchMeal(rec.id, { name: name.input.value.trim() }); await again(); } catch (err) { fail(err); }
  } }, name, h('button', { class: 'btn primary', type: 'submit' }, 'Save'), h('button', { class: 'btn ghost', type: 'button', onclick: () => show(body, null) }, 'Cancel')));
  name.input.focus();
}

// One recipe with its tags, Rename, Edit Ingredients (or Match Ingredients for one still being matched) and Delete.
// Both open the Match Ingredients page. opts.onDeleted runs after a delete instead of again().
export function recipeRow(rec, again, ctx, opts) {
  const status = h('div', { 'aria-live': 'polite' });
  const body = h('div');
  const fail = (e) => show(status, message(e.message, 'error'));
  const del = async () => {
    try { if (await deleteRecipe(rec)) await (opts && opts.onDeleted ? opts.onDeleted() : again()); } catch (e) { fail(e); }
  };
  return h('li', { class: 'saved-item' }, h('span', { class: 'item-title' }, rec.name),
    h('span', { class: 'item-sub' }, recipeSubText(rec, fmtNum(rec.kcal, 0))),
    chips(rec.meals, async (m) => { await api.patchMeal(rec.id, { meals: m }); rec.meals = m; }, status),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: () => renameRecipe(rec, body, again, fail) }, 'Rename'),
      // Every recipe is edited on Match Ingredients, which keeps an imported recipe's own lines.
      h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('match', { mealId: rec.id, edit: true }) },
        rec.complete && !rec.skipped ? 'Edit Ingredients' : 'Match Ingredients'),
      h('button', { class: 'btn', type: 'button', onclick: del }, 'Delete')),
    body, status);
}

function foodRowMine(food, ctx, again) {
  const status = h('div', { 'aria-live': 'polite' });
  const del = async () => {
    if (!window.confirm(DELETE_FOOD_CONFIRM)) return;
    try { await api.deleteFood(food.id); await again(); } catch (e) { show(status, message(e.message, 'error')); }
  };
  return h('li', { class: 'saved-item' }, h('span', { class: 'item-title' }, title(food)),
    h('span', { class: 'item-sub' }, amountText(food.serving_amount, food.serving_unit) + ' - ' + fmtNum(food.kcal, 0) + ' kcal', ' ', sourceBadge(food.source, true), kcalCue(food)),
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
      section('recipes', 'Recipes', data.recipes, (r) => r.name, (p) => p.map((r) => recipeRow(r, again, ctx)), 'No recipes yet.', true),
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
