import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  qtyText, fractionUnit, canonUnit, amountText, amountLabel, rowAmountText, setAmountFormat, matchAmount, matchedAmountText,
  moveItem, stepsCheck,
} from '../../app/static/js/util.js';

test('qtyText: tidy fractions for cooking units and counts in fraction mode', () => {
  const cases = [[0.125, 'cup', '1/8'], [0.25, 'tbsp', '1/4'], [1 / 3, 'tsp', '1/3'], [0.5, 'cup', '1/2'], [2 / 3, 'cup', '2/3'],
    [0.75, 'tsp', '3/4'], [1.5, 'cup', '1 1/2'], [2, 'cup', '2'], [2.5, 'slice', '2 1/2'], [1.5, null, '1 1/2'], [0.5, 'floz', '1/2'],
    [1.5, 'clove', '1 1/2'], [0.5, 'serving', '1/2'], [0.4, 'cup', '3/8'], [1.1, 'tbsp', '1 1/8']];
  for (const [n, u, want] of cases) assert.equal(qtyText(n, u, 'fraction'), want, n + ' ' + u);
});

test('qtyText: always the nearest friendly fraction in fraction mode', () => {
  const cases = [[0.3125, 'cup', '1/3'], [0.31, 'cup', '1/3'], [0.313, 'tsp', '1/3'], [1.34, 'cup', '1 1/3'], [2.5, 'cup', '2 1/2'],
    [0.05, 'tsp', '1/8'], [0.001, 'tbsp', '1/8'], [0.05, null, '1/8'], [0.99, 'cup', '1'], [1.96, 'tbsp', '2'], [0.62, 'cup', '5/8'],
    [0.62, 'slice', '2/3'], [0.4, 'serving', '1/3'], [0.4, 'clove', '1/3'], [0.88, 'cup', '7/8'], [0.88, 'egg', '1'], [3.7, 'tsp', '3 2/3'],
    [0.6667, 'cup', '2/3'], [10.3, 'cup', '10 1/3'], [0, 'cup', '0']];
  for (const [n, u, want] of cases) assert.equal(qtyText(n, u, 'fraction'), want, n + ' ' + u);
  for (const [n, u, want] of [[12, 'g', '12'], [0.05, 'g', '0.05'], [0.313, 'ml', '0.313']]) {
    assert.equal(qtyText(n, u, 'fraction'), want, n + ' ' + u);
  }
});

test('qtyText: decimal mode gives short useful decimals for cooking amounts', () => {
  const cases = [[0.313, 'cup', '0.3'], [0.3125, 'cup', '0.3'], [1 / 3, 'cup', '0.33'], [0.25, 'cup', '0.25'], [0.5, 'tbsp', '0.5'],
    [0.75, 'tsp', '0.75'], [1.5, 'cup', '1.5'], [1.34, 'cup', '1.34'], [1.3333, 'serving', '1.33'], [1.31, 'cup', '1.3'], [2 / 3, 'cup', '0.67'], [0.125, 'cup', '0.13'],
    [0.05, 'tsp', '0.05'], [0.001, 'tsp', '0.01'], [2, 'cup', '2'], [10.34, 'cup', '10.3'], [12.5, 'slice', '12.5'], [0.4, null, '0.4'], [0, 'cup', '0']];
  for (const [n, u, want] of cases) assert.equal(qtyText(n, u, 'decimal'), want, n + ' ' + u);
  for (const [n, u, want] of [[12, 'g', '12'], [0.3125, 'g', '0.313'], [28.35, 'oz', '28.35']]) assert.equal(qtyText(n, u, 'decimal'), want, n + ' ' + u);
});

test('qtyText: metric, weights and percent stay decimal; decimal mode is unchanged', () => {
  for (const u of ['g', 'kg', 'mg', 'ml', 'l', 'oz', 'lb', 'pct', 'grams', 'Ounces']) {
    assert.equal(qtyText(0.5, u, 'fraction'), '0.5', u);
    assert.equal(fractionUnit(u), false, u);
  }
  assert.equal(qtyText(1.5, 'cup', 'decimal'), '1.5');
  assert.equal(qtyText(0.125, 'tsp', 'decimal'), '0.13');
  assert.equal(qtyText(null, 'cup'), '');
  assert.equal(qtyText(NaN, 'cup'), '');
});

test('the module format reaches amountText, the wheel and amount boxes', () => {
  try {
    setAmountFormat('fraction');
    assert.equal(amountText(1.5, 'cup'), '1 1/2 cup');
    assert.equal(amountText(2.5, 'slice'), '2 1/2 slice');
    assert.equal(amountText(28.35, 'g'), '28.35 g');
    assert.equal(amountLabel('tbsp', 0.5), '1/2');
    assert.equal(rowAmountText(0.75, 'cup'), '3/4');
    setAmountFormat('decimal');
    assert.equal(amountText(1.5, 'cup'), '1.5 cup');
    assert.equal(amountLabel('tbsp', 0.5), '0.5');
    assert.equal(rowAmountText(0.75, 'cup'), '0.75');
  } finally { setAmountFormat('fraction'); }
});

test('canonUnit', () => {
  const cases = [['Cups', 'cup'], ['tablespoons', 'tbsp'], ['Tbsp.', 'tbsp'], ['T', 'tbsp'], ['t', 'tsp'], ['teaspoon', 'tsp'],
    ['fl oz', 'floz'], ['fl. oz.', 'floz'], ['fluid ounces', 'floz'], ['grams', 'g'], ['lbs', 'lb'], ['ounces', 'oz'], ['ml', 'ml'],
    ['Liters', 'l'], ['cloves', 'clove'], ['%', 'pct'], ['servings', 'serving'], ['', ''], [null, ''], ['Slices', 'slice']];
  for (const [u, want] of cases) assert.equal(canonUnit(u), want, String(u));
});

// food.units as GET /api/foods/{id} gives them: label unit first, then serving, pct, then reachable units.
const unit = (u, d, est = false) => ({ unit: u, default_amount: d, estimated: est });
const BUTTER = [unit('tbsp', 1), unit('serving', 1), unit('pct', 100), unit('g', 14), unit('oz', 0.49), unit('ml', 14.79),
  unit('cup', 0.06), unit('tsp', 3)];  // a tbsp label with its grams: weights through serving_g, volumes exact
const FLOUR_G = [unit('g', 30), unit('serving', 1), unit('pct', 100), unit('oz', 1.06), unit('ml', 30, true), unit('cup', 0.13, true),
  unit('tbsp', 2.03, true)];
const MILK = [unit('ml', 240), unit('serving', 1), unit('pct', 100), unit('g', 248), unit('floz', 8.12), unit('cup', 1.01), unit('tbsp', 16.2)];
const EGG = [unit('egg', 1), unit('serving', 1), unit('pct', 100), unit('g', 50), unit('oz', 1.76), unit('ml', 50, true)];

test('matchAmount uses the line unit when the food reaches it exactly', () => {
  assert.deepEqual(matchAmount(BUTTER, 2, 'tbsp'), { amount: 2, unit: 'tbsp', check: false });  // same unit
  assert.deepEqual(matchAmount(BUTTER, 28, 'g'), { amount: 28, unit: 'g', check: false });  // tbsp label to grams
  assert.deepEqual(matchAmount(BUTTER, 1, 'tsp'), { amount: 1, unit: 'tsp', check: false });
  assert.deepEqual(matchAmount(MILK, 1, 'Cups'), { amount: 1, unit: 'cup', check: false });  // cup to ml label
  assert.deepEqual(matchAmount(FLOUR_G, 4, 'ounces'), { amount: 4, unit: 'oz', check: false });  // oz to g
  assert.deepEqual(matchAmount(MILK, '1 1/2', 'cup'), { amount: 1.5, unit: 'cup', check: false });
});

test('matchAmount counts go to the count word or to servings', () => {
  assert.deepEqual(matchAmount(EGG, 2, null), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(EGG, 3, 'eggs'), { amount: 3, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(FLOUR_G, 2, ''), { amount: 2, unit: 'serving', check: false });
  assert.deepEqual(matchAmount(FLOUR_G, 1, 'piece'), { amount: 1, unit: 'serving', check: false });
});

test('matchAmount uses an estimated unit and flags it, as the picker offers it', () => {
  assert.deepEqual(matchAmount(FLOUR_G, 1, 'cup'), { amount: 1, unit: 'cup', check: false, estimated: true });  // only a 1 g per ml guess
  assert.deepEqual(matchAmount(FLOUR_G, 2, 'tbsp'), { amount: 2, unit: 'tbsp', check: false, estimated: true });
  assert.equal(matchAmount(MILK, 1, 'cup').estimated, undefined);
});

test('matchAmount flags what is unreachable and skips lines without an amount', () => {
  assert.deepEqual(matchAmount(BUTTER, 1, 'stick'), { amount: 1, unit: 'tbsp', check: true });
  assert.deepEqual(matchAmount(MILK, 1, 'can'), { amount: 240, unit: 'ml', check: true });
  assert.equal(matchAmount(MILK, null, 'cup'), null);
  assert.equal(matchAmount(MILK, 0, 'cup'), null);
  assert.equal(matchAmount(MILK, 'some', 'cup'), null);
  assert.equal(matchAmount([], 1, 'cup'), null);
});

test('matchedAmountText adds grams when known', () => {
  assert.equal(matchedAmountText(1, 'cup', 125), '1 cup, 125 g');
  assert.equal(matchedAmountText(0.5, 'tsp', 2.4), '1/2 tsp, 2.4 g');
  assert.equal(matchedAmountText(30, 'g', 30), '30 g');
  assert.equal(matchedAmountText(2, 'egg', null), '2 egg');
});

test('moveItem and stepsCheck', () => {
  assert.deepEqual(moveItem(['a', 'b', 'c'], 0, 1), ['b', 'a', 'c']);
  assert.deepEqual(moveItem(['a', 'b', 'c'], 2, -1), ['a', 'c', 'b']);
  assert.deepEqual(moveItem(['a', 'b'], 0, -1), ['a', 'b']);
  assert.deepEqual(moveItem(['a', 'b'], 1, 1), ['a', 'b']);
  assert.deepEqual(stepsCheck([' a  b ', '', null, 'c']), { steps: ['a b', 'c'] });
  assert.deepEqual(stepsCheck(undefined), { steps: [] });
  assert.match(stepsCheck(['x'.repeat(1001)]).error, /Step 1/);
  assert.equal(stepsCheck(new Array(60).fill('x')).steps.length, 60);
});
