// Recipes tab: New Recipe, Import Recipe and the list of my recipes, plus one recipe's screen with Log and the edit tools
// from Saved. A partial recipe (unmatched ingredients) opens Match Ingredients instead.
import { api } from './api.js';
import { h, clear, field, message, show, select } from './dom.js';
import { MEALS, MEAL_LABELS, fmtNum, pageOf, PAGE_SIZE, matchedAmountText, stepsCheck, qtyText } from './util.js';
import { recipeListSub, servingsText, perServingText, tagsText, portionUnits, portionFraction, portionAmount, yieldText } from './recipeimport.js';
import { servingSizeEditor } from './servingsize.js';
import { recipeRow, deleteRecipe } from './saved.js';
import { stepsList, stepsEditor } from './steps.js';

// The recipe's ingredients as a read only list: "Wheat flour" over "1 1/2 cup, 188 g". Skipped lines keep their own text.
function ingredientList(meal) {
  return h('ul', { class: 'list recipe-ings' }, meal.items.map((it) => (it.skipped || !it.food
    ? h('li', { class: 'item' }, h('div', { class: 'item-main' }, h('span', { class: 'item-title' }, (it.src && it.src.text) || 'Ingredient'),
      h('span', { class: 'item-sub' }, 'Skipped')))
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

// ctx: { go, back, newRecipe(), importRecipe(), defaultMeal() }
export async function renderRecipes(root, ctx) {
  const all = (await api.meals()).meals;
  const listBox = h('div');
  let shown = PAGE_SIZE;
  const open = (m) => (m.complete ? ctx.go('recipeview', { mealId: m.id }) : ctx.go('match', { mealId: m.id }));
  const row = (m) => h('li', { class: 'item' },
    h('button', { class: 'item-main', type: 'button', onclick: () => open(m) },
      h('span', { class: 'item-title' }, m.name),
      h('span', { class: 'item-sub' }, recipeListSub(m, fmtNum(m.kcal, 0)))));
  function paint() {
    const page = pageOf(all, shown);
    clear(listBox);
    if (!all.length) { listBox.appendChild(message('No recipes yet. Tap New Recipe or Import Recipe, or tap Save As Recipe under a meal on Today.')); return; }
    listBox.appendChild(h('ul', { class: 'list' }, page.items.map(row)));
    if (page.more) listBox.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => { shown += PAGE_SIZE; paint(); } }, 'Show More'));
  }
  paint();
  root.appendChild(h('section', { class: 'screen recipes' }, h('h1', null, 'Recipes'),
    h('div', { class: 'row wrap recipes-actions' },
      h('button', { class: 'btn primary', type: 'button', onclick: ctx.newRecipe }, 'New Recipe'),
      h('button', { class: 'btn', type: 'button', onclick: ctx.importRecipe }, 'Import Recipe')),
    h('p', { class: 'sub' }, 'Tap a recipe to log or edit it. A recipe with unmatched ingredients opens Match Ingredients.'),
    listBox));
}

// params: { mealId }. Log (meal and how much: servings, % of the recipe or a yield unit, worked out by the server), or Adjust
// Items for the checklist; then Serving Size and the Saved tools.
export async function renderRecipeView(root, params, ctx) {
  const meal = await api.meal(params.mealId);
  if (!meal.complete) { await ctx.go('match', { mealId: meal.id }, true); return; }
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
  const adjust = h('button', { class: 'btn', type: 'button', onclick: () => {
    const r = portionFraction(meal, amount.input.value, unitSel.value);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    ctx.go('meal', { mealId: meal.id, meal: mealSel.value, amount: r.amount, unit: unitSel.value, nav: 'recipes' });
  } }, 'Adjust Items');
  const deleteStatus = h('div', { 'aria-live': 'polite' });
  async function removeRecipe() {  // back to the Recipes tab list, which sits just below this screen
    try { if (await deleteRecipe(meal)) await ctx.back(); } catch (e) { show(deleteStatus, message(e.message, 'error')); }
  }
  const again = () => ctx.go('recipeview', { mealId: meal.id }, true);  // rename, tags and items repaint from fresh data
  root.appendChild(h('section', { class: 'screen recipe-view' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, meal.name),
    sub, per,
    h('h2', null, 'Log'),
    h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel),
    h('div', { class: 'grid2 recipe-log' }, amount, h('label', { class: 'field' }, h('span', null, 'Of the recipe'), unitSel)),
    status,
    h('div', { class: 'row wrap' }, logBtn, adjust),
    h('p', { class: 'sub' }, 'Adjust Items lets you untick ingredients or change amounts for this log only.'),
    h('h2', null, 'Ingredients'),
    ingredientList(meal),
    h('h2', null, 'Steps'),
    stepsSection(meal),
    h('h2', null, 'Serving Size'),
    servingSizeEditor(meal, { onSaved: sizeSaved }).el,
    h('h2', null, 'Edit'),
    h('ul', { class: 'list' }, recipeRow(meal, again, ctx, { noDelete: true })),
    deleteStatus,
    h('button', { class: 'btn danger', type: 'button', onclick: removeRecipe }, 'Delete Recipe')));
}
