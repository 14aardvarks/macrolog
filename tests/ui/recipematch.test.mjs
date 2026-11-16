import test from 'node:test';
import assert from 'node:assert/strict';
import {
  notCounted, notCountedText, unmatchedIds, servingSizeBody, yieldText,
  portionUnits, portionFraction, portionItems, portionNote, portionAmount, photoPick, PHOTOS_TEXT, MAX_PHOTOS,
} from '../../app/static/js/recipeimport.js';
import { setAmountFormat } from '../../app/static/js/util.js';

const F = { id: 9, name: 'Oats' };
const un = (id) => ({ id, food: null, food_id: null, amount: null, unit: null, skipped: false, check: false });
const ok = (id, over) => ({ id, food: F, food_id: 9, amount: 2, unit: 'cup', skipped: false, check: false, ...over });
const meal = (items, over) => ({ id: 1, servings: 2, yield: null, items, ...over });

test('not counted rows and the quiet sentence', () => {
  const m = meal([ok(1), un(2), { ...un(3), skipped: true }, ok(4, { check: true })], { matched: 1 });
  assert.equal(notCounted(m), 3);
  assert.equal(notCountedText(5), '5 ingredients are not counted.');
});

test('unmatchedIds lists rows with no food that are not skipped', () => {
  assert.deepEqual(unmatchedIds([un(1), ok(2), ok(3, { check: true }), { ...un(4), skipped: true }, un(5)]), [1, 5]);
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
  ok(3, { amount: 300, unit: 'g' }), un(4), ok(5, { check: true })], ...over });

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

test('portionItems scales matched rows, not skipped or Check Amount ones', () => {
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

// ---------- Match and Match With Claude (issue #56; Auto-Match After Import is gone) ----------
import {
  autoMatchResult, AUTO_CLAUDE_FAILED, rateLimitNote, RATE_LIMIT_NOTE, AUTO_MATCH_LOADING, AUTO_MATCH_FAILED,
} from '../../app/static/js/recipeimport.js';
import * as UTIL from '../../app/static/js/util.js';
import * as IMPORT from '../../app/static/js/recipeimport.js';
const { DEFAULT_DISPLAY, sentence } = UTIL;

const amRow = (id, over) => ({ id, food: null, food_id: null, skipped: false, check: false, src: { text: 'r' + id }, ...over });

test('the Auto-Match After Import setting and its helpers are gone', () => {
  assert.ok(!('auto_match' in DEFAULT_DISPLAY));
  for (const k of ['AUTO_MATCHES', 'autoMatch', 'effectiveAutoMatch']) assert.ok(!(k in UTIL), k);
  for (const k of ['autoMatchOn', 'autoMatchPlan', 'autoMatchIds', 'autoClaudeBatch', 'claudeOffNote', 'acceptAllText', 'previousCountText', 'matchDoneText']) assert.ok(!(k in IMPORT), k);
});

test('auto-match answers for rows matched or skipped meanwhile are dropped, and found lists rows that got a food', () => {
  const items = [amRow(1), amRow(2), amRow(3, { food: { id: 9 }, food_id: 9 }), amRow(4, { skipped: true }), amRow(5)];
  const proposals = [{ item_id: 1, food: { id: 7 } }, { item_id: 2, food: null }, { item_id: 3, food: { id: 7 } }, { item_id: 4, food: { id: 7 } }, { item_id: 5, food: { id: 8 } }];
  const r = autoMatchResult(items, proposals);
  assert.deepEqual(r.fresh.map((p) => p.item_id), [1, 2, 5]);
  assert.deepEqual(r.found, [1, 5]);
  assert.deepEqual(autoMatchResult(items, undefined), { fresh: [], found: [] });
});

test('the USDA rate limit note is one quiet sentence, only when rows were skipped', () => {
  assert.equal(RATE_LIMIT_NOTE, 'USDA lookup limit reached. Rows below were not searched.');
  assert.equal(sentence(RATE_LIMIT_NOTE), RATE_LIMIT_NOTE);
  assert.equal(rateLimitNote({ rate_limited: true, proposals: [] }), RATE_LIMIT_NOTE);
  assert.equal(rateLimitNote({ proposals: [{ skipped: true }] }), RATE_LIMIT_NOTE);
  assert.equal(rateLimitNote({ rate_limited: false, proposals: [{ item_id: 1 }] }), '');
  assert.equal(rateLimitNote(null), '');
});

test('loading and failure texts follow the house style', () => {
  assert.equal(AUTO_MATCH_LOADING, 'Finding Matches...');
  for (const t of [AUTO_MATCH_FAILED, AUTO_CLAUDE_FAILED]) assert.ok(!t.includes('\u2014') && !t.includes(':') && /\.$/.test(t) && !/Match All/.test(t));
});
