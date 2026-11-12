import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MEALS, MEAL_LABELS, groupByMeal, guessMeal, filterByMeal, filterSaved, filterSavedItems, toggleMeal, mealWord, emptyText,
  recipeBody, newRecipeDraft,
} from '../../app/static/js/util.js';
import { tagsText } from '../../app/static/js/recipeimport.js';
import { buildTable } from '../../app/static/js/tablemodel.js';

test('dessert is the fifth meal, after snack', () => {
  assert.deepEqual(MEALS, ['breakfast', 'lunch', 'dinner', 'snack', 'dessert']);
  assert.equal(MEAL_LABELS.dessert, 'Dessert');
  assert.equal(mealWord('dessert'), 'dessert');
});

test('Today groups put dessert in its own group after snack, before No meal', () => {
  const g = groupByMeal([{ meal: 'dessert', kcal: 300 }, { meal: null, kcal: 1 }, { meal: 'snack', kcal: 50 }, { meal: 'dessert', kcal: 20 }]);
  assert.deepEqual(g.map((x) => [x.meal, x.label, x.kcal]), [['snack', 'Snack', 50], ['dessert', 'Dessert', 320], [null, 'No meal', 1]]);
});

test('guessMeal never picks dessert', () => {
  for (let h = 0; h < 24; h++) assert.notEqual(guessMeal(h), 'dessert', 'hour ' + h);
});

test('Add filter: tagged dessert items and untagged items show under Dessert', () => {
  const it = [{ id: 1, meals: ['dessert'] }, { id: 2, meals: [] }, { id: 3, meals: ['snack'] }, { id: 4 },
    { id: 5, meals: ['dinner', 'dessert'], counts: { dessert: 3 } }];
  assert.deepEqual(filterSaved(it, 'dessert').map((i) => i.id), [5, 1, 2, 4]);
  assert.deepEqual(filterSaved(it, 'snack').map((i) => i.id), [2, 3, 4]);
  assert.deepEqual(filterByMeal([{ id: 1, meal: 'dessert' }, { id: 2, meal: 'snack' }], 'dessert').map((i) => i.id), [1]);
  assert.equal(emptyText('yesterday', 'dessert', true), 'Nothing for dessert yesterday.');
  assert.equal(emptyText('recipes', 'dessert', true), 'No recipes tagged dessert. Choose All to see every recipe.');
});

test('Saved filter is strict for dessert', () => {
  const it = [{ name: 'Pie', meals: ['dessert'] }, { name: 'Soup', meals: [] }, { name: 'Chips', meals: ['snack'] }];
  const f = (meal) => filterSavedItems(it, '', meal, (i) => i.name).map((i) => i.name);
  assert.deepEqual(f('dessert'), ['Pie']);
  assert.deepEqual(f('untagged'), ['Soup']);
});

test('tags keep breakfast to dessert order', () => {
  assert.deepEqual(toggleMeal(['dessert'], 'breakfast'), ['breakfast', 'dessert']);
  assert.deepEqual(toggleMeal(['snack', 'dessert'], 'dessert'), ['snack']);
  assert.equal(tagsText(['dessert', 'lunch']), 'Lunch, Dessert');
  const d = newRecipeDraft(0);
  d.name = 'Pie';
  d.meals = ['dessert', 'snack'];
  d.rows = [{ food_id: 1, amount: 1, unit: 'slice' }];
  assert.deepEqual(recipeBody(d).body.meals, ['snack', 'dessert']);
});

test('Table view has a Dessert subtotal group after Snack', () => {
  const t = buildTable([{ id: 1, meal: 'dessert', name: 'Pie', kcal: 300, carbs: 40, protein: 3, fat: 14 },
    { id: 2, meal: 'snack', name: 'Chips', kcal: 150, carbs: 15, protein: 2, fat: 10 }], { show_macros: true, micros_shown: [] });
  assert.deepEqual(t.groups.map((g) => g.label), ['Snack', 'Dessert']);
  assert.equal(t.count, 2);
});
