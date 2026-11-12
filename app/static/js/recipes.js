// Recipes tab: New Recipe, Import Recipe and the list of my recipes, plus one recipe's screen with Log and the edit tools
// from Saved. Matching is optional: a recipe with unmatched ingredients opens and logs like any other.
import { api } from './api.js';
import { h, clear, field, message, show, select } from './dom.js';
import { MEALS, MEAL_LABELS, fmtNum, pageOf, PAGE_SIZE, matchedAmountText, stepsCheck, qtyText, SAVED_FILTERS, SAVED_FILTER_LABELS, filterSavedItems,
  RECIPE_SORTS, RECIPE_SORT_LABELS, sortRecipes, sentence } from './util.js';
import { recipeListSub, notCounted, notCountedText, matchState, servingsText, perServingText, tagsText, portionUnits, portionFraction, portionAmount, yieldText } from './recipeimport.js';
import { servingSizeEditor } from './servingsize.js';
import { chips, renameRecipe, deleteRecipe } from './saved.js';
import { stepsList, stepsEditor } from './steps.js';

// The recipe's ingredients as a read only list: "Wheat flour" over "1 1/2 cup, 188 g". Skipped lines keep their own text.
function ingredientList(meal) {
  const LABELS = { skipped: 'Skipped', unmatched: 'Unmatched', check: 'Check Amount' };
  return h('ul', { class: 'list recipe-ings' }, meal.items.map((it) => (matchState(it) !== 'matched'
    ? h('li', { class: 'item' }, h('div', { class: 'item-main' }, h('span', { class: 'item-title' }, (it.src && it.src.text) || (it.food && it.food.name) || 'Ingredient'),
      h('span', { class: 'item-sub' }, LABELS[matchState(it)] + ', not counted')))
    : h('li', { class: 'item' }, h('div', { class: 'item-main' },
      h('span', { class: 'item-title' }, it.food.brand ? it.food.name + ' (' + it.food.brand + ')' : it.food.name),
      h('span', { class: 'item-sub' }, matchedAmountText(it.amount, it.unit, it.grams)))))));
}

// Steps with Edit Steps: the editor works on a copy, Save Steps sends it (PATCH steps), Cancel drops it.
function stepsSection(meal) {
  const box = h('div');
  const status = h('div', { 'aria-live': 'polite' });
  function view(focusEdit) {
    const edit = h('button', { class: 'btn', type: 'button', onclick: editMode }, meal.steps.length ? 'Edit Steps' : 'Add Steps');
    show(box, h('div', null, stepsList(meal.steps), edit));
    if (focusEdit) edit.focus();
  }
  function editMode() {
    const draft = { steps: meal.steps.slice() };
    if (!draft.steps.length) draft.steps.push('');
    const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      const r = stepsCheck(draft.steps);
      if (r.error) { show(status, message(r.error, 'error')); return; }
      save.disabled = true;
      try { meal.steps = (await api.patchMeal(meal.id, { steps: r.steps })).steps; show(status, message('Steps saved.')); view(true); } catch (e) {
        save.disabled = false;
        show(status, message(e.message, 'error'));
      }
    } }, 'Save Steps');
    show(box, h('div', null, stepsEditor(draft), h('div', { class: 'row wrap' }, save,
      h('button', { class: 'btn ghost', type: 'button', onclick: () => { show(status, null); view(true); } }, 'Cancel'))));
    const first = box.querySelector('textarea');
    if (first) first.focus();
  }
  view(false);
  return h('div', null, box, status);
}

// The chosen meal filter and sort stay for the session (this module lives as long as the page); the search text does not.
const listView = { meal: 'all', sort: 'name' };

// ctx: { go, back, newRecipe(), importRecipe(), defaultMeal() }
export async function renderRecipes(root, ctx) {
  const all = (await api.meals()).meals;
  const listBox = h('div');
  let shown = PAGE_SIZE;
  let query = '';
  const open = (m) => ctx.go('recipeview', { mealId: m.id });
  const row = (m) => h('li', { class: 'item' },
    h('button', { class: 'item-main', type: 'button', onclick: () => open(m) },
      h('span', { class: 'item-title' }, m.name),
      h('span', { class: 'item-sub' }, recipeListSub(m, fmtNum(m.kcal, 0)))));
  const q = h('input', { type: 'search', placeholder: 'Search recipes', 'aria-label': 'Search recipes', autocomplete: 'off', enterkeyhint: 'search' });
  const sortSel = select(RECIPE_SORTS.map((s) => ({ value: s, label: RECIPE_SORT_LABELS[s] })), listView.sort, { 'aria-label': 'Sort recipes' });
  const filterBox = h('div', { class: 'chips', role: 'group', 'aria-label': 'Meal filter' });
  const paintChips = () => filterBox.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.meal === listView.meal ? 'true' : 'false'));
  for (const m of SAVED_FILTERS) {
    filterBox.appendChild(h('button', { class: 'chip', type: 'button', 'data-meal': m, onclick: () => { listView.meal = m; shown = PAGE_SIZE; paintChips(); paint(); } }, SAVED_FILTER_LABELS[m]));
  }
  paintChips();
  q.addEventListener('input', () => { query = q.value; shown = PAGE_SIZE; paint(); });
  sortSel.addEventListener('change', () => { listView.sort = sortSel.value; shown = PAGE_SIZE; paint(); });
  function paint() {
    clear(listBox);
    if (!all.length) { listBox.appendChild(message('No recipes yet. Tap New Recipe or Import Recipe, or tap Save As Recipe under a meal on Today.')); return; }
    const items = sortRecipes(filterSavedItems(all, query, listView.meal, (r) => r.name), listView.sort);
    if (!items.length) { listBox.appendChild(h('p', { class: 'sub', role: 'status' }, sentence('No recipes match your search'))); return; }
    const page = pageOf(items, shown);
    listBox.appendChild(h('ul', { class: 'list' }, page.items.map(row)));
    if (page.more) listBox.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => { shown += PAGE_SIZE; paint(); } }, 'Show More'));
  }
  paint();
  root.appendChild(h('section', { class: 'screen recipes' }, h('h1', null, 'Recipes'),
    h('div', { class: 'row wrap recipes-actions' },
      h('button', { class: 'btn primary', type: 'button', onclick: ctx.newRecipe }, 'New Recipe'),
      h('button', { class: 'btn', type: 'button', onclick: ctx.importRecipe }, 'Import Recipe')),
    h('p', { class: 'sub' }, 'Tap a recipe to log or edit it. Ingredients that are not matched are not counted.'),
    h('div', { class: 'saved-filter', role: 'search' }, q, filterBox, h('label', { class: 'meal-pick' }, h('span', null, 'Sort'), sortSel)),
    listBox));
}

// params: { mealId }. Log (meal and how much: servings, % of the recipe or a yield unit, worked out by the server); the
// ingredients with Edit Ingredients (the Match Ingredients page); meal tags, Rename, Steps, Serving Size and Delete Recipe.
// The checklist with Adjust is only for logging a recipe from Add.
export async function renderRecipeView(root, params, ctx) {
  const meal = await api.meal(params.mealId);
  const status = h('div', { 'aria-live': 'polite' });
  const mealSel = select([{ value: 'none', label: MEAL_LABELS.none }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))],
    ctx.defaultMeal(), { 'aria-label': 'Meal' });
  const amount = field('Amount', { inputmode: 'decimal', autocomplete: 'off', value: '1' });
  let units = portionUnits(meal);
  const unitSel = select(units.map((u) => ({ value: u.unit, label: u.label })), 'serving', { 'aria-label': 'Amount unit' });
  let lastUnit = 'serving';
  const subText = () => servingsText(meal) + (meal.yield ? ', ' + yieldText(meal.yield) + ' in all' : '') + ' · ' + tagsText(meal.meals);
  const sub = h('p', { class: 'sub' }, subText());
  const perText = () => 'Per serving: ' + perServingText(meal, (v) => fmtNum(v, 0)) + '.';
  const per = h('p', { class: 'sub' }, perText());
  // After Save Serving Size: new servings or yield change the units and the per serving line, without a repaint.
  function sizeSaved(m) {
    Object.assign(meal, m);
    units = portionUnits(meal);
    if (!units.some((u) => u.unit === unitSel.value)) { unitSel.value = 'serving'; amount.input.value = '1'; }
    const keep = unitSel.value;
    clear(unitSel);
    units.forEach((u) => unitSel.appendChild(h('option', { value: u.unit, selected: u.unit === keep }, u.label)));
    unitSel.value = keep;
    lastUnit = keep;
    sub.textContent = subText();
    per.textContent = perText();
  }
  unitSel.addEventListener('change', () => {  // keep the same share of the recipe in the new unit when the amount reads
    const from = portionFraction(meal, amount.input.value, lastUnit);
    if (!from.error) amount.input.value = qtyText(portionAmount(meal, from.fraction, unitSel.value), unitSel.value);
    lastUnit = unitSel.value;
  });
  const chosenMeal = () => (mealSel.value === 'none' ? null : mealSel.value);
  const logBtn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const r = portionFraction(meal, amount.input.value, unitSel.value);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    logBtn.disabled = true;
    try { await api.logMeal(meal.id, { amount: r.amount, unit: unitSel.value, meal: chosenMeal() }); await ctx.go('today', {}, true); } catch (e) {
      logBtn.disabled = false;
      show(status, message(e.message, 'error'));
    }
  } }, 'Log');
  const deleteStatus = h('div', { 'aria-live': 'polite' });
  async function removeRecipe() {  // back to the Recipes tab list, which sits just below this screen
    try { if (await deleteRecipe(meal)) await ctx.back(); } catch (e) { show(deleteStatus, message(e.message, 'error')); }
  }
  const again = () => ctx.go('recipeview', { mealId: meal.id }, true);  // rename and tags repaint from fresh data
  const tagStatus = h('div', { 'aria-live': 'polite' });
  const renameBox = h('div');
  root.appendChild(h('section', { class: 'screen recipe-view' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, meal.name),
    sub, per,
    h('h2', null, 'Log'),
    h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel),
    h('div', { class: 'grid2 recipe-log' }, amount, h('label', { class: 'field' }, h('span', null, 'Of the recipe'), unitSel)),
    notCounted(meal) ? h('p', { class: 'sub not-counted' }, notCountedText(notCounted(meal))) : null,
    status,
    h('div', { class: 'row wrap' }, logBtn),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('cooking', { mealId: meal.id }) }, 'Cooking')),
    h('h2', null, 'Ingredients'),
    ingredientList(meal),
    h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('match', { mealId: meal.id, edit: true }) }, 'Edit Ingredients'),
    h('h2', null, 'Meal Tags'),
    chips(meal.meals, async (m) => { await api.patchMeal(meal.id, { meals: m }); meal.meals = m; sub.textContent = subText(); }, tagStatus),
    tagStatus,
    h('h2', null, 'Recipe Name'),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: () => renameRecipe(meal, renameBox, again, (e) => show(renameBox, message(e.message, 'error'))) }, 'Rename')),
    renameBox,
    h('h2', null, 'Steps'),
    stepsSection(meal),
    h('h2', null, 'Serving Size'),
    servingSizeEditor(meal, { onSaved: sizeSaved }).el,
    deleteStatus,
    h('button', { class: 'btn danger', type: 'button', onclick: removeRecipe }, 'Delete Recipe')));
}
