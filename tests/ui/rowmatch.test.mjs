import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ROW_STATES, rowState, rowActions, ACTION_LABELS, rowChip, rowLine, foodText, MATCH_ALL_MODES, searchIds, matchAllPlan, claudeIds, moreText,
  reviewOrder, reviewNext, reviewPos, lineOf, searchStart, topResults, SEARCH_RESULTS, matchedLine, restoreRowBody,
} from '../../app/static/js/rowmatch.js';
import { AUTO_CLAUDE_OFF } from '../../app/static/js/recipeimport.js';
import { setAmountFormat, sentence } from '../../app/static/js/util.js';

setAmountFormat('fraction');
const F = { id: 9, name: 'Butter, salted', source: 'fdc' };
const src = (name, amount, unit, note) => ({ text: [amount, unit, name].filter(Boolean).join(' '), amount, unit, name, note: note || null });
const un = (id, over) => ({ id, food: null, food_id: null, amount: null, unit: null, skipped: false, check: false, src: src('row ' + id, 1, 'cup'), ...over });
const ok = (id, over) => ({ id, food: F, food_id: 9, amount: 1, unit: 'tbsp', skipped: false, check: false, src: src('butter', 1, 'tbsp'), ...over });
const sug = (id, over) => ({ item_id: id, food: F, method: 'search', amount: 1, unit: 'tbsp', ...over });

test('row state machine: unmatched, suggested, accepted, check and skipped come from the row and its suggestion', () => {
  assert.deepEqual(ROW_STATES, ['unmatched', 'suggested', 'accepted', 'check', 'skipped']);
  assert.equal(rowState(un(1)), 'unmatched');
  assert.equal(rowState(un(1), sug(1)), 'suggested');                 // + found a food
  assert.equal(rowState(un(1), { item_id: 1, food: null }), 'unmatched');  // + found nothing: still unmatched
  assert.equal(rowState(ok(1)), 'accepted');                          // Accept saved it
  assert.equal(rowState(ok(1), sug(1)), 'accepted');                  // a stale suggestion never hides a match
  assert.equal(rowState(ok(1, { check: true })), 'check');
  assert.equal(rowState(un(1, { skipped: true }), sug(1)), 'skipped');
  assert.equal(rowState(ok(1, { skipped: true })), 'skipped');
  assert.equal(rowState(null), 'unmatched');
});

test('each state shows one primary action set and puts the rest in the menu', () => {
  assert.deepEqual(rowActions('unmatched', { aiOn: false }), { primary: ['match'], menu: ['change', 'find', 'skip', 'remove'] });
  assert.deepEqual(rowActions('unmatched', { aiOn: true }).primary, ['match', 'claude']);
  assert.deepEqual(rowActions('suggested', { aiOn: true }), { primary: ['accept', 'change'], menu: ['claude', 'find', 'skip', 'remove'] });
  assert.deepEqual(rowActions('suggested', { aiOn: false }).menu, ['find', 'skip', 'remove']);
  assert.deepEqual(rowActions('accepted', {}), { primary: [], menu: ['change', 'find', 'amount', 'grams', 'skip', 'remove'] });
  assert.deepEqual(rowActions('check', {}).primary, ['amount']);
  assert.deepEqual(rowActions('skipped', {}), { primary: [], menu: ['unskip', 'remove'] });
  assert.ok(!rowActions('accepted', { canRemove: false }).menu.includes('remove'));  // the last row stays
  for (const s of ROW_STATES) for (const k of [...rowActions(s, { aiOn: true }).primary, ...rowActions(s, { aiOn: true }).menu]) assert.ok(ACTION_LABELS[k], k);
  assert.equal(ACTION_LABELS.match, 'Match Ingredient');
  assert.equal(ACTION_LABELS.claude, 'Match With Claude');
});

test('chips say the state in words', () => {
  assert.equal(rowChip('accepted'), 'Matched');
  assert.equal(rowChip('unmatched'), 'Not Matched');
  assert.equal(rowChip('suggested', { method: 'search' }), 'Suggested');
  assert.equal(rowChip('suggested', { kind: 'candidate' }), 'Claude Suggests');
  assert.equal(rowChip('check'), 'Check Amount');
  assert.equal(rowChip('skipped'), 'Skipped');
});

test('rowLine shows amount, unit and name, with the note apart', () => {
  assert.deepEqual(rowLine(un(1, { src: src('flour', 1.5, 'cup', 'sifted') })), { head: '1 1/2 cup flour', note: 'sifted' });
  assert.deepEqual(rowLine(un(1, { src: src('eggs', 2, 'count') })), { head: '2 eggs', note: '' });
  assert.deepEqual(rowLine(un(1, { src: { text: 'Salt, to taste', amount: null, unit: null, name: 'Salt', note: 'to taste' } })), { head: 'Salt', note: 'to taste' });
  assert.deepEqual(rowLine({ id: 1, food: F, amount: 2, unit: 'tbsp', src: null }), { head: '2 tbsp Butter, salted', note: '' });
  assert.equal(foodText({ name: 'Oats', brand: 'Acme' }, 1, 'cup', 80, 300), 'Oats (Acme), 1 cup, 80 g, 300 kcal');
  assert.equal(foodText(null), '');
});

test('Match All: modes, the rows Search looks up and the plan with and without Claude', () => {
  assert.deepEqual(MATCH_ALL_MODES.map((m) => m[0]), ['search', 'claude', 'search_claude']);
  const items = [un(1), un(2), ok(3), un(4, { skipped: true }), un(5)];
  assert.deepEqual(searchIds(items, { 2: sug(2) }), { send: [1, 5], rest: [] });  // a suggested row already has one
  assert.deepEqual(searchIds(items, { 2: { item_id: 2, food: null } }).send, [1, 2, 5]);  // no result before: search again
  const many = Array.from({ length: 45 }, (_, i) => un(i + 1));
  assert.deepEqual([searchIds(many, {}).send.length, searchIds(many, {}).rest.length], [40, 5]);
  assert.deepEqual(matchAllPlan('search', true, false), { search: true, claude: false, note: '', all: false });
  assert.deepEqual(matchAllPlan('claude', true, false), { search: false, claude: true, note: '', all: true });
  assert.deepEqual(matchAllPlan('search_claude', true, false), { search: true, claude: true, note: '', all: false });
  assert.deepEqual(matchAllPlan('search_claude', true, true).all, true);  // Full Claude Use asks every row
  assert.deepEqual(matchAllPlan('claude', false, true), { search: true, claude: false, note: AUTO_CLAUDE_OFF, all: false });
  assert.deepEqual(claudeIds(items, { 1: sug(1) }, false).send, [2, 5]);
  assert.deepEqual(claudeIds(items, { 1: sug(1), 2: sug(2, { from_previous: true }) }, true).send, [1, 5]);
  assert.equal(moreText(0), '');
  assert.equal(moreText(1), '1 more is still unmatched. Tap Match All again for them.');
  assert.equal(moreText(5), sentence('5 more are still unmatched. Tap Match All again for them'));
});

test('Review One By One walks unmatched and suggested rows in list order and skips rows matched meanwhile', () => {
  const items = [ok(1), un(2), un(3, { skipped: true }), un(4), ok(5, { check: true }), un(6)];
  const props = { 4: sug(4) };
  const order = reviewOrder(items, props);
  assert.deepEqual(order, [2, 4, 6]);
  assert.equal(reviewNext(order, items, props, null), 0);
  assert.equal(reviewNext(order, items, props, 0), 1);
  const later = items.map((it) => (it.id === 4 ? ok(4) : it));  // row 4 was accepted
  assert.equal(reviewNext(order, later, {}, 0), 2);
  assert.equal(reviewNext(order, later, {}, 2), -1);
  assert.deepEqual(reviewOrder([ok(1)], {}), []);
  assert.equal(reviewPos(1, 3), 'Ingredient 2 of 3');
});

test('inline search: the line for the amount, the start text and at most 5 results', () => {
  const pk = un(1, { src: { text: '1 (15 oz) can beans', amount: 1, unit: 'can', name: 'beans', note: '15 oz', pkg_amount: 15, pkg_unit: 'oz' } });
  assert.deepEqual(lineOf(pk), { amount: 1, unit: 'can', pkg: { amount: 15, unit: 'oz' }, name: 'beans', was: null });
  const est = un(3, { src: { text: '3 cloves garlic', amount: 9, unit: 'g', name: 'garlic', note: '3 cloves', estimated: true, was_amount: 3, was_unit: 'clove' } });
  assert.deepEqual(lineOf(est).was, { amount: 3, unit: 'clove' });  // issue #55: the original wording for a real portion
  assert.deepEqual(lineOf({ id: 2, amount: 3, unit: 'g', src: null }), { amount: 3, unit: 'g', pkg: null, name: '' });
  assert.equal(searchStart(pk), 'beans');
  assert.equal(searchStart({ food: F, src: null }), 'Butter, salted');
  assert.equal(SEARCH_RESULTS, 5);
  assert.deepEqual(topResults([{ id: 1 }, { id: null }, { id: 2 }, { id: 3 }, { id: 4 }, { id: 5 }, { id: 6 }]).map((f) => f.id), [1, 2, 3, 4, 5]);
  assert.deepEqual(topResults(undefined), []);
});

test('the count line and the Undo body of a removed row', () => {
  const meal = { matched: 3, needed: 8, checks: 1, skipped: 0, items: [un(1), un(2), ok(3)] };
  assert.equal(matchedLine(meal, { 1: sug(1) }), '3 of 8 matched, 1 to check, 1 suggested');
  assert.equal(matchedLine({ matched: 1, needed: 2, skipped: 1, items: [] }, {}), '1 of 2 matched, 1 skipped');
  assert.deepEqual(restoreRowBody(ok(3, { check: true }), 2), { position: 2, src: src('butter', 1, 'tbsp'), food_id: 9, amount: 1, unit: 'tbsp', check: true });
  assert.deepEqual(restoreRowBody(un(4, { skipped: true }), 0), { position: 0, src: src('row 4', 1, 'cup'), skipped: true });
});

import { matchPromptCount, matchPromptShows, matchPromptText } from '../../app/static/js/rowmatch.js';

test('Match Ingredients banner shows only for editable recipes with unmatched rows and no dismissal', () => {
  const meal = (items, over) => ({ items, match_prompt_dismissed: false, ...over });
  const rows = [un(1), ok(2), un(3, { skipped: true }), un(4)];
  assert.equal(matchPromptCount(rows, {}), 2);
  assert.equal(matchPromptCount(rows, { 1: sug(1) }), 1);  // a waiting suggestion is not unmatched
  assert.equal(matchPromptShows(meal(rows), {}, { edit: true }), true);
  assert.equal(matchPromptShows(meal(rows), {}, { edit: false }), false);
  assert.equal(matchPromptShows(meal(rows, { match_prompt_dismissed: true }), {}, { edit: true }), false);
  assert.equal(matchPromptShows(meal(rows), {}, { edit: true, running: true }), false);
  assert.equal(matchPromptShows(meal(rows), {}, { edit: true, acted: true }), false);
  assert.equal(matchPromptShows(meal([ok(1), un(2, { skipped: true })]), {}, { edit: true }), false);
  assert.equal(matchPromptText(1), '1 ingredient is not matched to a food yet');
  assert.equal(matchPromptText(3), '3 ingredients are not matched to foods yet');
});
