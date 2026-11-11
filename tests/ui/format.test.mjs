import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseDecimal, fmtNum, fmtAmount, roundTo, progressText, remainingText, barWidth, pctTotal, digitsOnly, fitSize, debounce,
} from '../../app/static/js/util.js';

test('parseDecimal accepts comma and dot', () => {
  assert.equal(parseDecimal('1,5'), 1.5);
  assert.equal(parseDecimal('1.5'), 1.5);
  assert.equal(parseDecimal(' 2 '), 2);
  assert.equal(parseDecimal('.5'), 0.5);
  assert.equal(parseDecimal('3.'), 3);
  assert.equal(parseDecimal('0,125'), 0.125);
  assert.equal(parseDecimal(4), 4);
});

test('parseDecimal rejects junk', () => {
  for (const s of ['', '  ', 'abc', '1,2,3', '1.2.3', '1e3', '--1', null, undefined, '12g', NaN, Infinity]) {
    assert.equal(parseDecimal(s), null, String(s));
  }
});

test('fmtNum trims zeros and handles null', () => {
  assert.equal(fmtNum(12.5), '12.5');
  assert.equal(fmtNum(12), '12');
  assert.equal(fmtNum(12.04), '12');
  assert.equal(fmtNum(0), '0');
  assert.equal(fmtNum(1234.5678, 0), '1235');
  assert.equal(fmtNum(null), '');
  assert.equal(fmtNum(NaN), '');
  assert.equal(fmtNum(0.25, 2), '0.25');
});

test('fmtAmount keeps three decimals', () => {
  assert.equal(fmtAmount(0.125), '0.125');
  assert.equal(fmtAmount(2), '2');
  assert.equal(fmtAmount(1.5), '1.5');
});

test('roundTo', () => {
  assert.equal(roundTo(1.005, 2), 1.01);
  assert.equal(roundTo(0.1 + 0.2, 2), 0.3);
});

test('progress and remaining text', () => {
  assert.equal(progressText(1200, 3000, 40), '1200 / 3000 (40%)');
  assert.equal(progressText(80.4, 225, 36, ' g'), '80 / 225 g (36%)');
  assert.equal(remainingText(1800), '1800 left');
  assert.equal(remainingText(-200.4), '200 over');
  assert.equal(remainingText(12, ' g'), '12 g left');
  assert.equal(remainingText(null), '');
});

test('barWidth is clamped', () => {
  assert.equal(barWidth(150), 100);
  assert.equal(barWidth(-5), 0);
  assert.equal(barWidth(40), 40);
  assert.equal(barWidth(undefined), 0);
});

test('pctTotal avoids float noise', () => {
  assert.equal(pctTotal(33.3, 33.3, 33.4), 100);
  assert.equal(pctTotal(50, 30, 20), 100);
});

test('digitsOnly and fitSize', () => {
  assert.equal(digitsOnly('0 12345-678'), '012345678');
  assert.deepEqual(fitSize(4000, 3000, 1280), { w: 1280, h: 960 });
  assert.deepEqual(fitSize(3000, 4000, 1280), { w: 960, h: 1280 });
  assert.deepEqual(fitSize(800, 600, 1280), { w: 800, h: 600 });
});

test('debounce only fires the last call', async () => {
  const calls = [];
  const d = debounce((x) => calls.push(x), 20);
  d(1); d(2); d(3);
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(calls, [3]);
  d(4); d.cancel();
  await new Promise((r) => setTimeout(r, 40));
  assert.deepEqual(calls, [3]);
});

import {
  parseAmount, fractionText, amountText, unitLabel, initialPick, convertAmount,
} from '../../app/static/js/util.js';

test('parseAmount accepts decimals, fractions and unicode fractions', () => {
  const cases = [['1.5', 1.5], ['1,5', 1.5], [' 2 ', 2], ['.5', 0.5], ['1/2', 0.5], ['1 / 2', 0.5], ['3/4', 0.75],
    ['1 1/2', 1.5], ['2  1/4', 2.25], ['½', 0.5], ['¼', 0.25], ['¾', 0.75], ['1½', 1.5], ['1 ½', 1.5],
    ['2¾', 2.75], ['⅓', 1 / 3], ['⅔', 2 / 3], ['1⅓', 1 + 1 / 3], ['0', 0], [1.25, 1.25]];
  for (const [text, want] of cases) assert.ok(Math.abs(parseAmount(text) - want) < 1e-9, String(text));
});

test('parseAmount rejects bad input', () => {
  for (const bad of ['', '   ', null, undefined, '1/0', '0/0', 'abc', '1/', '/2', '1/2/3', '-1', '-1/2', '1 1/0', '1.5.5', '1 2', 'half', NaN, Infinity, '½½'])
    assert.equal(parseAmount(bad), null, String(bad));
});

test('fractionText', () => {
  const cases = [[0.5, '1/2'], [0.25, '1/4'], [0.75, '3/4'], [1, '1'], [1.5, '1 1/2'], [2, '2'], [1 / 3, '1/3'], [2 / 3, '2/3'],
    [0.125, '1/8'], [2.25, '2 1/4'], [0.375, '3/8']];
  for (const [n, want] of cases) assert.equal(fractionText(n), want, String(n));
  assert.equal(fractionText(0.4), null);
  assert.equal(fractionText(-1), null);
  assert.equal(fractionText(NaN), null);
});

test('amountText for serving, pct and other units', () => {
  assert.equal(amountText(0.5, 'serving'), '1/2 serving');
  assert.equal(amountText(1, 'serving'), '1 serving');
  assert.equal(amountText(1.5, 'serving'), '1 1/2 servings');
  assert.equal(amountText(2, 'serving'), '2 servings');
  assert.equal(amountText(0.4, 'serving'), '0.4 serving');
  assert.equal(amountText(25, 'pct'), '25% of a serving');
  assert.equal(amountText(150, 'pct'), '150% of a serving');
  assert.equal(amountText(2, 'slice'), '2 slice');
  assert.equal(amountText(30, 'g'), '30 g');
  assert.equal(unitLabel('pct'), '% of serving');
  assert.equal(unitLabel('g'), 'g');
});

test('last used serving or pct reopens exactly, and conversion between them', () => {
  const units = [{ unit: 'slice', default_amount: 1 }, { unit: 'serving', default_amount: 1 }, { unit: 'pct', default_amount: 100 }, { unit: 'g', default_amount: 34 }];
  assert.deepEqual(initialPick(units, { unit: 'serving', amount: 0.5 }), { unit: 'serving', amount: 0.5 });
  assert.deepEqual(initialPick(units, { unit: 'pct', amount: 25 }), { unit: 'pct', amount: 25 });
  assert.equal(convertAmount(units, 0.5, 'serving', 'pct'), 50);
  assert.equal(convertAmount(units, 25, 'pct', 'serving'), 0.25);
  assert.equal(convertAmount(units, 0.5, 'serving', 'g'), 17);
});
