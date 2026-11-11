// Create Recipe screen: name, ingredients, meal tags and Save. The draft lives in app state (ctx.recipe)
// so it survives the trip to the ingredient finder and the picker.
import { api } from './api.js';
import { h, field, message, show } from './dom.js';
import { amountText, recipeRemoveRow, recipeBody } from './util.js';
import { chips } from './saved.js';

// ctx: { recipe (the draft), back, addIngredient(), adjustIngredient(i), saved() }
export function renderRecipe(root, ctx) {
  const draft = ctx.recipe;
  const status = h('div', { 'aria-live': 'polite' });
  const name = field('Recipe name', { value: draft.name, autocomplete: 'off', enterkeyhint: 'done' });
  name.input.addEventListener('input', () => { draft.name = name.input.value; });

  const rows = draft.rows.map((r, i) => h('li', { class: 'item' },
    h('button', { class: 'item-main', type: 'button', 'aria-label': 'Adjust ' + r.name, onclick: () => ctx.adjustIngredient(i) },
      h('span', { class: 'item-title' }, r.brand ? r.name + ' (' + r.brand + ')' : r.name),
      h('span', { class: 'item-sub' }, amountText(r.amount, r.unit))),
    h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + r.name, onclick: () => {
      draft.rows = recipeRemoveRow(draft.rows, i);
      ctx.refresh();
    } }, '×')));

  const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const r = recipeBody(draft);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    save.disabled = true;
    try { const m = await api.createMeal(r.body); ctx.saved(m); } catch (e) { save.disabled = false; show(status, message(e.message, 'error')); }
  } }, 'Save');

  root.appendChild(h('section', { class: 'screen recipe' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, 'Create Recipe'),
    name,
    h('h2', null, 'Ingredients'),
    rows.length ? h('ul', { class: 'list' }, rows) : h('p', { class: 'sub' }, 'No ingredients yet.'),
    h('button', { class: 'btn', type: 'button', onclick: ctx.addIngredient }, 'Add Ingredient'),
    h('h2', null, 'Meal Tags'),
    h('p', { class: 'sub' }, 'Tags decide where the recipe shows on Add. Untagged recipes show under every meal.'),
    chips(draft.meals, (m) => { draft.meals = m; }, status),
    status, save));
}
