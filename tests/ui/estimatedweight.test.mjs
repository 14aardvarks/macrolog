// Issue #45 step 8: the Estimated Weight tag (grams and the source in words), the "N amounts are estimated" header list, the
// import review's typical weight before matching, and the grams typed in the tag.
import test from 'node:test';
import assert from 'node:assert/strict';
import { weightTag, estimateList, estimateSummary, unitPreviewText, tagGrams, WEIGHT_SOURCE_WORDS, ESTIMATE_HELP, FULL_CLAUDE_ACTIONS } from '../../app/static/js/util.js';

const row = (o) => ({ id: 1, food: { name: 'garlic' }, src: { name: 'garlic', unit: 'clove' }, amount: 2, unit: 'clove', check: false, ...o });

test('the tag names grams and the source in words', () => {
  assert.equal(weightTag(row({ estimated: true, weight_source: 'table', estimate_source: 'table', weight_grams: 6 })).text, 'Estimated Weight 6 g, Typical Weight');
  assert.equal(weightTag(row({ estimated: true, weight_source: 'ai', estimate_source: 'claude', weight_grams: 10 })).text, 'Estimated Weight 10 g, Claude Estimate');
  assert.equal(weightTag(row({ estimated: false, weight_source: 'user', weight_grams: 8 })).text, 'Weight 8 g, Your Weight');
  assert.equal(weightTag(row({ estimated: false, weight_source: 'fdc', weight_grams: 6 })).word, 'USDA');
  assert.equal(weightTag(row({ estimated: false, weight_source: 'off', weight_grams: 425 })).word, 'Open Food Facts');
  assert.equal(weightTag(row({ unit: 'cup', estimated: true, estimate_source: 'density', weight_grams: 160 })).text, 'Estimated Weight 160 g, Typical Density');
  assert.equal(weightTag(row({ estimated: true, estimate_source: 'claude', weight_grams: 6.25 })).text, 'Estimated Weight 6.3 g, Claude Estimate');
});

test('no tag on a check row, a plain row, grams or a missing weight', () => {
  assert.equal(weightTag(row({ check: true, estimated: true, weight_source: 'table', weight_grams: 6 })), null);
  assert.equal(weightTag(row({ estimated: false, weight_source: null, weight_grams: null })), null);
  assert.equal(weightTag(row({ unit: 'g', estimated: true, estimate_source: 'claude', weight_grams: 6 })), null);
  assert.equal(weightTag(row({ estimated: true, weight_source: 'table', weight_grams: null })), null);
  assert.equal(weightTag({ kind: 'none' }), null);
  assert.equal(weightTag(null), null);
});

test('the header lists estimated rows with their source', () => {
  const meal = { items: [row({ estimated: true, weight_source: 'table', weight_grams: 6 }),
    row({ id: 2, src: { name: 'mystery root' }, estimated: true, weight_source: 'ai', weight_grams: 10 }),
    row({ id: 3, estimated: false, weight_source: 'user', weight_grams: 8 }),
    row({ id: 4, check: true, estimated: true }), row({ id: 5, skipped: true, estimated: true, weight_grams: 1, weight_source: 'table' }),
    row({ id: 6, src: { name: 'flour' }, unit: 'g', estimated: true, estimate_source: 'guess' })] };
  assert.deepEqual(estimateList(meal), [{ id: 1, text: 'Garlic: 6 g, Typical Weight' }, { id: 2, text: 'Mystery root: 10 g, Claude Estimate' },
    { id: 6, text: 'Flour: 1 g per ml Guess' }]);
  assert.equal(estimateSummary(3), '3 amounts are estimated');
  assert.equal(estimateSummary(1), '1 amount is estimated');
  assert.equal(estimateSummary(0), '');
  // recipe log parts have a name and no src
  assert.deepEqual(estimateList({ parts: [{ id: 9, name: 'garlic', amount: 2, unit: 'clove', estimated: true, weight_source: 'ai', weight_grams: 10 }] }),
    [{ id: 9, text: 'Garlic: 10 g, Claude Estimate' }]);
});

test('the review shows the typical weight before matching, or the real reason', () => {
  assert.equal(unitPreviewText({ unit: 'clove', grams: 3, total: 6, source: 'table', estimated: true }), 'Typical weight 3 g per clove (estimate)');
  assert.equal(unitPreviewText({ unit: 'can', grams: 425, source: 'table', estimated: true, note: 'Standard can size assumed' }), 'Standard can size 425 g (estimate)');
  assert.equal(unitPreviewText({ reason: 'no_weight', unit: 'clove' }), 'No standard weight for clove, enter grams');
  assert.equal(unitPreviewText({ reason: 'no_size', unit: 'can' }), 'Can size not printed, pick a size or enter grams');
  assert.equal(unitPreviewText({ source: 'printed', grams: 425 }), '');
  assert.equal(unitPreviewText({}), '');
  assert.equal(unitPreviewText(undefined), '');
});

test('grams typed in the tag', () => {
  assert.equal(tagGrams('12'), 12);
  assert.equal(tagGrams(' 2,5 '), 2.5);
  assert.equal(tagGrams('0'), null);
  assert.equal(tagGrams('abc'), null);
  assert.equal(tagGrams('200000'), null);
});

test('words, settings hint and cost label', () => {
  assert.deepEqual(['fdc', 'off', 'table', 'ai', 'user'].map((k) => WEIGHT_SOURCE_WORDS[k]), ['USDA', 'Open Food Facts', 'Typical Weight', 'Claude Estimate', 'Your Weight']);
  assert.ok(/Estimated Weight/.test(ESTIMATE_HELP) && !/—/.test(ESTIMATE_HELP));
  assert.equal(FULL_CLAUDE_ACTIONS.find(([k]) => k === 'match')[1], 'Claude match of 15 ingredients, with weights');
});
