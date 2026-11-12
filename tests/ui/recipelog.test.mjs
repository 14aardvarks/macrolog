import test from 'node:test';
import assert from 'node:assert/strict';
import { isRecipeLog, recipeAmountText, entryAmountText, saveRecipeRows, tickedIds, scaledLog, partsText, REMOVE_RECIPE_CONFIRM,
  portionFraction, portionAmount } from '../../app/static/js/recipeimport.js';
import { buildTable } from '../../app/static/js/tablemodel.js';
import { groupByMeal, setAmountFormat } from '../../app/static/js/util.js';

const PORTIONS = [{ unit: 'serving', label: 'servings', whole: 4 }, { unit: 'pct', label: '% of recipe', whole: 100 },
  { unit: 'g', label: 'g', whole: 1200 }];
const parts = [
  { kind: 'food', id: 11, food_id: 1, name: 'Bread', amount: 1, unit: 'slice', meal: 'lunch', kcal: 90, carbs: 17, protein: 4, fat: 1.5, sodium: 170 },
  { kind: 'food', id: 12, food_id: 2, name: 'Peanut Butter', amount: 16, unit: 'g', meal: 'lunch', kcal: 95, carbs: 3.5, protein: 4, fat: 8, sodium: null },
];
const log = { kind: 'recipe', id: null, group_id: 5, name: 'Toast', amount: 1, unit: 'serving', fraction: 0.25, meal: 'lunch',
  food_id: null, source: null, portions: PORTIONS, parts, kcal: 185, carbs: 20.5, protein: 8, fat: 9.5, sodium: 170, calcium: null };
const apple = { kind: 'food', id: 13, food_id: 3, name: 'Apple', amount: 1, unit: 'piece', meal: 'lunch', kcal: 95, carbs: 25, protein: 0.5, fat: 0.3, sodium: 2 };

test('isRecipeLog tells a recipe log from a food entry', () => {
  assert.equal(isRecipeLog(log), true);
  assert.equal(isRecipeLog(apple), false);
  assert.equal(isRecipeLog({ id: 1 }), false);  // older replies have no kind
  assert.equal(isRecipeLog(null), false);
});

test('recipeAmountText names the portion of the recipe', () => {
  setAmountFormat('fraction');
  assert.equal(recipeAmountText(1, 'serving'), '1 serving');
  assert.equal(recipeAmountText(0.5, 'serving'), '1/2 serving');
  assert.equal(recipeAmountText(2, 'serving'), '2 servings');
  assert.equal(recipeAmountText(25, 'pct'), '25% of the recipe');
  assert.equal(recipeAmountText(250, 'g'), '250 g');
  assert.equal(recipeAmountText(1.5, 'cup'), '1 1/2 cup');
  assert.equal(recipeAmountText(8, 'floz'), '8 fl oz');
  setAmountFormat('decimal');
  assert.equal(recipeAmountText(0.5, 'serving'), '0.5 serving');
  setAmountFormat('fraction');
  assert.equal(entryAmountText(log), '1 serving');
  assert.equal(entryAmountText(apple), '1 piece');
});

test('saveRecipeRows: a recipe log is one row standing for its ingredient rows', () => {
  const gone = { ...apple, id: 14, food_id: null, name: 'Old food' };
  const rows = saveRecipeRows([log, apple, gone]);
  assert.deepEqual(rows.map((r) => [r.name, r.ids, r.text, r.recipe]), [['Toast', [11, 12], '1 serving', true], ['Apple', [13], '1 piece', false]]);
  assert.deepEqual(tickedIds(rows, [true, true]), [11, 12, 13]);
  assert.deepEqual(tickedIds(rows, [false, true]), [13]);
  assert.deepEqual(saveRecipeRows([{ ...log, parts: [{ ...parts[0], food_id: null }] }]), []);
  assert.deepEqual(saveRecipeRows(undefined), []);
});

test('scaledLog previews another portion; unknown stays null', () => {
  const half = scaledLog(log, 0.125);
  assert.equal(half.kcal, 92.5);
  assert.equal(half.fat, 4.75);
  assert.equal(half.sodium, 85);
  assert.equal(half.calcium, null);
  assert.equal(log.kcal, 185);  // not changed in place
  const r = portionFraction(log, '300', 'g');
  assert.equal(r.fraction, 0.25);
  assert.equal(scaledLog(log, r.fraction).kcal, 185);
  assert.equal(portionAmount(log, 0.125, 'pct'), 12.5);
});

test('a recipe log counts once in the meal groups and the table', () => {
  const g = groupByMeal([log, apple]);
  assert.equal(g.length, 1);
  assert.equal(g[0].kcal, 280);
  const t = buildTable([log, apple], { micros_shown: ['sodium'] });
  assert.equal(t.count, 2);
  assert.deepEqual(t.groups[0].rows.map((r) => r.entry.name), ['Toast', 'Apple']);
  assert.equal(t.totals[0], '280');
  assert.equal(t.groups[0].rows[0].cells[t.cols.findIndex((c) => c.key === 'sodium')], '170');
});

test('copy for a recipe log', () => {
  assert.equal(partsText(1), '1 ingredient');
  assert.equal(partsText(3), '3 ingredients');
  assert.ok(REMOVE_RECIPE_CONFIRM.startsWith('Remove This Recipe From Today? '));
  assert.ok(REMOVE_RECIPE_CONFIRM.endsWith('.') && !REMOVE_RECIPE_CONFIRM.includes('—'));
});
