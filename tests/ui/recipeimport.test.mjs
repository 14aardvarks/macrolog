import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseIngredientLine, parseIngredientText, servingsFrom, isHeading, reviewDraft, reviewBody, rowText, blankRow,
  matchState, matchCountText, recipeSubText, nextUnmatched, selectableIds, toggleAll, toggleId, matchBatch, proposalText, matchWhat, importWhat,
} from '../../app/static/js/recipeimport.js';

const parts = (line) => { const r = parseIngredientLine(line); return r && [r.amount, r.unit, r.name, r.note]; };

test('ingredient lines split into amount, unit, name and note', () => {
  assert.deepEqual(parts('1 1/2 cups all-purpose flour, sifted'), [1.5, 'cup', 'all-purpose flour', 'sifted']);
  assert.deepEqual(parts('2 eggs'), [2, null, 'eggs', null]);
  assert.deepEqual(parts('½ tsp salt'), [0.5, 'tsp', 'salt', null]);
  assert.deepEqual(parts('1½ Tbsp. olive oil'), [1.5, 'tbsp', 'olive oil', null]);
  assert.deepEqual(parts('2 T butter'), [2, 'tbsp', 'butter', null]);
  assert.deepEqual(parts('2 t vanilla'), [2, 'tsp', 'vanilla', null]);
  assert.deepEqual(parts('200g dark chocolate (70%)'), [200, 'g', 'dark chocolate', '70%']);
  assert.deepEqual(parts('2-3 cloves garlic, minced'), [2.5, 'clove', 'garlic', 'minced']);
  assert.deepEqual(parts('2 to 3 tomatoes'), [2.5, null, 'tomatoes', null]);
  assert.deepEqual(parts('2 tomatoes'), [2, null, 'tomatoes', null]);
  assert.deepEqual(parts('8 fl oz milk'), [8, 'floz', 'milk', null]);
  assert.deepEqual(parts('1 cup of sugar'), [1, 'cup', 'sugar', null]);
  assert.deepEqual(parts('1,5 kg potatoes'), [1.5, 'kg', 'potatoes', null]);
  assert.deepEqual(parts('Salt to taste'), [null, null, 'Salt', 'to taste']);
  assert.deepEqual(parts('- 3 large carrots'), [3, null, 'large carrots', null]);
  assert.deepEqual(parts('1. 2 cups rice'), [2, 'cup', 'rice', null]);
  assert.equal(parseIngredientLine('   '), null);
  assert.equal(parseIngredientLine('1 cup flour').text, '1 cup flour');
});

test('pasted text drops headings and finds servings', () => {
  assert.equal(servingsFrom('Serves 4'), 4);
  assert.equal(servingsFrom('Yield: 12 cookies'), 12);
  assert.equal(servingsFrom('2 cups flour'), null);
  assert.ok(isHeading('For the sauce:'));
  assert.ok(!isHeading('1 cup milk'));
  const r = parseIngredientText('Serves 6\n\nFor the dough:\n2 cups flour\n1 tsp salt\r\nWater, as needed');
  assert.equal(r.servings, 6);
  assert.deepEqual(r.ingredients.map((i) => i.name), ['flour', 'salt', 'Water']);
  assert.equal(r.ingredients[2].note, 'as needed');
});

test('review draft round trips into the import body', () => {
  const d = reviewDraft({ name: 'Pancakes', servings: 4, ingredients: [{ amount: 1.5, unit: 'cup', name: 'flour', note: null, text: '1 1/2 cups flour' }] });
  assert.deepEqual(d.rows[0], { amount: '1.5', unit: 'cup', name: 'flour', note: '', text: '1 1/2 cups flour' });
  d.meals = ['breakfast'];
  d.rows.push(blankRow());  // an empty row is ignored
  assert.deepEqual(reviewBody(d).body, { name: 'Pancakes', servings: 4, meals: ['breakfast'],
    ingredients: [{ text: '1.5 cup flour', amount: 1.5, unit: 'cup', name: 'flour', note: null }] });
  d.rows[0].amount = '1 1/2';
  d.rows[0].note = 'sifted';
  assert.equal(reviewBody(d).body.ingredients[0].amount, 1.5);
  assert.equal(rowText(d.rows[0]), '1.5 cup flour, sifted');
});

test('review validation', () => {
  const d = reviewDraft({ name: '', ingredients: [] });
  assert.match(reviewBody(d).error, /name/);
  d.name = 'X';
  assert.match(reviewBody(d).error, /ingredient/);
  d.rows = [{ ...blankRow(), amount: '2' }];
  assert.match(reviewBody(d).error, /needs a name/);
  d.rows = [{ ...blankRow(), amount: 'lots', name: 'rice' }];
  assert.match(reviewBody(d).error, /amount of rice/);
  d.rows = [{ ...blankRow(), name: 'rice' }];
  d.servings = '0';
  assert.match(reviewBody(d).error, /Servings/);
  d.servings = '';
  assert.deepEqual(reviewBody(d).body.ingredients, [{ text: 'rice', amount: null, unit: null, name: 'rice', note: null }]);
});

const items = [
  { id: 1, food: { name: 'Flour' }, skipped: false },
  { id: 2, food: null, skipped: false },
  { id: 3, food: null, skipped: true },
  { id: 4, food: null, skipped: false },
  { id: 5, food: { name: 'Egg' }, skipped: false },
];

test('match state and counts', () => {
  assert.deepEqual(items.map(matchState), ['matched', 'unmatched', 'skipped', 'unmatched', 'matched']);
  assert.equal(matchCountText({ matched: 3, needed: 8, skipped: 0 }), '3 of 8 matched');
  assert.equal(matchCountText({ matched: 2, needed: 4, skipped: 1 }), '2 of 4 matched, 1 skipped');
  assert.equal(recipeSubText({ complete: false, matched: 1, needed: 2, skipped: 0 }, '0'), '1 of 2 matched');
  assert.equal(recipeSubText({ complete: true, needed: 1, items: [{}, {}] }, '90'), '1 item - 90 kcal');
  assert.equal(recipeSubText({ complete: true, items: [{}, {}] }, '90'), '2 items - 90 kcal');
});

test('Save and Next picks the next unmatched row, wrapping, skipping skipped rows', () => {
  assert.equal(nextUnmatched(items, null), 1);
  assert.equal(nextUnmatched(items, 1), 3);
  assert.equal(nextUnmatched(items, 3), 1);
  assert.equal(nextUnmatched(items, 4), 1);
  assert.equal(nextUnmatched([{ id: 1, food: {}, skipped: false }, { id: 2, food: null, skipped: true }], 0), -1);
  assert.equal(nextUnmatched([], null), -1);
});

test('selection helpers', () => {
  assert.deepEqual(selectableIds(items), [1, 2, 4, 5]);
  assert.deepEqual(toggleAll(items, []), [2, 4]);
  assert.deepEqual(toggleAll(items, [2, 4]), []);
  assert.deepEqual(toggleAll(items, [1]), [2, 4]);
  assert.deepEqual(toggleId([2], 4), [2, 4]);
  assert.deepEqual(toggleId([2, 4], 2), [4]);
  const ids = Array.from({ length: 20 }, (_, i) => i + 1);
  const b = matchBatch(ids);
  assert.equal(b.send.length, 15);
  assert.deepEqual(b.rest, [16, 17, 18, 19, 20]);
});

test('proposal and notice wording', () => {
  assert.equal(proposalText({ kind: 'candidate', food: { name: 'Flour', brand: 'Acme' }, amount: 1.5, unit: 'cup' }), 'Flour (Acme), 1.5 cup');
  assert.equal(proposalText({ kind: 'none', food: null, note: 'Salt has no calories' }), 'Salt has no calories.');
  assert.match(proposalText({ kind: 'none', food: null, note: null }), /no match/);
  assert.equal(matchWhat(1), '1 ingredient with database candidates');
  assert.equal(importWhat('photos', 2), '2 photos of a recipe');
  assert.equal(importWhat('text', 120), 'your recipe text (120 characters)');
});
