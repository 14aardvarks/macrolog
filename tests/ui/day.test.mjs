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
