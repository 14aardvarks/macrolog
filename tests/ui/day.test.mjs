import test from 'node:test';
import assert from 'node:assert/strict';
import { groupByMeal, guessMeal, localDate, addDays, dayLabel } from '../../app/static/js/util.js';

test('groupByMeal orders meals and drops empty groups', () => {
  const entries = [
    { id: 1, meal: 'dinner', kcal: 500 },
    { id: 2, meal: 'breakfast', kcal: 300.25 },
    { id: 3, meal: null, kcal: 50 },
    { id: 4, meal: 'breakfast', kcal: 100 },
  ];
  const g = groupByMeal(entries);
  assert.deepEqual(g.map((x) => x.meal), ['breakfast', 'dinner', null]);
  assert.deepEqual(g.map((x) => x.entries.map((e) => e.id)), [[2, 4], [1], [3]]);
  assert.equal(g[0].kcal, 400.3);
  assert.equal(g[0].label, 'Breakfast');
  assert.equal(g[2].label, 'No meal');
});

test('groupByMeal handles empty and unknown meals', () => {
  assert.deepEqual(groupByMeal([]), []);
  assert.deepEqual(groupByMeal(undefined), []);
  const g = groupByMeal([{ id: 1, meal: 'brunch', kcal: 10 }]);
  assert.equal(g.length, 1);
  assert.equal(g[0].meal, null);
});

test('guessMeal by hour', () => {
  assert.equal(guessMeal(7), 'breakfast');
  assert.equal(guessMeal(12), 'lunch');
  assert.equal(guessMeal(15), 'snack');
  assert.equal(guessMeal(19), 'dinner');
});

test('localDate uses local calendar fields', () => {
  assert.equal(localDate(new Date(2025, 0, 5, 23, 59)), '2025-01-05');
  assert.equal(localDate(new Date(2025, 11, 31, 0, 0)), '2025-12-31');
});

test('addDays crosses month and year', () => {
  assert.equal(addDays('2025-03-01', -1), '2025-02-28');
  assert.equal(addDays('2024-03-01', -1), '2024-02-29');
  assert.equal(addDays('2025-12-31', 1), '2026-01-01');
});

test('dayLabel', () => {
  assert.equal(dayLabel('2025-05-10', '2025-05-10'), 'Today');
  assert.equal(dayLabel('2025-05-09', '2025-05-10'), 'Yesterday');
  assert.ok(dayLabel('2025-05-01', '2025-05-10').length > 3);
});

import { checkedItems, canSaveRecipe } from '../../app/static/js/util.js';

test('checkedItems keeps only ticked rows and validates amounts', () => {
  const rows = [
    { checked: true, amount: '2', food_id: 1, unit: 'g', name: 'A' },
    { checked: false, amount: 'junk', food_id: 2, unit: 'g', name: 'B' },
    { checked: true, amount: '1/2', food_id: 3, unit: 'cup', name: 'C' },
  ];
  assert.deepEqual(checkedItems(rows).items, [{ food_id: 1, amount: 2, unit: 'g' }, { food_id: 3, amount: 0.5, unit: 'cup' }]);
  assert.match(checkedItems([{ ...rows[0], amount: '0' }]).error, /amount for A/);
  assert.match(checkedItems(rows.map((r) => ({ ...r, checked: false }))).error, /at least one/);
});

test('canSaveRecipe needs a ticked row and a name', () => {
  assert.equal(canSaveRecipe(1, 'Breakfast'), true);
  assert.equal(canSaveRecipe(0, 'Breakfast'), false);
  assert.equal(canSaveRecipe(2, '   '), false);
});

import { mealGroupsAll, quickLabel, MEALS } from '../../app/static/js/util.js';

test('mealGroupsAll lists every meal, empty ones too, and no meal only with entries', () => {
  const g = mealGroupsAll([{ meal: 'lunch', kcal: 100 }]);
  assert.deepEqual(g.map((x) => x.meal), MEALS);
  assert.equal(g.find((x) => x.meal === 'lunch').entries.length, 1);
  assert.equal(g.find((x) => x.meal === 'dinner').entries.length, 0);
  assert.deepEqual(mealGroupsAll([]).map((x) => x.meal), MEALS);
  assert.equal(mealGroupsAll([{ meal: null, kcal: 5 }]).at(-1).label, 'No meal');
});

test('quickLabel names the action and the meal', () => {
  assert.equal(quickLabel('add', 'lunch'), 'Add to Lunch');
  assert.equal(quickLabel('scan', 'snack'), 'Scan for Snack');
  assert.equal(quickLabel('search', 'dessert'), 'Search for Dessert');
});
