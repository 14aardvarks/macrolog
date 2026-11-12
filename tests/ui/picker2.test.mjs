import test from 'node:test';
import assert from 'node:assert/strict';
import {
  initialPick, convertAmount, gramsFor, macroShares, percentParts, polar, arcPath, donutSegments,
  latestGuard, groupByMeal,
} from '../../app/static/js/util.js';

const units = [
  { unit: 'cup', step: 0.125, default_amount: 1 },
  { unit: 'g', step: 5, default_amount: 240 },
  { unit: 'oz', step: 0.25, default_amount: 8.47 },
  { unit: 'tbsp', step: 0.5, default_amount: 16 },
];

test('initialPick uses the preset when usable, else the label unit', () => {
  assert.deepEqual(initialPick(units, { amount: 120, unit: 'g' }), { unit: 'g', amount: 120 });
  assert.deepEqual(initialPick(units, null), { unit: 'cup', amount: 1 });
  assert.deepEqual(initialPick(units, { amount: 5, unit: 'bogus' }), { unit: 'cup', amount: 1 });
  assert.deepEqual(initialPick(units, { amount: 0, unit: 'g' }), { unit: 'g', amount: 240 });
});

test('initialPick starts on the package serving, never 1 serving by default', () => {
  const ths = [{ unit: 'serving', step: 0.25, default_amount: 1 }, { unit: 'pct', step: 5, default_amount: 100 }, { unit: 'g', step: 5, default_amount: 30 }];
  assert.deepEqual(initialPick(ths, null, { amount: 30, unit: 'g' }), { unit: 'g', amount: 30 });
  assert.deepEqual(initialPick(ths, undefined, { amount: 30, unit: 'bogus' }), { unit: 'serving', amount: 1 });
  assert.deepEqual(initialPick(units, null, { amount: 1, unit: 'cup' }), { unit: 'cup', amount: 1 });
  assert.deepEqual(initialPick(ths, { amount: 2, unit: 'serving' }, { amount: 30, unit: 'g' }), { unit: 'serving', amount: 2 });  // last amount wins
  assert.deepEqual(initialPick(ths, { amount: 0, unit: 'serving' }, { amount: 30, unit: 'g' }), { unit: 'g', amount: 30 });
});

test('convertAmount keeps the quantity', () => {
  assert.equal(convertAmount(units, 0.5, 'cup', 'g'), 120);
  assert.equal(convertAmount(units, 120, 'g', 'tbsp'), 8);
  assert.equal(convertAmount(units, 2, 'cup', 'cup'), 2);
});

test('convertAmount falls back to the default amount', () => {
  assert.equal(convertAmount(units, 0, 'cup', 'g'), 240);
  assert.equal(convertAmount(units, 3, 'nope', 'g'), 240);
  assert.equal(convertAmount(units, 3, 'cup', 'nope'), null);
});

test('gramsFor', () => {
  assert.equal(gramsFor(units, 0.25, 'cup'), 60);
  assert.equal(gramsFor(units, 100, 'g'), null);
  assert.equal(gramsFor([{ unit: 'cup', default_amount: 1 }], 1, 'cup'), null);
});


test('macroShares uses 4/4/9 kcal per gram', () => {
  const s = macroShares({ carbs: 50, protein: 25, fat: 10 });
  assert.ok(Math.abs(s.carbs - 200 / 390) < 1e-9);
  assert.ok(Math.abs(s.protein - 100 / 390) < 1e-9);
  assert.ok(Math.abs(s.fat - 90 / 390) < 1e-9);
  assert.equal(macroShares({ carbs: 0, protein: 0, fat: 0 }), null);
  assert.equal(macroShares(null), null);
});

test('percentParts always adds to 100', () => {
  const p = percentParts({ carbs: 1 / 3, protein: 1 / 3, fat: 1 / 3 });
  assert.equal(p.carbs + p.protein + p.fat, 100);
  assert.deepEqual(percentParts({ carbs: 0.5, protein: 0.3, fat: 0.2 }), { carbs: 50, protein: 30, fat: 20 });
  assert.deepEqual(percentParts(null), { carbs: 0, protein: 0, fat: 0 });
});

test('polar and arcPath geometry', () => {
  assert.deepEqual(polar(0, 0, 10, 0), { x: 10, y: 0 });
  assert.deepEqual(polar(0, 0, 10, Math.PI / 2), { x: 0, y: 10 });
  const d = arcPath(0, 0, 10, 5, 0, Math.PI / 2);
  assert.equal(d, 'M10 0A10 10 0 0 1 0 10L0 5A5 5 0 0 0 5 0Z');
  assert.match(arcPath(0, 0, 10, 5, 0, 1.5 * Math.PI), /A10 10 0 1 1/);
  assert.ok(!/NaN/.test(arcPath(0, 0, 10, 5, 0, 2 * Math.PI)));  // a full ring still draws
});

test('donutSegments start at the top and cover the circle', () => {
  const segs = donutSegments({ carbs: 0.5, protein: 0.25, fat: 0.25 });
  assert.equal(segs.length, 3);
  assert.equal(segs[0].start, -Math.PI / 2);
  assert.ok(Math.abs(segs[2].end - (1.5 * Math.PI)) < 1e-9);
  assert.equal(donutSegments({ carbs: 1, protein: 0, fat: 0 }).length, 1);
  assert.deepEqual(donutSegments(null), []);
});

test('latestGuard only trusts the newest ticket', () => {
  const g = latestGuard();
  const a = g.next();
  const b = g.next();
  assert.equal(g.isLatest(a), false);
  assert.equal(g.isLatest(b), true);
});

test('groupByMeal can name the leftover group', () => {
  const g = groupByMeal([{ meal: null, kcal: 5 }, { meal: 'lunch', kcal: 7 }], 'Other');
  assert.deepEqual(g.map((x) => x.label), ['Lunch', 'Other']);
});

import { rowAmountText, applyRowPick, draftFits } from '../../app/static/js/util.js';

test('applyRowPick sets one row, ticks it and keeps the others', () => {
  const draft = [{ checked: false, amount: '2', unit: 'slice' }, { checked: true, amount: '1', unit: 'tbsp' }];
  const out = applyRowPick(draft, 0, 34, 'g');
  assert.deepEqual(out[0], { checked: true, amount: '34', exact: 34, shown: '34', unit: 'g' });
  assert.deepEqual(out[1], draft[1]);
  assert.notEqual(out[1], draft[1]);
  assert.equal(draft[0].checked, false);
});

test('rowAmountText formats servings and plain amounts', () => {
  assert.equal(rowAmountText(1.5, 'g'), '1.5');
  assert.equal(rowAmountText(120, 'g'), '120');
  assert.equal(typeof rowAmountText(0.5, 'serving'), 'string');
});

test('draftFits needs the same recipe, depth and row count', () => {
  const d = { mealId: 3, depth: 2, rows: [{}, {}] };
  assert.equal(draftFits(d, 3, 2, 2), true);
  assert.equal(draftFits(d, 4, 2, 2), false);
  assert.equal(draftFits(d, 3, 1, 2), false);
  assert.equal(draftFits(d, 3, 2, 3), false);
  assert.equal(draftFits(null, 3, 2, 2), false);
});
