import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseIngredientLine, parseIngredientText, servingsFrom, isHeading, reviewDraft, reviewBody, rowText, blankRow,
  matchState, matchCountText, recipeSubText, nextUnmatched, selectableIds, toggleAll, toggleId, matchBatch, proposalText, matchWhat, importWhat,
} from '../../app/static/js/recipeimport.js';

const parts = (line) => { const r = parseIngredientLine(line); return r && [r.amount, r.unit, r.name, r.note]; };

test('ingredient lines split into amount, unit, name and note', () => {
  assert.deepEqual(parts('1 1/2 cups all-purpose flour, sifted'), [1.5, 'cup', 'all-purpose flour', 'sifted']);
  assert.deepEqual(parts('2 eggs'), [2, 'count', 'eggs', null]);
  assert.deepEqual(parts('½ tsp salt'), [0.5, 'tsp', 'salt', null]);
  assert.deepEqual(parts('1½ Tbsp. olive oil'), [1.5, 'tbsp', 'olive oil', null]);
  assert.deepEqual(parts('2 T butter'), [2, 'tbsp', 'butter', null]);
  assert.deepEqual(parts('2 t vanilla'), [2, 'tsp', 'vanilla', null]);
  assert.deepEqual(parts('200g dark chocolate (70%)'), [200, 'g', 'dark chocolate', '70%']);
  assert.deepEqual(parts('2-3 cloves garlic, minced'), [2.5, 'count', 'garlic cloves', 'minced']);
  assert.deepEqual(parts('2 to 3 tomatoes'), [2.5, 'count', 'tomatoes', null]);
  assert.deepEqual(parts('2 tomatoes'), [2, 'count', 'tomatoes', null]);
  assert.deepEqual(parts('8 fl oz milk'), [8, 'floz', 'milk', null]);
  assert.deepEqual(parts('1 cup of sugar'), [1, 'cup', 'sugar', null]);
  assert.deepEqual(parts('1,5 kg potatoes'), [1.5, 'kg', 'potatoes', null]);
  assert.deepEqual(parts('Salt to taste'), [null, null, 'Salt', 'to taste']);
  assert.deepEqual(parts('- 3 large carrots'), [3, 'count', 'large carrots', null]);
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

test('review draft keeps an odd imported amount until the box is edited', () => {
  const d = reviewDraft({ name: 'X', servings: 2.4, ingredients: [{ amount: 0.4, unit: 'cup', name: 'oats', note: null, text: '' }] });
  assert.equal(d.rows[0].amount, '3/8');
  assert.equal(reviewBody(d).body.ingredients[0].amount, 0.4);
  d.rows[0].amount = '1/2';
  assert.equal(reviewBody(d).body.ingredients[0].amount, 0.5);
  assert.equal(reviewBody(d).body.servings, 2.4);
});

test('review draft round trips into the import body', () => {
  const d = reviewDraft({ name: 'Pancakes', servings: 4, ingredients: [{ amount: 1.5, unit: 'cup', name: 'flour', note: null, text: '1 1/2 cups flour' }],
    steps: ['Mix.', 5, 'Fry.'] });
  assert.deepEqual(d.rows[0], { amount: '1 1/2', shown: '1 1/2', exact: 1.5, unit: 'cup', name: 'flour', note: '', text: '1 1/2 cups flour' });
  assert.deepEqual(d.steps, ['Mix.', 'Fry.']);
  d.meals = ['breakfast'];
  d.rows.push(blankRow());  // an empty row is ignored
  assert.deepEqual(reviewBody(d).body, { name: 'Pancakes', servings: 4, meals: ['breakfast'],
    ingredients: [{ text: '1 1/2 cup flour', amount: 1.5, unit: 'cup', name: 'flour', note: null }], steps: ['Mix.', 'Fry.'] });
  d.rows[0].amount = '1.5';
  d.rows[0].note = 'sifted';
  assert.equal(reviewBody(d).body.ingredients[0].amount, 1.5);
  assert.equal(rowText(d.rows[0]), '1 1/2 cup flour, sifted');
  d.rows[0].unit = 'g';
  d.rows[0].amount = '28.5';
  assert.equal(rowText(d.rows[0]), '28.5 g flour, sifted');
  d.steps = new Array(61).fill('Stir.');
  assert.match(reviewBody(d).error, /at most 60 steps/);
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
  const withCheck = [{ id: 1, food: {}, skipped: false }, { id: 2, food: {}, check: true, skipped: false }];
  assert.equal(matchState(withCheck[1]), 'check');
  assert.equal(nextUnmatched(withCheck, 0), 1);
  assert.equal(matchCountText({ matched: 1, needed: 2, skipped: 1, checks: 1 }), '1 of 2 matched, 1 to check, 1 skipped');
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
  assert.equal(proposalText({ kind: 'candidate', food: { name: 'Flour', brand: 'Acme' }, amount: 1.5, unit: 'cup' }), 'Flour (Acme), 1 1/2 cup');
  assert.equal(proposalText({ kind: 'candidate', food: { name: 'Flour' }, amount: 1.5, unit: 'cup', grams: 187.5 }), 'Flour, 1 1/2 cup, 188 g');
  assert.equal(proposalText({ kind: 'estimate', food: { name: 'Flour' }, amount: 30, unit: 'g', grams: null, check: true }), 'Flour, 30 g (check the amount)');
  assert.equal(proposalText({ kind: 'none', food: null, note: 'Salt has no calories' }), 'Salt has no calories.');
  assert.match(proposalText({ kind: 'none', food: null, note: null }), /no match/);
  assert.equal(matchWhat(1), '1 ingredient with database candidates');
  assert.equal(importWhat('photos', 2), '2 photos of a recipe');
  assert.equal(importWhat('text', 120), 'your recipe text (120 characters)');
});

// ---------- Recipes tab ----------
import { tagsText, servingsText, recipeListSub, perServingText, logAmountText } from '../../app/static/js/recipeimport.js';

const F = { id: 9, name: 'Oats' };
const tabMeal = (over) => ({ id: 1, name: 'Porridge', servings: 4, meals: ['dinner', 'breakfast'], complete: true, matched: 3, needed: 3, skipped: 1,
  per_serving: { kcal: 250.4, carbs: 40, protein: 8.6, fat: null },
  items: [{ food: F, food_id: 9, amount: 2, unit: 'cup' }, { food: F, food_id: 9, amount: 1, unit: 'g', skipped: true },
    { food: F, food_id: 10, amount: 100, unit: 'g' }, { food: F, food_id: 11, amount: 3, unit: 'tbsp' }], ...over });

test('tagsText keeps meal order and says Untagged', () => {
  assert.equal(tagsText(['dinner', 'breakfast']), 'Breakfast, Dinner');
  assert.equal(tagsText([]), 'Untagged');
  assert.equal(tagsText(undefined), 'Untagged');
});

test('servingsText', () => {
  assert.equal(servingsText({ servings: 4 }), 'Makes 4 servings');
  assert.equal(servingsText({ servings: 1 }), 'Makes 1 serving');
  assert.equal(servingsText({ servings: null }), 'Makes 1 serving');
});

test('recipeListSub shows matching progress for partial recipes', () => {
  assert.equal(recipeListSub(tabMeal({ complete: false, matched: 3, needed: 8, skipped: 0, meals: [] }), '0'), '3 of 8 matched · Makes 4 servings · Untagged');
  assert.equal(recipeListSub(tabMeal(), '1000'), '3 items - 1000 kcal · Makes 4 servings · Breakfast, Dinner');
});

test('perServingText and logAmountText', () => {
  assert.equal(perServingText(tabMeal(), (v) => String(Math.round(v))), '250 kcal, 40 g carbs, 9 g protein, 0 g fat');
  assert.equal(logAmountText(1, 4), 'Amounts are for 1 of 4 servings.');
  assert.equal(logAmountText(2, 1), 'Amounts are for 2 servings.');
  assert.equal(logAmountText(1, 1), '');
});

test('an amount with no unit is a count, and a unit word the server does not know joins the name', () => {
  assert.deepEqual(parts('3 carrots'), [3, 'count', 'carrots', null]);
  assert.deepEqual(parts('2 cloves garlic'), [2, 'count', 'garlic cloves', null]);
  assert.deepEqual(parts('1 can black beans, drained'), [1, 'count', 'black beans can', 'drained']);
  assert.deepEqual(parts('4 slices bread'), [4, 'count', 'bread slices', null]);
  assert.deepEqual(parts('2 cloves garlic cloves'), [2, 'count', 'garlic cloves', null]);  // the word is not added twice
  assert.deepEqual(parts('1 cup flour'), [1, 'cup', 'flour', null]);
  assert.deepEqual(parts('1 count egg'), [1, 'count', 'egg', null]);
  assert.deepEqual(parts('fresh basil'), [null, null, 'fresh basil', null]);  // no amount and no unit stays plain text
  assert.equal(parseIngredientLine('3 carrots').text, '3 carrots');
});

test('a line that says to taste or as needed has no amount or unit and keeps to taste in the note', () => {
  assert.deepEqual(parseIngredientLine('Salt to taste'), { text: 'Salt, to taste', amount: null, unit: null, name: 'Salt', note: 'to taste' });
  assert.deepEqual(parseIngredientLine('1 tsp salt, to taste'), { text: 'salt, to taste', amount: null, unit: null, name: 'salt', note: 'to taste' });
  assert.deepEqual(parseIngredientLine('2 pinches pepper to taste'), { text: 'pepper, to taste', amount: null, unit: null, name: 'pepper', note: 'to taste' });
  assert.deepEqual(parseIngredientLine('Black pepper, as needed'), { text: 'Black pepper, as needed', amount: null, unit: null, name: 'Black pepper', note: 'as needed' });
  assert.deepEqual(parseIngredientLine('Water (as needed), cold'), { text: 'Water, as needed, cold', amount: null, unit: null, name: 'Water', note: 'as needed, cold' });
  const r = parseIngredientText('2 eggs\nSalt to taste');
  assert.deepEqual(r.ingredients.map((i) => [i.amount, i.unit, i.name, i.note]), [[2, 'count', 'eggs', null], [null, null, 'Salt', 'to taste']]);
});

test('the review body makes an amount with no unit a count and leaves a to taste line blank', () => {
  const d = reviewDraft({ name: 'Soup', ingredients: [{ text: '3 carrots', amount: 3, unit: 'count', name: 'carrots', note: null }, { text: 'salt, to taste', amount: null, unit: null, name: 'salt', note: 'to taste' }] });
  const b = reviewBody(d).body.ingredients;
  assert.deepEqual(b.map((i) => [i.text, i.amount, i.unit, i.note]), [['3 carrots', 3, 'count', null], ['salt, to taste', null, null, 'to taste']]);
});
