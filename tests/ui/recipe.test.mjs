import test from 'node:test';
import assert from 'node:assert/strict';
import {
  newRecipeDraft, recipeAddRow, recipeSetRow, recipeRemoveRow, recipeBody, stepsBack, matchesQuery, filterSavedItems,
  SAVED_FILTERS, SAVED_FILTER_LABELS, emptyText, pageOf, PAGE_SIZE,
} from '../../app/static/js/util.js';

const rice = { id: 4, name: 'Rice', brand: 'Acme' };

test('draft rows add, set and remove without changing the old array', () => {
  const a = [];
  const b = recipeAddRow(a, rice, 1.5, 'cup');
  assert.deepEqual(a, []);
  assert.deepEqual(b, [{ food_id: 4, name: 'Rice', brand: 'Acme', amount: 1.5, unit: 'cup' }]);
  const c = recipeAddRow(b, { id: 5, name: 'Oil' }, 1, 'tbsp');
  assert.equal(c[1].brand, null);
  assert.deepEqual(recipeSetRow(c, 1, 2, 'tsp').map((r) => [r.amount, r.unit]), [[1.5, 'cup'], [2, 'tsp']]);
  assert.deepEqual(recipeRemoveRow(c, 0).map((r) => r.food_id), [5]);
  assert.equal(c.length, 2);
});

test('recipeBody validates and builds the request', () => {
  const d = newRecipeDraft(2);
  assert.match(recipeBody(d).error, /name/);
  d.name = '  Pilaf ';
  assert.match(recipeBody(d).error, /ingredient/);
  d.rows = recipeAddRow([], rice, 2, 'serving');
  d.meals = ['snack', 'lunch'];
  assert.deepEqual(recipeBody(d).body, { name: 'Pilaf', meals: ['lunch', 'snack'], items: [{ food_id: 4, amount: 2, unit: 'serving' }], steps: [] });
  d.steps = [' Rinse  the rice. ', '', 'Simmer.'];
  assert.deepEqual(recipeBody(d).body.steps, ['Rinse the rice.', 'Simmer.']);
  d.steps = ['x'.repeat(1001)];
  assert.match(recipeBody(d).error, /Step 1 is too long/);
});

test('stepsBack is at least one', () => {
  assert.equal(stepsBack(5, 2), 3);
  assert.equal(stepsBack(2, 2), 1);
  assert.equal(stepsBack(1, 3), 1);
});

test('matchesQuery needs every word, ignoring case', () => {
  assert.ok(matchesQuery('Peanut Butter (Acme)', 'butter pea'));
  assert.ok(matchesQuery('Rice', '  '));
  assert.ok(matchesQuery('Rice', ''));
  assert.ok(!matchesQuery('Rice', 'rice beans'));
  assert.ok(!matchesQuery(null, 'x'));
});

test('filterSavedItems by query and meal tag', () => {
  const items = [{ n: 'Eggs', meals: ['breakfast'] }, { n: 'Egg Salad', meals: [] }, { n: 'Pasta', meals: ['dinner', 'lunch'] }, { n: 'Soup' }];
  const f = (q, m) => filterSavedItems(items, q, m, (i) => i.n).map((i) => i.n);
  assert.deepEqual(f('', 'all'), ['Eggs', 'Egg Salad', 'Pasta', 'Soup']);
  assert.deepEqual(f('egg', 'all'), ['Eggs', 'Egg Salad']);
  assert.deepEqual(f('', 'lunch'), ['Pasta']);
  assert.deepEqual(f('', 'untagged'), ['Egg Salad', 'Soup']);
  assert.deepEqual(f('egg', 'breakfast'), ['Eggs']);
  assert.deepEqual(f('zzz', 'all'), []);
  assert.deepEqual(filterSavedItems(null, '', 'all', (i) => i), []);
});

test('saved filter options and the past foods empty text', () => {
  assert.deepEqual(SAVED_FILTERS, ['all', 'breakfast', 'lunch', 'dinner', 'snack', 'dessert', 'untagged']);
  assert.deepEqual(SAVED_FILTERS.map((m) => SAVED_FILTER_LABELS[m]), ['All', 'Breakfast', 'Lunch', 'Dinner', 'Snack', 'Dessert', 'Untagged']);
  assert.match(emptyText('recent', 'all', false), /past foods/);
});

test('twenty per section then more', () => {
  const list = Array.from({ length: 45 }, (_, i) => i);
  assert.equal(pageOf(list, PAGE_SIZE).items.length, 20);
  assert.equal(pageOf(list, PAGE_SIZE).more, 25);
  assert.equal(pageOf(list, PAGE_SIZE * 3).more, 0);
});
