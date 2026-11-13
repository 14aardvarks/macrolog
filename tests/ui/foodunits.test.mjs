// Issue #45 steps 4 to 6 on the client: weight units from food_units (clove (3 g), can (425 g), large (50 g)) in matchAmount, kept in
// sync with units.count_row, the estimate sources, and Use Grams keeping the line so its grams become your weight.
import test from 'node:test';
import assert from 'node:assert/strict';
import { matchAmount, weightEntry, sizeHint, checkReasonText, checkList, ESTIMATE_SOURCES } from '../../app/static/js/util.js';
import { parseIngredientText, reviewDraft, reviewBody, useGrams } from '../../app/static/js/recipeimport.js';

const u = (unit, d, estimated) => ({ unit, default_amount: d, ...(estimated ? { estimated: true } : {}) });
const w = (unit, grams, source, estimated) => ({ unit, default_amount: 1, label: unit + ' (' + grams + ' g)', grams, source, estimated: !!estimated });
const GARLIC = [u('g', 100), u('serving', 1), u('pct', 100), u('oz', 3.53), w('clove', 3, 'table', true), w('head', 40, 'table', true)];
const EGG = [u('g', 100), u('serving', 1), u('pct', 100), w('count', 50, 'table', true), w('large', 50, 'fdc'), w('medium', 44, 'fdc'), w('small', 38, 'fdc')];
const EGG_LABEL = [u('egg', 1), u('serving', 1), u('pct', 100), u('g', 50), u('count', 1)];
const BEANS = [u('g', 100), u('serving', 1), u('pct', 100), u('oz', 3.53), w('can', 425, 'table', true)];

test('a weight unit converts with its source and estimate flag', () => {
  assert.deepEqual(matchAmount(GARLIC, 2, 'cloves'), { amount: 2, unit: 'clove', check: false, estimated: true, source: 'table' });
  assert.deepEqual(matchAmount(GARLIC, 1, 'Head'), { amount: 1, unit: 'head', check: false, estimated: true, source: 'table' });
  assert.deepEqual(matchAmount(GARLIC, 1, 'bunch'), { amount: 100, unit: 'g', check: true, reason: 'no_weight' });
  assert.deepEqual(matchAmount(BEANS, 1, 'can'), { amount: 1, unit: 'can', check: false, estimated: true, source: 'table' });
});

test('a plain count uses the size the line names, else count, medium, large, small', () => {
  assert.equal(matchAmount(EGG, 2, '', null, 'eggs').unit, 'count');
  assert.deepEqual(matchAmount(EGG, 2, 'count', null, 'large eggs'), { amount: 2, unit: 'large', check: false, source: 'fdc' });
  assert.equal(matchAmount(EGG, 2, null, null, 'extra-large eggs').unit, 'large');
  assert.equal(matchAmount(EGG, 2, 'small').unit, 'small');
  assert.equal(matchAmount(EGG.filter((x) => x.unit !== 'count'), 2, '').unit, 'medium');
  assert.deepEqual(matchAmount(EGG_LABEL, 2, '', null, 'small eggs'), { amount: 2, unit: 'egg', check: false });  // the label's word wins
  assert.equal(weightEntry(EGG_LABEL, 'count'), null);
  assert.equal(sizeHint('Jumbo eggs'), 'large');
  assert.equal(sizeHint('eggs'), null);
});

test('only your own weight beats a printed size', () => {
  assert.deepEqual(matchAmount(BEANS, 1, 'can', { amount: 15, unit: 'oz' }), { amount: 15, unit: 'oz', check: false });
  const mine = [...BEANS.slice(0, 4), w('can', 400, 'user')];
  assert.deepEqual(matchAmount(mine, 1, 'can', { amount: 15, unit: 'oz' }), { amount: 1, unit: 'can', check: false, source: 'user' });
});

test('every source has words', () => {
  for (const k of ['density', 'guess', 'claude', 'user', 'fdc', 'off', 'table', 'ai']) assert.ok(ESTIMATE_SOURCES[k], k);
  assert.equal(checkReasonText('estimated', 'clove', 'table'), 'estimated from a typical weight, source a typical weight table');
  const meal = { items: [{ id: 1, food: { name: 'Garlic' }, src: { name: 'garlic', unit: 'clove' }, estimated: true, estimate_source: 'table' }] };
  assert.equal(checkList(meal)[0].text, 'Garlic: estimated from a typical weight, source a typical weight table');
});

test('Use Grams keeps the line and the review sends it', () => {
  const d = reviewDraft({ ingredients: parseIngredientText('2 cloves garlic\n1 cup flour').ingredients });
  useGrams(d.rows[0]);
  useGrams(d.rows[1]);  // not a count: nothing kept
  assert.deepEqual([d.rows[0].wasAmount, d.rows[0].wasUnit, d.rows[1].wasAmount], [2, 'clove', null]);
  d.name = 'G';
  d.rows[0].amount = '6';
  d.rows[1].amount = '120';
  const body = reviewBody(d).body.ingredients;
  assert.deepEqual([body[0].was_amount, body[0].was_unit, body[0].unit], [2, 'clove', 'g']);
  assert.equal('was_amount' in body[1], false);
  d.rows[0].unit = 'cup';  // changed away from a weight: the line is not sent
  assert.equal('was_amount' in reviewBody(d).body.ingredients[0], false);
});
