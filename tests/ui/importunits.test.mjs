// Issue #55: import units are weights and volumes. Claude's estimates keep their source and wording, a real portion replaces them,
// odd words typed in the amount box go to the note, and a count with no known weight says so.
import test from 'node:test';
import assert from 'node:assert/strict';
import { linePick, weightTag, weightReasonLine, RECIPE_UNITS, isMeasureUnit } from '../../app/static/js/util.js';
import { reviewDraft, reviewBody, reviewFlag, rowEstimated, estimateNote, splitAmountBox, tidyAmountBox, IMPORT_UNITS, parseIngredientText } from '../../app/static/js/recipeimport.js';

const CLAUDE = { name: 'Curry', ingredients: [
  { text: '3 cloves garlic', amount: 9, unit: 'g', name: 'garlic', note: '3 cloves', estimated: true, est_source: 'ai', was_amount: 3, was_unit: 'clove' },
  { text: '1 can coconut milk', amount: 13.5, unit: 'floz', name: 'coconut milk', note: '1 can', estimated: true, est_source: 'ai', was_amount: 1, was_unit: 'can' },
  { text: '2 eggs', amount: 100, unit: 'g', name: 'eggs', note: '2 eggs', estimated: true, est_source: 'table', was_amount: 2, was_unit: 'count' },
  { text: '1 cup rice', amount: 1, unit: 'cup', name: 'rice', note: null, estimated: false },
] };

test('only weights and volumes are unit choices', () => {
  assert.deepEqual(RECIPE_UNITS, ['g', 'kg', 'oz', 'lb', 'ml', 'l', 'floz', 'cup', 'tbsp', 'tsp']);
  assert.deepEqual(IMPORT_UNITS.map(([v]) => v), RECIPE_UNITS);
  for (const u of ['count', 'clove', 'can', 'pinch', '', 'serving']) assert.equal(isMeasureUnit(u), false, u);
});

test('the review keeps an untouched estimate and sends its source and wording', () => {
  const d = reviewDraft(CLAUDE);
  assert.deepEqual(d.rows.map(rowEstimated), [true, true, true, false]);
  assert.equal(estimateNote(d.rows[0]), 'Estimated by Claude from 3 cloves');
  assert.equal(estimateNote(d.rows[2]), 'Estimated from a typical weight');
  assert.equal(estimateNote(d.rows[3]), '');
  const b = reviewBody({ ...d, name: 'Curry' }).body.ingredients;
  assert.deepEqual([b[0].amount, b[0].unit, b[0].estimated, b[0].est_source, b[0].was_amount, b[0].was_unit], [9, 'g', true, 'ai', 3, 'clove']);
  assert.deepEqual([b[1].unit, b[1].estimated, b[1].was_unit], ['floz', true, 'can']);
  assert.equal(b[2].est_source, 'table');
  assert.equal(b[3].estimated, undefined);
});

test('an edited estimate is the person\'s own amount and sends no estimate', () => {
  const d = reviewDraft(CLAUDE);
  d.rows[0].amount = '12';
  d.rows[1].unit = 'ml';
  assert.equal(rowEstimated(d.rows[0]), false);
  assert.equal(estimateNote(d.rows[1]), '');
  const b = reviewBody({ ...d, name: 'Curry' }).body.ingredients;
  for (const r of b.slice(0, 2)) assert.ok(!('estimated' in r) && !('was_amount' in r), JSON.stringify(r));
});

test('words typed in the amount box: a measure becomes the unit, anything else joins the note', () => {
  assert.deepEqual(splitAmountBox('30 g'), { amount: '30', unit: 'g', extra: '' });
  assert.deepEqual(splitAmountBox('2 cups chopped'), { amount: '2', unit: 'cup', extra: 'chopped' });
  assert.deepEqual(splitAmountBox('2 pinches'), { amount: '2', unit: null, extra: 'pinches' });
  assert.equal(splitAmountBox('1 1/2'), null);
  assert.equal(splitAmountBox(''), null);
  const r = { amount: '3 large', unit: '', note: 'peeled', name: 'eggs' };
  assert.equal(tidyAmountBox(r), true);
  assert.deepEqual([r.amount, r.unit, r.note], ['3', '', 'large, peeled']);
  const body = reviewBody({ name: 'S', rows: [{ amount: '2 pinches', unit: '', name: 'salt', note: '' }], steps: [] }).body;
  assert.deepEqual([body.ingredients[0].amount, body.ingredients[0].unit, body.ingredients[0].note], [2, 'count', 'pinches']);
});

test('a count with no known weight shows a short disclaimer, in plain words', () => {
  const rows = reviewDraft(parseIngredientText('3 widgets\n2 cloves garlic\n1 cup flour')).rows;
  assert.deepEqual([rows[0].unit, rows[1].unit], ['count', 'clove']);  // Split Lines Without Claude keeps the fallback units
  const t = reviewFlag(rows[0]);
  assert.equal(t, 'No standard weight for count, so it shows Check Amount after matching unless the food has a weight per item');
  assert.equal(weightReasonLine('no_weight', 'count'), t);
  assert.equal(weightReasonLine('no_size', 'can'), 'Can size not printed, so it shows Check Amount after matching unless the food has a package weight');
  assert.equal(weightReasonLine(null, 'count'), '');  // a typical weight is known: nothing to say
  assert.equal(reviewFlag(rows[2]), '');
  for (const s of [t, weightReasonLine('no_size', 'can')]) assert.ok(!/[—:]/.test(s), s);
});

const GARLIC = (src) => [{ unit: 'g', default_amount: 100 }, { unit: 'clove', default_amount: 1, grams: 4, source: src, estimated: src === 'table' || src === 'ai' }];
const LINE = { amount: 9, unit: 'g', pkg: null, name: 'garlic', was: { amount: 3, unit: 'clove' } };

test('a real portion replaces the estimate when a food is picked', () => {
  for (const src of ['fdc', 'off', 'user']) assert.deepEqual(linePick(GARLIC(src), LINE), { amount: 3, unit: 'clove', check: false, source: src }, src);
  for (const src of ['table', 'ai']) assert.deepEqual(linePick(GARLIC(src), LINE), { amount: 9, unit: 'g', check: false }, src);
  const egg = [{ unit: 'egg', default_amount: 1 }, { unit: 'g', default_amount: 50 }];
  assert.deepEqual(linePick(egg, { amount: 100, unit: 'g', name: 'eggs', was: { amount: 2, unit: 'count' } }), { amount: 2, unit: 'egg', check: false });
  assert.deepEqual(linePick(GARLIC('fdc'), { ...LINE, was: null }), { amount: 9, unit: 'g', check: false });
});

test('an import estimate in grams shows the Estimated Weight tag', () => {
  const row = { food: {}, unit: 'g', amount: 9, estimated: true, weight_source: 'ai', estimate_source: 'claude', weight_grams: 9, line_estimate: true };
  assert.equal(weightTag(row).text, 'Estimated Weight 9 g, Claude Estimate');
  assert.equal(weightTag({ ...row, weight_source: 'table', estimate_source: 'table' }).text, 'Estimated Weight 9 g, Typical Weight');
  assert.equal(weightTag({ ...row, line_estimate: undefined }), null);  // a plain grams row still shows none
});
