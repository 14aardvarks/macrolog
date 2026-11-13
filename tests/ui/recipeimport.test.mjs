import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseIngredientLine, parseIngredientText, servingsFrom, isHeading, reviewDraft, reviewBody, rowText, blankRow,
  matchState, matchCountText, recipeSubText, nextUnmatched, selectableIds, toggleAll, toggleId, matchBatch, proposalText, matchWhat, importWhat,
  NOTE_MAX, NOTE_LABEL, NOTE_HINT, NOTE_EXAMPLES, RERUN_LABEL, noteCheck, canRerun, rerunInput, claudeRead,
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
  assert.deepEqual(parts('2-3 cloves garlic, minced'), [2.5, 'clove', 'garlic', 'minced']);
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
  assert.deepEqual(d.rows[0], { amount: '1 1/2', shown: '1 1/2', exact: 1.5, unit: 'cup', name: 'flour', note: '', text: '1 1/2 cups flour', pkgAmount: null, pkgUnit: null });
  assert.deepEqual(d.steps, ['Mix.', 'Fry.']);
  d.meals = ['breakfast'];
  d.rows.push(blankRow());  // an empty row is ignored
  assert.deepEqual(reviewBody(d).body, { name: 'Pancakes', servings: 4, meals: ['breakfast'],
    ingredients: [{ text: '1 1/2 cup flour', amount: 1.5, unit: 'cup', name: 'flour', note: null, pkg_amount: null, pkg_unit: null }], steps: ['Mix.', 'Fry.'] });
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
  assert.deepEqual(reviewBody(d).body.ingredients, [{ text: 'rice', amount: null, unit: null, name: 'rice', note: null, pkg_amount: null, pkg_unit: null }]);
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

test('an amount with no unit is a count, and package and fuzzy units stay units (issue #45)', () => {
  assert.deepEqual(parts('3 carrots'), [3, 'count', 'carrots', null]);
  assert.deepEqual(parts('2 cloves garlic'), [2, 'clove', 'garlic', null]);
  assert.deepEqual(parts('1 can black beans, drained'), [1, 'can', 'black beans', 'drained']);
  assert.deepEqual(parts('4 slices bread'), [4, 'slice', 'bread', null]);
  assert.deepEqual(parts('2 bunches cilantro'), [2, 'bunch', 'cilantro', null]);
  assert.deepEqual(parts('1 head of lettuce'), [1, 'head', 'lettuce', null]);
  assert.deepEqual(parts('3 Pinches salt'), [3, 'pinch', 'salt', null]);
  assert.deepEqual(parts('1 cup flour'), [1, 'cup', 'flour', null]);
  assert.deepEqual(parts('1 count egg'), [1, 'count', 'egg', null]);
  assert.deepEqual(parts('fresh basil'), [null, null, 'fresh basil', null]);  // no amount and no unit stays plain text
  assert.equal(parseIngredientLine('3 carrots').text, '3 carrots');
});

test('a line that says to taste or as needed has no amount or unit and keeps to taste in the note', () => {
  assert.deepEqual(parseIngredientLine('Salt to taste'), { text: 'Salt, to taste', amount: null, unit: null, name: 'Salt', note: 'to taste' });
  assert.deepEqual(parseIngredientLine('1 tsp salt, to taste'), { text: '1 tsp salt, to taste', amount: 1, unit: 'tsp', name: 'salt', note: 'to taste' });  // issue 47: a real amount stays
  assert.deepEqual(parseIngredientLine('2 pinches pepper to taste'), { text: '2 pinches pepper to taste', amount: 2, unit: 'pinch', name: 'pepper', note: 'to taste' });
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

test('issue 47: a real amount is never blanked by to taste or as needed, fractions and plural units parse', () => {
  const cases = [
    ['1 ½ tablespoons olive oil (more as needed, if not using nonstick pan)', [1.5, 'tbsp', 'olive oil', 'more as needed, if not using nonstick pan']],
    ['1 ½ cups flour', [1.5, 'cup', 'flour', null]],
    ['1½ cups flour', [1.5, 'cup', 'flour', null]],
    ['¾ tsp salt', [0.75, 'tsp', 'salt', null]],
    ['⅓ cup sugar', [1 / 3, 'cup', 'sugar', null]],
    ['⅔ cup milk', [2 / 3, 'cup', 'milk', null]],
    ['⅛ tsp nutmeg', [0.125, 'tsp', 'nutmeg', null]],
    ['¼ cup oil', [0.25, 'cup', 'oil', null]],
    ['1-1/2 cups sugar', [1.5, 'cup', 'sugar', null]],
    ['2-3 cloves garlic', [2.5, 'clove', 'garlic', null]],
    ['1/2 cup (120 ml) milk', [0.5, 'cup', 'milk', '120 ml']],
    ['1 tablespoon butter, melted (or more as needed)', [1, 'tbsp', 'butter', 'or more as needed, melted']],
    ['2 cups water as needed', [2, 'cup', 'water', 'as needed']],
    ['2 teaspoons salt, or to taste', [2, 'tsp', 'salt', 'or to taste']],
    ['3 ounces cheese', [3, 'oz', 'cheese', null]],
    ['1 pound beef', [1, 'lb', 'beef', null]],
    ['100 grams rice', [100, 'g', 'rice', null]],
    ['2 widgets', [2, 'count', 'widgets', null]],
    ['salt to taste', [null, null, 'salt', 'to taste']],
    ['pepper', [null, null, 'pepper', null]],
    ['olive oil, as needed', [null, null, 'olive oil', 'as needed']],
  ];
  for (const [line, want] of cases) {
    const got = parts(line);
    assert.equal(got.length, 4, line);
    got.forEach((v, i) => (typeof v === 'number' ? assert.ok(Math.abs(v - want[i]) < 1e-9, line) : assert.equal(v, want[i], line)));
  }
});

// ---------- Note For Claude and Rerun With Notes (issue #46) ----------

const READ = { recipe: { name: 'Pancakes', servings: 4, ingredients: [{ text: '1 cup flour', amount: 1, unit: 'cup', name: 'flour', note: null }], steps: ['Mix.'] },
  warnings: ['Claude is unsure.'], cost: 0.002 };

test('the note box wording and limits', () => {
  assert.equal(NOTE_LABEL, 'Note For Claude');
  assert.equal(RERUN_LABEL, 'Rerun With Notes');
  assert.equal(NOTE_MAX, 500);
  assert.equal(NOTE_HINT, 'Optional. Tell Claude how to read the recipe.');
  for (const e of ['amounts are in grams', 'ignore the sauce', 'split into two recipes']) assert.ok(NOTE_EXAMPLES.includes(e));
  assert.ok(!/[\u2014\u2013]/.test(NOTE_HINT + NOTE_EXAMPLES));
});

test('noteCheck folds spaces, allows 500 characters and refuses more or control characters', () => {
  assert.deepEqual(noteCheck('  amounts   are in grams '), { note: 'amounts are in grams' });
  assert.deepEqual(noteCheck(''), { note: '' });
  assert.deepEqual(noteCheck(null), { note: '' });
  assert.deepEqual(noteCheck('   '), { note: '' });
  assert.equal(noteCheck('n'.repeat(500)).note.length, 500);
  assert.match(noteCheck('n'.repeat(501)).error, /500 characters/);
  for (const bad of ['a\nb', 'a\tb', 'a\u0000b', 'a\u001bb', 'a\u007fb']) assert.match(noteCheck(bad).error, /control characters/);
});

test('only a recipe Claude read can be rerun', () => {
  assert.equal(canRerun(null), false);
  assert.equal(canRerun(reviewDraft(READ.recipe, { warnings: [] })), false);  // Split Lines Without Claude
  assert.equal(canRerun({ claude: true }), true);
});

test('the rerun input keeps the pasted text, photos, web address and previous note', () => {
  const files = [{ name: 'a.jpg' }, { name: 'b.jpg' }];
  const input = { kind: 'text', text: 'Pancakes\n1 cup flour', url: 'https://example.com/p', files, note: 'use grams' };
  const draft = { claude: true, source: 'photos' };
  const next = rerunInput(input, draft);
  assert.deepEqual(next, { kind: 'photos', text: 'Pancakes\n1 cup flour', url: 'https://example.com/p', files, note: 'use grams' });
  assert.equal(next.files, files);
  assert.equal(rerunInput(input, { claude: true }).kind, 'text');
  assert.equal(input.kind, 'text');  // the stored input is not changed by asking
});

test('claudeRead passes the checked note to the request and builds a Claude draft', async () => {
  const seen = [];
  const out = await claudeRead('url', '  ignore   the sauce ', async (n) => { seen.push(n); return READ; }, { photoFiles: [1] });
  assert.deepEqual(seen, ['ignore the sauce']);
  assert.equal(out.error, undefined);
  assert.equal(out.draft.claude, true);
  assert.equal(out.draft.source, 'url');
  assert.equal(out.draft.cost, 0.002);
  assert.deepEqual(out.draft.warnings, ['Claude is unsure.']);
  assert.deepEqual(out.draft.photoFiles, [1]);
  assert.equal(out.draft.rows[0].name, 'flour');
  assert.equal(canRerun(out.draft), true);
  const none = [];
  await claudeRead('text', '   ', async (n) => { none.push(n); return READ; });
  assert.deepEqual(none, ['']);  // an empty note is passed as nothing
});

test('claudeRead refuses a bad note without sending anything', async () => {
  let sent = 0;
  for (const bad of ['x'.repeat(501), 'a\nb']) {
    const out = await claudeRead('text', bad, async () => { sent++; return READ; });
    assert.ok(out.error);
    assert.equal(out.draft, undefined);
  }
  assert.equal(sent, 0);
});

test('a failed rerun returns no draft, so the previous review is kept exactly as edited', async () => {
  const flow = { input: { kind: 'text', text: 'x', note: '' }, draft: reviewDraft(READ.recipe, { claude: true, source: 'text' }) };
  flow.draft.name = 'My Pancakes';  // an edit made on the review screen
  flow.draft.rows[0].amount = '2';
  const before = flow.draft;
  const snapshot = JSON.stringify(before);
  const out = await claudeRead('text', 'grams', async () => { const e = new Error('Claude is busy. Try again soon.'); e.status = 502; throw e; });
  assert.equal(out.error, 'Claude is busy. Try again soon.');
  assert.equal(out.status, 502);
  assert.equal(out.draft, undefined);
  if (out.draft) flow.draft = out.draft;  // what the screen does: only a result replaces the draft
  assert.equal(flow.draft, before);
  assert.equal(JSON.stringify(flow.draft), snapshot);
  const ok = await claudeRead('text', 'grams', async () => READ);
  if (ok.draft) flow.draft = ok.draft;
  assert.notEqual(flow.draft, before);  // a success replaces it
  assert.equal(flow.draft.name, 'Pancakes');
});
