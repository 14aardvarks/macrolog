import test from 'node:test';
import assert from 'node:assert/strict';
import {
  stepDecimals, snapToStep, valueList, wheelMax, nearestIndex, indexFromScroll, clamp, MAX_WHEEL_ITEMS,
} from '../../app/static/js/util.js';

test('stepDecimals', () => {
  assert.equal(stepDecimals(5), 0);
  assert.equal(stepDecimals(0.5), 1);
  assert.equal(stepDecimals(0.25), 2);
  assert.equal(stepDecimals(0.125), 3);
  assert.equal(stepDecimals(0.05), 2);
});

test('snapToStep', () => {
  assert.equal(snapToStep(12, 5), 10);
  assert.equal(snapToStep(13, 5), 15);
  assert.equal(snapToStep(0.3, 0.25), 0.25);
  assert.equal(snapToStep(0.1, 0.5), 0.5);   // never below one step
  assert.equal(snapToStep(0.37, 0.125), 0.375);
  assert.equal(snapToStep(0.3, 0.05), 0.3);  // no float noise
});

test('valueList is clean and ascending', () => {
  assert.deepEqual(valueList(0.5, 2), [0.5, 1, 1.5, 2]);
  assert.deepEqual(valueList(5, 20), [5, 10, 15, 20]);
  assert.deepEqual(valueList(0.125, 0.5), [0.125, 0.25, 0.375, 0.5]);
  const l = valueList(0.05, 1);
  assert.equal(l.length, 20);
  assert.equal(l[5], 0.3);
  assert.equal(l[19], 1);
});

test('valueList is capped', () => {
  assert.equal(valueList(1, 100000).length, MAX_WHEEL_ITEMS);
  assert.equal(valueList(5, 1).length, 1);
});

test('wheelMax covers the value', () => {
  assert.equal(wheelMax(5, 30), 1000);
  assert.equal(wheelMax(0.5, 100), 400 * 0.5);
  assert.ok(wheelMax(0.5, 100) >= 100);
  assert.equal(wheelMax(1, 1e9), MAX_WHEEL_ITEMS);
});

test('nearestIndex', () => {
  const l = valueList(0.5, 5);
  assert.equal(nearestIndex(l, 0.5), 0);
  assert.equal(nearestIndex(l, 2.2), 3);
  assert.equal(nearestIndex(l, 99), l.length - 1);
  assert.equal(nearestIndex(l, 0), 0);
});

test('indexFromScroll clamps and rounds', () => {
  assert.equal(indexFromScroll(0, 44, 10), 0);
  assert.equal(indexFromScroll(60, 44, 10), 1);
  assert.equal(indexFromScroll(66, 44, 10), 2);
  assert.equal(indexFromScroll(-20, 44, 10), 0);
  assert.equal(indexFromScroll(9999, 44, 10), 9);
});

test('clamp', () => {
  assert.equal(clamp(5, 0, 3), 3);
  assert.equal(clamp(-1, 0, 3), 0);
  assert.equal(clamp(2, 0, 3), 2);
});

import { amountLabel, amountValues, withValue, SERVING_MAX, PCT_MAX } from '../../app/static/js/util.js';

test('amountLabel shows servings as fractions', () => {
  assert.equal(amountLabel('serving', 0.25), '1/4');
  assert.equal(amountLabel('serving', 0.5), '1/2');
  assert.equal(amountLabel('serving', 1), '1');
  assert.equal(amountLabel('serving', 1.25), '1 1/4');
  assert.equal(amountLabel('serving', 1.5), '1 1/2');
  assert.equal(amountLabel('serving', 0.4), '0.4');
  assert.equal(amountLabel('g', 0.5), '0.5');
  assert.equal(amountLabel('cup', 0.125), '0.125');
  assert.equal(amountLabel('pct', 50), '50');
});

test('amountValues per unit', () => {
  const sv = amountValues('serving', 0.25, 1);
  assert.deepEqual(sv.slice(0, 6), [0.25, 0.5, 0.75, 1, 1.25, 1.5]);
  assert.equal(sv[sv.length - 1], SERVING_MAX);
  assert.equal(sv.length, SERVING_MAX * 4);
  const pc = amountValues('pct', 5, 100);
  assert.deepEqual(pc.slice(0, 3), [5, 10, 15]);
  assert.equal(pc[pc.length - 1], PCT_MAX);
  const g = amountValues('g', 5, 240);
  assert.equal(g[0], 5);
  assert.ok(g[g.length - 1] >= 480);
  assert.ok(g.length <= MAX_WHEEL_ITEMS);
  const cup = amountValues('cup', 0.125, 1);
  assert.deepEqual(cup.slice(0, 3), [0.125, 0.25, 0.375]);
  assert.equal(amountValues('slice', 0.5, 2)[1], 1);
});

test('withValue keeps an off-grid value as a row', () => {
  const l = [0.25, 0.5, 0.75, 1];
  assert.deepEqual(withValue(l, 0.5), { values: l, index: 1 });
  assert.deepEqual(withValue(l, 0.6), { values: [0.25, 0.5, 0.6, 0.75, 1], index: 2 });
  assert.deepEqual(withValue(l, 0.1), { values: [0.1, 0.25, 0.5, 0.75, 1], index: 0 });
  assert.deepEqual(withValue(l, 7), { values: [0.25, 0.5, 0.75, 1, 7], index: 4 });
  assert.deepEqual(l, [0.25, 0.5, 0.75, 1]);
});
