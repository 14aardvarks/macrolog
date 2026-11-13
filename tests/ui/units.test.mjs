import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanUnitText, unitToSave, unitChoices, isCustomUnit, unitLabel, initialPick, CUSTOM_UNIT_MAX, matchAmount, amountText, matchedAmountText, cookIngredient, cookIngredients, qtyText, ingredientText } from '../../app/static/js/util.js';
import { reviewBody, reviewDraft, rowText, importUnitOptions, IMPORT_UNITS, blankRow } from '../../app/static/js/recipeimport.js';

const EGG = [{ unit: 'egg', default_amount: 1 }, { unit: 'serving', default_amount: 1 }, { unit: 'count', default_amount: 1 }, { unit: '', default_amount: 1 }];
const FLOUR = [{ unit: 'g', default_amount: 30 }, { unit: 'cup', default_amount: 0.25, estimated: true }, { unit: 'count', default_amount: 1 }, { unit: '', default_amount: 1 }];

test('review unit choices start with lowercase count and have no None choice', () => {
  assert.deepEqual(IMPORT_UNITS[0], ['count', 'count']);
  assert.ok(!IMPORT_UNITS.some(([v, l]) => v === '' || l === 'None' || l === 'Count'));
  assert.deepEqual(importUnitOptions()[0], { value: 'count', label: 'count' });
});

test('custom unit text is trimmed, capped, stripped of control characters and kept as typed', () => {
  assert.equal(cleanUnitText('  to \n taste\u0000 '), 'to taste');
  assert.equal(cleanUnitText('x'.repeat(50)).length, CUSTOM_UNIT_MAX);
  assert.equal(cleanUnitText(null), '');
  assert.equal(unitToSave('Shell'), 'Shell');
  assert.equal(unitToSave('Pinches'), 'pinch');  // a fuzzy unit is a known unit
  assert.equal(unitToSave('Cups'), 'cup');
  assert.equal(unitToSave('Count'), 'count');
  for (const blank of ['', '  ', '-', 'None', null, undefined]) assert.equal(unitToSave(blank), '');
});

test('unit choices drop the blank unit, show count lowercase and spot a typed unit', () => {
  const ch = unitChoices([{ unit: 'g', label: 'g' }, { unit: 'count', label: 'Count' }, { unit: '', label: 'None' }, { unit: 'cup', label: 'cup', estimated: true }]);
  assert.deepEqual(ch.map((c) => [c.value, c.label]), [['g', 'g'], ['count', 'count'], ['cup', 'cup']]);
  assert.equal(isCustomUnit('pinch', ch), true);
  assert.equal(isCustomUnit('g', ch), false);
  assert.equal(isCustomUnit('', ch), false);
  assert.equal(unitLabel('count'), 'count');
});

test('a typed unit starts the picker on Custom with its word, blank starts on Custom empty', () => {
  const us = [{ unit: 'g', default_amount: 30 }, { unit: 'count', default_amount: 1 }, { unit: '', default_amount: 1 }];
  assert.deepEqual(initialPick(us, { unit: 'pinch', amount: 2 }, null), { unit: '', amount: 2, word: 'pinch' });
  assert.deepEqual(initialPick(us, { unit: '', amount: 2 }, null), { unit: '', amount: 2 });
  assert.deepEqual(initialPick(us, { unit: 'count', amount: 2 }, null), { unit: 'count', amount: 2 });
});

test('a typed unit reaches the saved line unchanged and a blank one is null', () => {
  const d = reviewDraft({ name: 'Soup', ingredients: [] });
  const body = (unit) => reviewBody({ ...d, rows: [{ ...blankRow(), name: 'salt', amount: '1', unit }] }).body.ingredients[0];
  assert.deepEqual([body('pinch').unit, body('pinch').text], ['pinch', '1 pinch salt']);
  assert.equal(body('to taste').unit, 'to taste');
  assert.equal(body('').unit, 'count');  // an amount with no unit is a count
  const noAmount = reviewBody({ ...d, rows: [{ ...blankRow(), name: 'salt', unit: '' }] }).body.ingredients[0];
  assert.deepEqual([noAmount.amount, noAmount.unit], [null, null]);  // no amount and no unit stays plain text
});

test('a review line needs neither amount nor unit', () => {
  const d = reviewDraft({ name: 'Soup', ingredients: [{ text: 'salt to taste', amount: null, unit: null, name: 'salt', note: 'to taste' },
    { text: '2 eggs', amount: 2, unit: null, name: 'egg', note: null }, { text: 'oil', amount: null, unit: 'tbsp', name: 'oil', note: null }] });
  const r = reviewBody(d);
  assert.equal(r.error, undefined);
  assert.deepEqual(r.body.ingredients.map((i) => [i.amount, i.unit, i.name]), [[null, null, 'salt'], [2, 'count', 'egg'], [null, 'tbsp', 'oil']]);
  assert.equal(r.body.ingredients[0].text, 'salt, to taste');
  const blank = { ...d, rows: [{ ...blankRow(), name: 'pepper', unit: 'count', amount: '2' }] };
  assert.deepEqual(reviewBody(blank).body.ingredients[0], { text: '2 pepper', amount: 2, unit: 'count', name: 'pepper', note: null, pkg_amount: null, pkg_unit: null });
  assert.equal(rowText({ ...blankRow(), name: 'water', unit: 'floz', amount: '8' }), '8 fl oz water');
});

test('matchAmount skips blank amounts and treats blank and Count as a plain count', () => {
  for (const a of [null, '', 0, undefined]) { assert.equal(matchAmount(EGG, a, 'count'), null); assert.equal(matchAmount(FLOUR, a, ''), null); }
  assert.deepEqual(matchAmount(EGG, 2, 'count'), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(EGG, 2, ''), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(EGG, 2, null), { amount: 2, unit: 'egg', check: false });
  const nw = { amount: FLOUR[0].default_amount, unit: FLOUR[0].unit, check: true, reason: 'no_weight' };  // issue #45
  assert.deepEqual(matchAmount(FLOUR, 2, 'Count'), nw);
  assert.deepEqual(matchAmount(FLOUR, 2, undefined), nw);
});

test('amount text with a blank unit or Count has no stray space', () => {
  assert.equal(amountText(2, ''), '2');
  assert.equal(amountText(1.5, 'count'), '1 1/2 count');
  assert.equal(matchedAmountText(2, '', null), '2');
  assert.equal(qtyText(2, ''), '2');
});

test('cooking view keeps plain lines and scales amounts without units', () => {
  const salt = { src: { text: 'salt, to taste', amount: null, unit: null, name: 'salt', note: 'to taste' }, food: null };
  assert.deepEqual(cookIngredient(salt, 3), { text: 'salt, to taste', scaled: false });
  assert.deepEqual(cookIngredient({ src: { text: '2 eggs', amount: 2, unit: null, name: 'egg', note: null } }, 2), { text: '4 egg', scaled: true });
  assert.deepEqual(cookIngredient({ src: { text: 'x', amount: 2, unit: 'count', name: 'egg', note: null } }, 1.5), { text: '3 egg', scaled: true });
  assert.equal(cookIngredient({ food: { name: 'Salt' }, amount: 1, unit: '' }, 2).text, '2 Salt');
  const meal = { servings: 2, items: [salt, { src: { amount: 1, unit: '', name: 'lime' } }] };
  assert.deepEqual(cookIngredients(meal, 4).map((x) => x.text), ['salt, to taste', '2 lime']);
});

test('ingredientText shows a count without its unit word and other units as usual', () => {
  assert.equal(ingredientText(3, 'count', 'carrots'), '3 carrots');
  assert.equal(ingredientText(1.5, '', 'onion'), '1 1/2 onion');
  assert.equal(ingredientText(1.5, 'cup', 'flour'), '1 1/2 cup flour');
  assert.equal(ingredientText(2, 'serving', 'rice'), '2 servings rice');
});

test('matchAmount treats an amount with no unit as count, with Check Amount where a count has no weight', () => {
  for (const u of [undefined, null, '', 'count', 'Count']) {
    assert.deepEqual(matchAmount(FLOUR, 3, u), { amount: FLOUR[0].default_amount, unit: FLOUR[0].unit, check: true, reason: 'no_weight' });
    assert.deepEqual(matchAmount(EGG, 3, u), { amount: 3, unit: 'egg', check: false });
  }
  assert.equal(matchAmount(EGG, null, ''), null);  // no amount, nothing to count
});

test('the cooking view shows 3 carrots for a stored count and a line to taste as salt, to taste', () => {
  assert.equal(cookIngredient({ src: { amount: 3, unit: 'count', name: 'carrots', note: null } }, 1).text, '3 carrots');
  assert.equal(cookIngredient({ src: { amount: 3, unit: 'count', name: 'carrots', note: 'peeled' } }, 2).text, '6 carrots, peeled');
  assert.equal(cookIngredient({ food: { name: 'Carrot' }, amount: 2, unit: 'count' }, 1).text, '2 Carrot');
  assert.equal(cookIngredient({ src: { text: 'salt, to taste', amount: null, unit: null, name: 'salt', note: 'to taste' } }, 4).text, 'salt, to taste');
});
