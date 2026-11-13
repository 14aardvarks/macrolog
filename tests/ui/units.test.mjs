import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanUnitText, unitToSave, unitChoices, isCustomUnit, unitLabel, initialPick, CUSTOM_UNIT_MAX, matchAmount, amountText, matchedAmountText, cookIngredient, cookIngredients, qtyText } from '../../app/static/js/util.js';
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
  assert.equal(unitToSave('Pinch'), 'Pinch');
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
  assert.equal(body('').unit, null);
});

test('a review line needs neither amount nor unit', () => {
  const d = reviewDraft({ name: 'Soup', ingredients: [{ text: 'salt to taste', amount: null, unit: null, name: 'salt', note: 'to taste' },
    { text: '2 eggs', amount: 2, unit: null, name: 'egg', note: null }, { text: 'oil', amount: null, unit: 'tbsp', name: 'oil', note: null }] });
  const r = reviewBody(d);
  assert.equal(r.error, undefined);
  assert.deepEqual(r.body.ingredients.map((i) => [i.amount, i.unit, i.name]), [[null, null, 'salt'], [2, null, 'egg'], [null, 'tbsp', 'oil']]);
  assert.equal(r.body.ingredients[0].text, 'salt, to taste');
  const blank = { ...d, rows: [{ ...blankRow(), name: 'pepper', unit: 'count', amount: '2' }] };
  assert.deepEqual(reviewBody(blank).body.ingredients[0], { text: '2 count pepper', amount: 2, unit: 'count', name: 'pepper', note: null });
  assert.equal(rowText({ ...blankRow(), name: 'water', unit: 'floz', amount: '8' }), '8 fl oz water');
});

test('matchAmount skips blank amounts and treats blank and Count as a plain count', () => {
  for (const a of [null, '', 0, undefined]) { assert.equal(matchAmount(EGG, a, 'count'), null); assert.equal(matchAmount(FLOUR, a, ''), null); }
  assert.deepEqual(matchAmount(EGG, 2, 'count'), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(EGG, 2, ''), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(EGG, 2, null), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(matchAmount(FLOUR, 2, 'Count'), { amount: 2, unit: 'serving', check: false });
  assert.deepEqual(matchAmount(FLOUR, 2, undefined), { amount: 2, unit: 'serving', check: false });
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
  assert.deepEqual(cookIngredient({ src: { text: 'x', amount: 2, unit: 'count', name: 'egg', note: null } }, 1.5), { text: '3 count egg', scaled: true });
  assert.equal(cookIngredient({ food: { name: 'Salt' }, amount: 1, unit: '' }, 2).text, '2 Salt');
  const meal = { servings: 2, items: [salt, { src: { amount: 1, unit: '', name: 'lime' } }] };
  assert.deepEqual(cookIngredients(meal, 4).map((x) => x.text), ['salt, to taste', '2 lime']);
});
