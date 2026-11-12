import test from 'node:test';
import assert from 'node:assert/strict';
import {
  matchSnapshot, restoreBody, changedSince, nextUnmatched, notCounted, notMatchedText, notCountedText, saveChoice, canSaveWithout, unmatchedIds, pendingProposals, acceptAllText, servingSizeBody, yieldText,
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
  assert.deepEqual(restoreBody(base, meal([un(1), ok(2), un(3), ok(4, { skipped: true })])), { remove: [], add: [], items: [], meal: null });
  assert.equal(changedSince(base, meal([un(1), ok(2), un(3), ok(4, { skipped: true })])), false);
});

test('the snapshot is a copy, and a Check Amount row restores with check', () => {
  const m = meal([ok(1, { check: true })], { yield: { amount: 1, unit: 'l' } });
  const base = matchSnapshot(m);
  m.yield.amount = 2;
  m.items[0].check = false;
  assert.deepEqual(restoreBody(base, m), { remove: [], add: [], items: [{ id: 1, food_id: 9, amount: 2, unit: 'cup', check: true, skipped: false }], meal: { yield: { amount: 1, unit: 'l' } } });
});

test('nextUnmatched wraps round and finds unmatched and Check Amount rows', () => {
  const items = [ok(1), un(2), ok(3, { check: true }), { ...un(4), skipped: true }, ok(5)];
  assert.equal(nextUnmatched(items, -1), 1);
  assert.equal(nextUnmatched(items, 1), 2);
  assert.equal(nextUnmatched(items, 2), 1);
  assert.equal(nextUnmatched([ok(1), ok(2)], -1), -1);
});

test('Save asks only while rows are not matched, and the texts are sentences', () => {
  const m = meal([ok(1), un(2), { ...un(3), skipped: true }, ok(4, { check: true })], { matched: 1 });
  assert.equal(notCounted(m), 3);
  assert.deepEqual(saveChoice(m), { ask: true, n: 3 });
  assert.deepEqual(saveChoice(meal([ok(1), ok(2)], { matched: 2 })), { ask: false, n: 0 });
  assert.equal(notMatchedText(3), '3 ingredients are not matched.');
  assert.equal(notMatchedText(1), '1 ingredient is not matched.');
  assert.equal(notCountedText(5), '5 ingredients are not counted.');
  assert.equal(canSaveWithout(m), true);
  assert.equal(canSaveWithout(meal([un(1)], { matched: 0 })), false);
});

test('only unmatched rows are pre-ticked', () => {
  assert.deepEqual(unmatchedIds([un(1), ok(2), ok(3, { check: true }), { ...un(4), skipped: true }, un(5)]), [1, 5]);
});

test('Accept All counts proposals with a food on rows that are not skipped', () => {
  const items = [un(1), un(2), { ...un(3), skipped: true }, un(4)];
  const props = { 1: { food: F }, 2: { kind: 'none', food: null }, 3: { food: F }, 4: { food: { name: 'Est' } } };
  assert.deepEqual(pendingProposals(items, props).map((x) => x.item.id), [1, 4]);
  assert.equal(acceptAllText(6), 'Accept 6 Suggested Matches');
  assert.equal(acceptAllText(1), 'Accept 1 Suggested Match');
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

// ---------- Auto-Match After Import ----------
import {
  autoMatchOn, autoMatchIds, autoMatchResult, autoMatchPlan, autoClaudeBatch, AUTO_CLAUDE_OFF, AUTO_CLAUDE_FAILED, AUTO_CLAUDE_CANCELLED, rateLimitNote, RATE_LIMIT_NOTE, AUTO_MATCH_LOADING, AUTO_MATCH_FAILED,
} from '../../app/static/js/recipeimport.js';
import { AUTO_MATCHES, autoMatch, DEFAULT_DISPLAY, sentence } from '../../app/static/js/util.js';

const amRow = (id, over) => ({ id, food: null, food_id: null, skipped: false, check: false, src: { text: 'r' + id }, ...over });

test('Auto-Match After Import: Search by default, four choices, anything odd means Search', () => {
  assert.deepEqual(AUTO_MATCHES.map((o) => o.value), ['search', 'claude', 'search_claude', 'off']);
  assert.deepEqual(AUTO_MATCHES.map((o) => o.label), ['Search', 'Claude', 'Search Then Claude', 'Off']);
  assert.equal(DEFAULT_DISPLAY.auto_match, 'search');
  for (const v of ['off', 'claude', 'search_claude', 'search']) assert.equal(autoMatch(v), v);
  for (const v of [undefined, null, '', 'OFF', 'Claude', 'bogus']) assert.equal(autoMatch(v), 'search');
  for (const v of ['search', 'claude', 'search_claude']) assert.equal(autoMatchOn({ auto_match: v }), true);
  assert.equal(autoMatchOn({ auto_match: 'off' }), false);
  assert.equal(autoMatchOn({}), true);
  assert.equal(autoMatchOn(undefined), true);
});

test('auto-match plan: what runs for each setting, with and without Claude', () => {
  assert.deepEqual(autoMatchPlan('search', true), { search: true, claude: false, note: '' });
  assert.deepEqual(autoMatchPlan('search', false), { search: true, claude: false, note: '' });
  assert.deepEqual(autoMatchPlan('off', true), { search: false, claude: false, note: '' });
  assert.deepEqual(autoMatchPlan('claude', true), { search: false, claude: true, note: '' });
  assert.deepEqual(autoMatchPlan('search_claude', true), { search: true, claude: true, note: '' });
  // Claude not set up, or the recipe switch is off: Search only, with a short note
  assert.deepEqual(autoMatchPlan('claude', false), { search: true, claude: false, note: AUTO_CLAUDE_OFF });
  assert.deepEqual(autoMatchPlan('search_claude', false), { search: true, claude: false, note: AUTO_CLAUDE_OFF });
  assert.deepEqual(autoMatchPlan(undefined, true), { search: true, claude: false, note: '' });
  for (const t of [AUTO_CLAUDE_OFF, AUTO_CLAUDE_FAILED, AUTO_CLAUDE_CANCELLED]) assert.ok(/\.$/.test(t) && !t.includes('\u2014'));
});

test('auto-match Claude rows: unmatched rows without a food proposal, up to the Claude cap of 15', () => {
  const items = [amRow(1), amRow(2), amRow(3, { food: { id: 9 }, food_id: 9 }), amRow(4, { skipped: true }), amRow(5), amRow(6)];
  assert.deepEqual(autoClaudeBatch(items, {}).send, [1, 2, 5, 6]);  // Claude only: nothing proposed yet
  const props = { 1: { item_id: 1, food: { name: 'a' } }, 2: { item_id: 2, food: null }, 6: { item_id: 6, food: { name: 'b' } } };
  assert.deepEqual(autoClaudeBatch(items, props), { send: [2, 5], rest: [] });  // Search Then Claude: rows with no proposal only
  assert.deepEqual(autoClaudeBatch(items, undefined).send, [1, 2, 5, 6]);
  const many = Array.from({ length: 20 }, (_, i) => amRow(i + 1));
  const b = autoClaudeBatch(many, {});
  assert.equal(b.send.length, 15);
  assert.deepEqual(b.rest, [16, 17, 18, 19, 20]);
  assert.deepEqual(autoClaudeBatch([], {}), { send: [], rest: [] });
});

test('auto-match searches unmatched rows only, up to the Search cap of 40', () => {
  const items = [amRow(1), amRow(2, { food: { id: 9 }, food_id: 9 }), amRow(3, { skipped: true }), amRow(4, { food: { id: 9 }, check: true }), amRow(5)];
  assert.deepEqual(autoMatchIds(items), [1, 5]);
  const many = Array.from({ length: 45 }, (_, i) => amRow(i + 1));
  assert.equal(autoMatchIds(many).length, 40);
  assert.deepEqual(autoMatchIds([]), []);
});

test('auto-match answers for rows matched or skipped meanwhile are dropped, and only rows with a food are un-ticked', () => {
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
  assert.ok(!AUTO_MATCH_FAILED.includes('—') && /\.$/.test(AUTO_MATCH_FAILED));
});
