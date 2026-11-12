import test from 'node:test';
import assert from 'node:assert/strict';
import { RECIPE_OWNERS, RECIPE_OWNER_LABELS, recipeOwner, filterRecipeOwner, ownerText, ownerEmptyText, DEFAULT_DISPLAY, filterSavedItems } from '../../app/static/js/util.js';
import { GUIDE } from '../../app/static/js/guide.js';

const list = [
  { id: 1, name: 'Toast', mine: true, shared: false, owner: { id: 1, name: 'Ann' }, meals: ['breakfast'] },
  { id: 2, name: 'Soup', mine: true, shared: true, owner: { id: 1, name: 'Ann' }, meals: [] },
  { id: 3, name: 'Chili', mine: false, shared: true, owner: { id: 2, name: 'Bob' }, meals: ['dinner'] },
  { id: 4, name: 'Old', meals: [] },  // a recipe from an older server reads as mine
];

test('owner filter choices, labels and default', () => {
  assert.deepEqual(RECIPE_OWNERS, ['mine', 'shared', 'all']);
  assert.deepEqual(RECIPE_OWNERS.map((o) => RECIPE_OWNER_LABELS[o]), ['Mine', 'Shared With Me', 'All']);
  assert.equal(DEFAULT_DISPLAY.recipe_owner, 'mine');
  assert.equal(recipeOwner('shared'), 'shared');
  for (const bad of [undefined, null, '', 'everyone', 3]) assert.equal(recipeOwner(bad), 'mine');
});

test('filterRecipeOwner keeps mine, shared with me, or all', () => {
  assert.deepEqual(filterRecipeOwner(list, 'mine').map((r) => r.id), [1, 2, 4]);
  assert.deepEqual(filterRecipeOwner(list, 'shared').map((r) => r.id), [3]);
  assert.deepEqual(filterRecipeOwner(list, 'all').map((r) => r.id), [1, 2, 3, 4]);
  assert.deepEqual(filterRecipeOwner(list, 'nonsense').map((r) => r.id), [1, 2, 4]);
  assert.deepEqual(filterRecipeOwner(null, 'all'), []);
  assert.notEqual(filterRecipeOwner(list, 'all'), list);
});

test('owner filter combines with the meal filter and search', () => {
  const shared = filterRecipeOwner(list, 'shared');
  assert.deepEqual(filterSavedItems(shared, 'chi', 'dinner', (r) => r.name).map((r) => r.id), [3]);
  assert.deepEqual(filterSavedItems(shared, '', 'breakfast', (r) => r.name), []);
});

test('ownerText names the owner of someone else\'s recipe and marks my shared ones', () => {
  assert.equal(ownerText(list[0]), '');
  assert.equal(ownerText(list[1]), 'Shared');
  assert.equal(ownerText(list[2]), 'Shared by Bob');
  assert.equal(ownerText(list[3]), '');
  assert.equal(ownerText({ mine: false, owner: { name: '  ' } }), 'Shared by another user');
  assert.equal(ownerText({ mine: false }), 'Shared by another user');
  assert.equal(ownerText(null), '');
});

test('empty texts are sentences with no em dash', () => {
  assert.equal(ownerEmptyText('shared'), 'No one has shared a recipe with you yet.');
  assert.match(ownerEmptyText('mine'), /^No recipes yet\. .*Today\.$/);
  assert.equal(ownerEmptyText('all'), ownerEmptyText('mine'));
  for (const o of RECIPE_OWNERS) assert.ok(!ownerEmptyText(o).includes('\u2014'));
});

test('guide explains shared recipes and the private default', () => {
  const g = GUIDE.find((x) => x.heading === 'Shared Recipes');
  assert.ok(g);
  assert.ok(g.bullets.some((b) => /private by default/.test(b)));
  assert.ok(g.bullets.some((b) => /Mine, Shared With Me or All/.test(b)));
});
