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

test('sortRecipes by recent, name and most used', async () => {
  const { sortRecipes, recipeUses, RECIPE_SORTS, RECIPE_SORT_LABELS } = await import('../../app/static/js/util.js');
  const r = [{ id: 1, name: 'banana bread', counts: { lunch: 2, dinner: 1 } }, { id: 3, name: 'Apple Pie' }, { id: 2, name: 'Chili', counts: { dinner: 3 } }, { id: 4, name: 'apple pie' }];
  const ids = (s) => sortRecipes(r, s).map((x) => x.id);
  assert.deepEqual(ids('name'), [3, 4, 1, 2]);
  assert.deepEqual(ids('recent'), [4, 3, 2, 1]);  // no dates: the highest id first
  assert.deepEqual(ids('newest'), [3, 4, 1, 2]);  // the old name is gone, so it falls back to name
  assert.deepEqual(ids('used'), [1, 2, 3, 4]);
  assert.deepEqual(ids('bogus'), [3, 4, 1, 2]);
  assert.equal(recipeUses(r[0]), 3);
  assert.equal(recipeUses({}), 0);
  assert.deepEqual(sortRecipes(null, 'name'), []);
  assert.deepEqual(r.map((x) => x.id), [1, 3, 2, 4]);
  assert.deepEqual(RECIPE_SORTS.map((s) => RECIPE_SORT_LABELS[s]), ['Recent', 'Name (A to Z)', 'Most Used']);
});

test('recent sort uses last edited, falls back to created, then the highest id', async () => {
  const { sortRecipes, recipeStamp } = await import('../../app/static/js/util.js');
  const r = [
    { id: 1, name: 'A', created_at: '2026-01-01 10:00:00', updated_at: '2026-03-01 09:00:00.500' },
    { id: 2, name: 'B', created_at: '2026-02-01 10:00:00', updated_at: null },
    { id: 3, name: 'C', created_at: '2026-03-01 09:00:00', updated_at: null },
    { id: 4, name: 'D', created_at: '2026-03-01 09:00:00', updated_at: null },
    { id: 5, name: 'E' },
  ];
  assert.deepEqual(sortRecipes(r, 'recent').map((x) => x.id), [1, 4, 3, 2, 5]);
  assert.equal(recipeStamp(r[1]), '2026-02-01 10:00:00');
  assert.equal(recipeStamp(r[0]), '2026-03-01 09:00:00.500');
  assert.equal(recipeStamp(null), '');
  assert.equal(sortRecipes(r, 'recent')[0].id, 1);
});

test('the Recipes list code has no grouping or group_recipes left', async () => {
  const fs = await import('node:fs');
  const util = await import('../../app/static/js/util.js');
  assert.equal(util.groupRecipesByMeal, undefined);
  assert.equal(util.pageGroups, undefined);
  assert.equal('group_recipes' in util.DEFAULT_DISPLAY, false);
  for (const f of ['recipes.js', 'app.js', 'micros.js']) assert.ok(!/group_recipes|groupRecipesByMeal/.test(fs.readFileSync(new URL('../../app/static/js/' + f, import.meta.url), 'utf8')), f);
});
