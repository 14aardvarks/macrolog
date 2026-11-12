import test from 'node:test';
import assert from 'node:assert/strict';
import { groupRecipesByMeal, pageGroups, sortRecipes, DEFAULT_DISPLAY } from '../../app/static/js/util.js';

const recs = [
  { id: 1, name: 'Oats', meals: ['breakfast'] }, { id: 2, name: 'Soup', meals: ['lunch', 'dinner'] },
  { id: 3, name: 'Cake', meals: ['dessert', 'snack'] }, { id: 4, name: 'Mystery', meals: [] }, { id: 5, name: 'Bare' },
];
const ids = (g) => g.map((x) => [x.label, x.items.map((i) => i.id)]);

test('groups follow meal order, untagged last, multi tag under each', () => {
  assert.deepEqual(ids(groupRecipesByMeal(recs)), [['Breakfast', [1]], ['Lunch', [2]], ['Dinner', [2]], ['Snack', [3]], ['Dessert', [3]], ['Untagged', [4, 5]]]);
});

test('empty groups are hidden and empty input is fine', () => {
  assert.deepEqual(groupRecipesByMeal([recs[0]]).map((g) => g.label), ['Breakfast']);
  assert.deepEqual(groupRecipesByMeal([]), []);
  assert.deepEqual(groupRecipesByMeal(null), []);
});

test('meal filter limits the groups', () => {
  assert.deepEqual(ids(groupRecipesByMeal([recs[1]], 'dinner')), [['Dinner', [2]]]);
  assert.deepEqual(ids(groupRecipesByMeal(recs, 'untagged')), [['Untagged', [4, 5]]]);
});

test('sort order is kept within each group', () => {
  const sorted = sortRecipes([{ id: 1, name: 'B', meals: ['lunch'] }, { id: 2, name: 'A', meals: ['lunch'] }, { id: 3, name: 'C', meals: ['lunch'] }], 'newest');
  assert.deepEqual(groupRecipesByMeal(sorted)[0].items.map((i) => i.id), [3, 2, 1]);
});

test('pageGroups limits rows across groups', () => {
  const g = groupRecipesByMeal(recs);
  const p = pageGroups(g, 3);
  assert.deepEqual(ids(p.groups), [['Breakfast', [1]], ['Lunch', [2]], ['Dinner', [2]]]);
  assert.equal(p.more, 4);
  assert.equal(pageGroups(g, 20).more, 0);
});

test('grouping is on by default', () => assert.equal(DEFAULT_DISPLAY.group_recipes, true));
