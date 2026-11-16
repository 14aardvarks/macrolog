import test from 'node:test';
import assert from 'node:assert/strict';
import {
  amountLabel, amountText, servingText, setAmountFormat, getAmountFormat, parseAmount, centsText, dollarText,
} from '../../app/static/js/util.js';
import { GUIDE } from '../../app/static/js/guide.js';

test('fraction mode (default) shows quarters as fractions', () => {
  setAmountFormat('fraction');
  assert.equal(getAmountFormat(), 'fraction');
  assert.deepEqual([0.25, 0.5, 0.75, 1, 1.25, 1.5].map((v) => amountLabel('serving', v)), ['1/4', '1/2', '3/4', '1', '1 1/4', '1 1/2']);
  assert.equal(amountText(0.5, 'serving'), '1/2 serving');
  assert.equal(amountText(1.25, 'serving'), '1 1/4 servings');
});

test('decimal mode shows servings as decimals', () => {
  setAmountFormat('decimal');
  try {
    assert.deepEqual([0.25, 0.5, 0.75, 1, 1.25, 1.5, 10].map((v) => amountLabel('serving', v)), ['0.25', '0.5', '0.75', '1', '1.25', '1.5', '10']);
    assert.equal(amountText(0.5, 'serving'), '0.5 serving');
    assert.equal(amountText(1.25, 'serving'), '1.25 servings');
    assert.equal(servingText(0.125), '0.13');
  } finally { setAmountFormat('fraction'); }
});

test('cooking units follow the format, metric, weights and percent stay decimal', () => {
  assert.equal(amountLabel('cup', 0.5, 'fraction'), '1/2');
  assert.equal(amountText(0.25, 'cup', 'fraction'), '1/4 cup');
  assert.equal(amountLabel('cup', 0.5, 'decimal'), '0.5');
  assert.equal(amountText(0.25, 'cup', 'decimal'), '0.25 cup');
  for (const f of ['fraction', 'decimal']) {
    assert.equal(amountText(25, 'pct', f), '25% of a serving');
    assert.equal(amountText(30, 'g', f), '30 g');
    assert.equal(amountText(0.5, 'oz', f), '0.5 oz');
  }
});

test('explicit format wins over the module default and bad values fall back to fraction', () => {
  setAmountFormat('decimal');
  try { assert.equal(amountLabel('serving', 0.5, 'fraction'), '1/2'); } finally { setAmountFormat('fraction'); }
  setAmountFormat('nonsense');
  assert.equal(getAmountFormat(), 'fraction');
});

test('typing accepts both formats in either mode', () => {
  for (const f of ['fraction', 'decimal']) {
    setAmountFormat(f);
    assert.equal(parseAmount('1/2'), 0.5);
    assert.equal(parseAmount('0.5'), 0.5);
    assert.equal(parseAmount('1 1/4'), 1.25);
    assert.equal(parseAmount('1,25'), 1.25);
  }
  setAmountFormat('fraction');
});

test('centsText and dollarText', () => {
  assert.equal(centsText(0.0045), '0.45 cents');
  assert.equal(centsText(0.01), '1 cent');
  assert.equal(centsText(0.034), '3.4 cents');
  assert.equal(centsText(0.12), '12 cents');
  assert.equal(centsText(1.5), '$1.50');
  assert.equal(centsText(null), '');
  assert.equal(centsText(NaN), '');
  assert.equal(dollarText(0.1234), '$0.12');
  assert.equal(dollarText(0), '$0.00');
  assert.equal(dollarText(0.001), 'under $0.01');
  assert.equal(dollarText(null), '');
});

test('guide has a Claude group', () => {
  const g = GUIDE.find((x) => x.heading === 'Claude');
  assert.ok(g && g.bullets.length >= 3);
});
