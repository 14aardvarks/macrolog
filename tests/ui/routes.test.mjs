import test from 'node:test';
import assert from 'node:assert/strict';
import { ROUTES, parseRoute, formatRoute, routeUrl, startRoute, tabOf } from '../../app/static/js/routes.js';

test('parseRoute reads every route in the table', () => {
  assert.deepEqual(parseRoute('#/today'), { name: 'today', params: {} });
  assert.deepEqual(parseRoute('#/today/log/7'), { name: 'recipelog', params: { groupId: 7 } });
  assert.deepEqual(parseRoute('#/add'), { name: 'add', params: {} });
  assert.deepEqual(parseRoute('#/add/food/12?meal=lunch'), { name: 'picker', params: { foodId: 12, meal: 'lunch' } });
  assert.deepEqual(parseRoute('#/add/recipe/3'), { name: 'meal', params: { mealId: 3 } });
  assert.deepEqual(parseRoute('#/recipes'), { name: 'recipes', params: {} });
  assert.deepEqual(parseRoute('#/recipes/5'), { name: 'recipeview', params: { mealId: 5 } });
  assert.deepEqual(parseRoute('#/recipes/5/cooking'), { name: 'cooking', params: { mealId: 5 } });
  assert.deepEqual(parseRoute('#/settings'), { name: 'settings', params: {} });
  assert.deepEqual(parseRoute('#/saved'), { name: 'saved', params: {} });
  assert.deepEqual(parseRoute('#/admin'), { name: 'admin', params: {} });
});

test('parseRoute takes the SSO link hash, a trailing slash and no leading #', () => {
  assert.deepEqual(parseRoute('#settings'), { name: 'settings', params: {} });
  assert.deepEqual(parseRoute('#/recipes/'), { name: 'recipes', params: {} });
  assert.deepEqual(parseRoute('/saved'), { name: 'saved', params: {} });
});

test('parseRoute rejects unknown routes and bad ids', () => {
  for (const h of ['', '#', '#/', '#/nope', '#/recipes/abc', '#/recipes/0', '#/recipes/-1', '#/recipes/1.5', '#/recipes/5/edit',
    '#/today/log', '#/add/food/', '#/import', '#/match/4', '#today', '#/admin/x', '#/recipes/99999999999999999']) {
    assert.equal(parseRoute(h), null, h);
  }
});

test('parseRoute drops unknown or bad query values', () => {
  assert.deepEqual(parseRoute('#/add/food/12?meal=brunch'), { name: 'picker', params: { foodId: 12 } });
  assert.deepEqual(parseRoute('#/add/food/12?x=1&meal=dessert'), { name: 'picker', params: { foodId: 12, meal: 'dessert' } });
  assert.deepEqual(parseRoute('#/recipes/5?meal=lunch'), { name: 'recipeview', params: { mealId: 5 } });
});

test('formatRoute builds the hash and round trips through parseRoute', () => {
  const cases = [['today', {}], ['recipelog', { groupId: 7 }], ['add', {}], ['picker', { foodId: 12, meal: 'lunch' }], ['picker', { foodId: 12 }],
    ['meal', { mealId: 3, meal: 'snack' }], ['recipes', {}], ['recipeview', { mealId: 5 }], ['cooking', { mealId: 5 }],
    ['settings', {}], ['saved', {}], ['admin', {}]];
  for (const [name, params] of cases) {
    const hash = formatRoute(name, params);
    assert.deepEqual(parseRoute(hash), { name, params }, hash);
  }
  assert.equal(formatRoute('cooking', { mealId: 5 }), '#/recipes/5/cooking');
  assert.equal(formatRoute('picker', { foodId: 12, meal: 'lunch', amount: 2, unit: 'g' }), '#/add/food/12?meal=lunch');
  assert.equal(formatRoute('picker', { foodId: 12, meal: null }), '#/add/food/12');
  assert.equal(formatRoute('add', { focus: true }), '#/add');
});

test('formatRoute gives no URL to in progress screens and mid flow params', () => {
  for (const name of ['login', 'import', 'importreview', 'match', 'recipe', 'scan', 'ai', 'manual', 'lookup', 'editfood', 'nope']) {
    assert.equal(formatRoute(name, { mealId: 5 }), null, name);
  }
  assert.equal(formatRoute('picker', { foodId: 1, entryId: 9 }), null);
  assert.equal(formatRoute('picker', { foodId: 1, adjust: { index: 0 } }), null);
  assert.equal(formatRoute('recipelog', { groupId: 2, copy: true }), null);
  assert.equal(formatRoute('add', { ingredient: true }), null);
  assert.equal(formatRoute('recipeview', {}), null);
  assert.equal(formatRoute('recipeview', { mealId: 'x' }), null);
});

test('routeUrl keeps the parent URL for screens without one and inside a recipe flow', () => {
  assert.equal(routeUrl('recipes', {}, '#/today'), '#/recipes');
  assert.equal(routeUrl('match', { mealId: 5 }, '#/recipes/5'), '#/recipes/5');
  assert.equal(routeUrl('import', {}, '#/recipes'), '#/recipes');
  assert.equal(routeUrl('picker', { foodId: 3 }, '#/recipes', true), '#/recipes');
  assert.equal(routeUrl('scan', {}, ''), '');
});

test('startRoute: no hash uses the start screen, an unknown one opens Today', () => {
  assert.equal(startRoute(''), null);
  assert.equal(startRoute('#'), null);
  assert.deepEqual(startRoute('#/whatever'), { name: 'today', params: {} });
  assert.deepEqual(startRoute('#/saved'), { name: 'saved', params: {} });
});

test('tabOf follows the route table, flows and Add', () => {
  for (const r of ROUTES) assert.equal(tabOf(r.name), r.tab);
  assert.equal(tabOf('saved'), 'settings');
  assert.equal(tabOf('admin'), 'settings');
  assert.equal(tabOf('editfood'), 'settings');
  assert.equal(tabOf('match'), 'recipes');
  assert.equal(tabOf('import'), 'recipes');
  assert.equal(tabOf('scan'), 'add');
  assert.equal(tabOf('lookup'), 'add');
});
