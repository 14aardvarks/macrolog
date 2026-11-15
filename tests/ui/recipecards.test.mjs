import test from 'node:test';
import assert from 'node:assert/strict';
import { recipeSummary, ingredientCount, cardChips, cardLabel, placeholderTone, cardGridClass, cardMenuItems, menuLabel, menuMove }
  from '../../app/static/js/recipecards.js';

const base = { id: 1, name: 'Pancakes', servings: 4, per_serving: { kcal: 520.4, protein: 31.6, carbs: 60, fat: 18 },
  items: [{}, {}, {}], needed: 3, matched: 3, skipped: 0, complete: true, meals: ['dinner', 'breakfast'], mine: true, shared: false, can_edit: true };

test('summary line has servings, per serving kcal and protein and the ingredient count', () => {
  assert.equal(recipeSummary(base), '4 servings · 520 kcal · 32 g protein · 3 ingredients');
  assert.equal(recipeSummary({ ...base, servings: 1, items: [{}] }), '1 serving · 520 kcal · 32 g protein · 1 ingredient');
});

test('summary leaves out unknown per serving numbers and treats no servings as one', () => {
  assert.equal(recipeSummary({ items: [], per_serving: { kcal: null } }), '1 serving · 0 ingredients');
  assert.equal(recipeSummary(null), '1 serving · 0 ingredients');
  assert.equal(recipeSummary({ ...base, per_serving: { kcal: 100 } }), '4 servings · 100 kcal · 3 ingredients');
});

test('ingredient count falls back to needed plus skipped', () => {
  assert.equal(ingredientCount({ needed: 5, skipped: 2 }), 7);
  assert.equal(ingredientCount({}), 0);
});

test('chips: meal tags in meal order, then owner, then partial', () => {
  assert.deepEqual(cardChips(base), [{ kind: 'breakfast', label: 'Breakfast' }, { kind: 'dinner', label: 'Dinner' }]);
  const theirs = { ...base, meals: [], mine: false, shared: true, owner: { name: 'Ann' }, complete: false, matched: 2, needed: 3 };
  assert.deepEqual(cardChips(theirs), [{ kind: 'owner', label: 'Shared by Ann' }, { kind: 'partial', label: '2 of 3 matched' }]);
  assert.deepEqual(cardChips({ ...base, meals: [], shared: true }), [{ kind: 'owner', label: 'Shared' }]);
  assert.deepEqual(cardChips({ meals: ['brunch'] }), []);
});

test('card label names the title, summary and chips', () => {
  assert.equal(cardLabel(base), 'Pancakes, 4 servings · 520 kcal · 32 g protein · 3 ingredients, Breakfast, Dinner');
});

test('placeholder tone is the first meal in meal order, else the accent', () => {
  assert.equal(placeholderTone(base), 'breakfast');
  assert.equal(placeholderTone({ meals: ['dessert', 'snack'] }), 'snack');
  assert.equal(placeholderTone({ meals: [] }), 'accent');
  assert.equal(placeholderTone(null), 'accent');
});

test('grid class is compact when photos are off', () => {
  assert.equal(cardGridClass(true), 'card-grid');
  assert.equal(cardGridClass(false), 'card-grid compact');
});

test('menu items follow edit rights and the photo switch', () => {
  const keys = (m, on) => cardMenuItems(m, on).map((i) => i.key);
  assert.deepEqual(keys(base, true), ['log', 'cooking', 'photo', 'duplicate', 'delete']);
  assert.deepEqual(keys(base, false), ['log', 'cooking', 'duplicate', 'delete']);
  assert.deepEqual(keys({ ...base, can_edit: false }, true), ['log', 'cooking', 'duplicate']);
  assert.equal(cardMenuItems({ ...base, photo: 'abcdefghijklmnop.jpg' }, true)[2].label, 'Replace Photo');
  assert.equal(cardMenuItems(base, true)[2].label, 'Add Photo');
  assert.equal(menuLabel(base), 'More Actions for Pancakes');
});

test('menu keys wrap and ignore other keys', () => {
  assert.equal(menuMove('ArrowDown', 4, 5), 0);
  assert.equal(menuMove('ArrowUp', 0, 5), 4);
  assert.equal(menuMove('Home', 3, 5), 0);
  assert.equal(menuMove('End', 0, 5), 4);
  assert.equal(menuMove('a', 0, 5), null);
  assert.equal(menuMove('ArrowDown', 0, 0), null);
});

test('summary parts keep each figure whole for no wrap spans', async () => {
  const { summaryParts } = await import('../../app/static/js/recipecards.js');
  assert.deepEqual(summaryParts(base), ['4 servings', '520 kcal', '32 g protein', '3 ingredients']);
});
