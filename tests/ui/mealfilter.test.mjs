import test from 'node:test';
import assert from 'node:assert/strict';
import { filterByMeal, mealWord, emptyText, MEAL_FILTERS, MEAL_FILTER_LABELS, groupByMeal } from '../../app/static/js/util.js';

const items = [
  { id: 1, meal: 'breakfast' }, { id: 2, meal: 'lunch' }, { id: 3, meal: null }, { id: 4, meal: 'lunch' }, { id: 5 },
];

test('filter options and labels', () => {
  assert.deepEqual(MEAL_FILTERS, ['all', 'breakfast', 'lunch', 'dinner', 'snack']);
  assert.deepEqual(MEAL_FILTERS.map((m) => MEAL_FILTER_LABELS[m]), ['All', 'Breakfast', 'Lunch', 'Dinner', 'Snack']);
});

test('filterByMeal keeps everything for all, including items with no meal', () => {
  assert.deepEqual(filterByMeal(items, 'all').map((i) => i.id), [1, 2, 3, 4, 5]);
  assert.deepEqual(filterByMeal(items, undefined).map((i) => i.id), [1, 2, 3, 4, 5]);
  assert.notEqual(filterByMeal(items, 'all'), items);
});

test('filterByMeal matches the meal and drops null meals', () => {
  assert.deepEqual(filterByMeal(items, 'lunch').map((i) => i.id), [2, 4]);
  assert.deepEqual(filterByMeal(items, 'dinner'), []);
  assert.deepEqual(filterByMeal(null, 'lunch'), []);
});

test('filterByMeal uses meals arrays for recipes', () => {
  const rec = [{ id: 1, meals: ['breakfast', 'lunch'] }, { id: 2, meals: [] }, { id: 3, meals: ['dinner'] }];
  assert.deepEqual(filterByMeal(rec, 'lunch').map((i) => i.id), [1]);
  assert.deepEqual(filterByMeal(rec, 'snack'), []);
  assert.deepEqual(filterByMeal(rec, 'all').map((i) => i.id), [1, 2, 3]);
});

test('mealWord', () => {
  assert.equal(mealWord('lunch'), 'lunch');
  assert.equal(mealWord('all'), '');
  assert.equal(mealWord(null), '');
});

test('emptyText names the meal', () => {
  assert.equal(emptyText('yesterday', 'lunch', true), 'Nothing for lunch yesterday.');
  assert.equal(emptyText('yesterday', 'all', false), 'Nothing from yesterday.');
  assert.equal(emptyText('favorites', 'lunch', true), 'No favorites logged as lunch. Choose All to see every favorite.');
  assert.equal(emptyText('recipes', 'snack', true), 'No recipes saved as snack. Choose All to see every recipe.');
  assert.equal(emptyText('favorites', 'all', false), 'No favorites yet. Tap the star on a food to add one.');
  assert.equal(emptyText('favorites', 'lunch', false), 'No favorites yet. Tap the star on a food to add one.');
  assert.equal(emptyText('recipes', 'all', false), 'No saved recipes. On Today, tap "Save today as a recipe".');
});

test('yesterday items group under headings for All', () => {
  const y = [{ meal: 'dinner', kcal: 5 }, { meal: 'breakfast', kcal: 2 }, { meal: 'breakfast', kcal: 3 }];
  assert.deepEqual(groupByMeal(filterByMeal(y, 'all'), 'Other').map((g) => [g.label, g.entries.length]), [['Breakfast', 2], ['Dinner', 1]]);
});
