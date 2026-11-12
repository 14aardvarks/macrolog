import test from 'node:test';
import assert from 'node:assert/strict';
import {
  matchSnapshot, restoreBody, changedSince, nextStep, pendingProposals, acceptAllText, skipAllIds, servingSizeBody, yieldText,
  portionUnits, portionFraction, portionItems, portionNote, portionAmount, photoPick, PHOTOS_TEXT, MAX_PHOTOS,
} from '../../app/static/js/recipeimport.js';
import { setAmountFormat } from '../../app/static/js/util.js';

const F = { id: 9, name: 'Oats' };
const un = (id) => ({ id, food: null, food_id: null, amount: null, unit: null, skipped: false, check: false });
const ok = (id, over) => ({ id, food: F, food_id: 9, amount: 2, unit: 'cup', skipped: false, check: false, ...over });
const meal = (items, over) => ({ id: 1, servings: 2, yield: null, items, ...over });

test('restoreBody writes back only the rows and sizes that changed since the last save', () => {
  const base = matchSnapshot(meal([un(1), ok(2), un(3), ok(4, { skipped: true })]));
  const now = meal([ok(1), ok(2, { amount: 3 }), un(3, ), ok(4)], { servings: 4, yield: { amount: 900, unit: 'g' } });
  const r = restoreBody(base, now);
  assert.deepEqual(r.items, [
    { id: 1, food_id: null, skipped: false },
    { id: 2, food_id: 9, amount: 2, unit: 'cup', check: false, skipped: false },
    { id: 4, food_id: 9, amount: 2, unit: 'cup', check: false, skipped: true },
  ]);
  assert.deepEqual(r.meal, { servings: 2, yield: null });
  assert.equal(changedSince(base, now), true);
  assert.deepEqual(restoreBody(base, meal([un(1), ok(2), un(3), ok(4, { skipped: true })])), { items: [], meal: null });
  assert.equal(changedSince(base, meal([un(1), ok(2), un(3), ok(4, { skipped: true })])), false);
});

test('the snapshot is a copy, and a Check Amount row restores with check', () => {
  const m = meal([ok(1, { check: true })], { yield: { amount: 1, unit: 'l' } });
  const base = matchSnapshot(m);
  m.yield.amount = 2;
  m.items[0].check = false;
  assert.deepEqual(restoreBody(base, m), { items: [{ id: 1, food_id: 9, amount: 2, unit: 'cup', check: true, skipped: false }], meal: { yield: { amount: 1, unit: 'l' } } });
});

test('nextStep moves to the next open row and is Done on the last one', () => {
  const items = [ok(1), un(2), ok(3, { check: true }), un(4, ), ok(5)];
  items[3].skipped = true;
  assert.deepEqual(nextStep(items, -1), { done: false, index: 1 });
  assert.deepEqual(nextStep(items, 1), { done: false, index: 2 });
  assert.deepEqual(nextStep(items, 2), { done: false, index: 1 });
  assert.deepEqual(nextStep([ok(1), un(2)], 1), { done: true, index: -1 });
  assert.deepEqual(nextStep([ok(1), ok(2)], -1), { done: true, index: -1 });
});

test('Accept All counts proposals with a food on rows that are not skipped', () => {
  const items = [un(1), un(2), { ...un(3), skipped: true }, un(4)];
  const props = { 1: { food: F }, 2: { kind: 'none', food: null }, 3: { food: F }, 4: { food: { name: 'Est' } } };
  assert.deepEqual(pendingProposals(items, props).map((x) => x.item.id), [1, 4]);
  assert.equal(acceptAllText(6), 'Accept 6 Suggested Matches');
  assert.equal(acceptAllText(1), 'Accept 1 Suggested Match');
});

test('Skip All takes only unmatched rows', () => {
  assert.deepEqual(skipAllIds([un(1), ok(2), ok(3, { check: true }), { ...un(4), skipped: true }, un(5)]), [1, 5]);
});

test('servingSizeBody validates servings and the optional yield', () => {
  assert.deepEqual(servingSizeBody('4', '', 'g'), { body: { servings: 4, yield: null } });
  assert.deepEqual(servingSizeBody('1 1/2', '1,5', 'l'), { body: { servings: 1.5, yield: { amount: 1.5, unit: 'l' } } });
  assert.match(servingSizeBody('0', '', 'g').error, /Servings/);
  assert.match(servingSizeBody('2', 'lots', 'g').error, /yield/);
  assert.match(servingSizeBody('2', '0', 'g').error, /yield/);
  assert.match(servingSizeBody('2', '5', 'slice').error, /unit/);
});

test('yieldText', () => {
  setAmountFormat('fraction');
  assert.equal(yieldText({ amount: 1200, unit: 'g' }), '1200 g');
  assert.equal(yieldText({ amount: 1.5, unit: 'cup' }), '1 1/2 cup');
  assert.equal(yieldText({ amount: 2, unit: 'floz' }), '2 fl oz');
  assert.equal(yieldText(null), '');
});

const PORTIONS = [{ unit: 'serving', label: 'servings', whole: 4 }, { unit: 'pct', label: '% of recipe', whole: 100 },
  { unit: 'g', label: 'g', whole: 1200 }, { unit: 'oz', label: 'oz', whole: 42.328789 }];
const logMeal = (over) => ({ servings: 4, portions: PORTIONS, items: [ok(1, { amount: 2, unit: 'cup' }), ok(2, { amount: 100, unit: 'g', skipped: true }),
  ok(3, { amount: 300, unit: 'g' }), un(4)], ...over });

test('portionFraction turns servings, percent and yield units into a share of the recipe', () => {
  assert.equal(portionFraction(logMeal(), '1', 'serving').fraction, 0.25);
  assert.equal(portionFraction(logMeal(), '50', 'pct').fraction, 0.5);
  assert.equal(portionFraction(logMeal(), '300', 'g').fraction, 0.25);
  assert.equal(portionFraction(logMeal(), 1, 'serving').amount, 1);
  assert.match(portionFraction(logMeal(), '0', 'serving').error, /above zero/);
  assert.match(portionFraction(logMeal(), '1', 'cup').error, /above zero/);
  assert.match(portionFraction(logMeal(), '401', 'serving').error, /100 times/);
  // an older reply without portions still has servings and percent
  assert.deepEqual(portionUnits({ servings: null }).map((p) => [p.unit, p.whole]), [['serving', 1], ['pct', 100]]);
});

test('portionItems scales matched, not skipped rows', () => {
  assert.deepEqual(portionItems(logMeal(), 0.25).map((i) => [i.id, i.amount]), [[1, 0.5], [3, 75]]);
  assert.deepEqual(portionItems(logMeal(), 1 / 3).map((i) => i.amount), [0.6667, 100]);
});

test('portionNote says what the checklist amounts are for', () => {
  setAmountFormat('fraction');
  assert.equal(portionNote(logMeal(), 1, 'serving'), 'Amounts are for 1 of 4 servings.');
  assert.equal(portionNote(logMeal(), 25, 'pct'), 'Amounts are for 25% of the recipe.');
  assert.equal(portionNote(logMeal(), 100, 'pct'), 'Amounts are for the whole recipe.');
  assert.equal(portionNote(logMeal(), 250, 'g'), 'Amounts are for 250 g of 1200 g.');
  assert.equal(portionNote(logMeal({ servings: 1, portions: null }), 1, 'serving'), '');
});

test('photoPick keeps at most 3 photos and says so', () => {
  assert.equal(MAX_PHOTOS, 3);
  assert.match(PHOTOS_TEXT, /^Choose up to 3 photos/);
  assert.deepEqual(photoPick(['a', 'b']), { files: ['a', 'b'], warning: '' });
  const r = photoPick(['a', 'b', 'c', 'd', 'e']);
  assert.deepEqual(r.files, ['a', 'b', 'c']);
  assert.equal(r.warning, 'You chose 5 photos. Choose up to 3. Only the first 3 will be sent.');
});

test('portionAmount converts a share into a unit, rounded for the box', () => {
  assert.equal(portionAmount(logMeal(), 100 / 522, 'pct'), 19.2);
  assert.equal(portionAmount(logMeal(), 0.25, 'g'), 300);
  assert.equal(portionAmount(logMeal(), 0.25, 'oz'), 10.582);
  assert.equal(portionAmount(logMeal(), 0.25, 'serving'), 1);
  assert.equal(portionAmount(logMeal(), 0.25, 'cup'), null);
});
