import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ROW_STATES, rowState, rowActions, ACTION_LABELS, rowChip, rowLine, foodText, MATCH_MODES, matchModes, matchMode, matchBlock, openCount,
  searchIds, claudeIds, confidentIds, isConfident, chunks, claudeDoneText, walkDoneText,
  reviewOrder, reviewNext, reviewPos, lineOf, searchStart, topResults, SEARCH_RESULTS, matchedLine, restoreRowBody,
} from '../../app/static/js/rowmatch.js';
import * as ROWMATCH from '../../app/static/js/rowmatch.js';
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

test('each state shows one primary action and puts the rest in the menu (issue #56)', () => {
  assert.deepEqual(rowActions('unmatched', { aiOn: false }), { primary: ['match'], menu: ['search', 'scan', 'find', 'skip', 'remove'] });
  assert.deepEqual(rowActions('unmatched', { aiOn: true }).primary, ['match', 'claude']);  // + and the Claude sparkle, one tap each
  assert.deepEqual(rowActions('suggested', { aiOn: true }), { primary: ['accept'], menu: ['search', 'scan', 'claude', 'find', 'skip', 'remove'] });
  assert.deepEqual(rowActions('suggested', { aiOn: false }).menu, ['search', 'scan', 'find', 'skip', 'remove']);
  assert.deepEqual(rowActions('accepted', {}), { primary: [], menu: ['change', 'scan', 'find', 'amount', 'grams', 'skip', 'remove'] });
  assert.deepEqual(rowActions('check', {}).primary, ['amount']);
  assert.deepEqual(rowActions('skipped', {}), { primary: [], menu: ['unskip', 'remove'] });
  assert.ok(!rowActions('accepted', { canRemove: false }).menu.includes('remove'));  // the last row stays
  for (const s of ROW_STATES) for (const k of [...rowActions(s, { aiOn: true }).primary, ...rowActions(s, { aiOn: true }).menu]) assert.ok(ACTION_LABELS[k], k);
  assert.deepEqual([ACTION_LABELS.match, ACTION_LABELS.claude, ACTION_LABELS.search, ACTION_LABELS.scan, ACTION_LABELS.accept],
    ['Find Match', 'Use Claude', 'Search Again', 'Scan Barcode', 'Accept']);
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

test('one Match block: a choice of Match or Match With Claude, Start, and Continue Without Matching', () => {
  assert.deepEqual(MATCH_MODES, [['walk', 'Match'], ['claude', 'Match With Claude']]);
  assert.deepEqual(matchModes(false).map((m) => m[0]), ['walk']);  // Match With Claude only when Claude is usable
  assert.deepEqual(matchModes(true).map((m) => m[0]), ['walk', 'claude']);
  assert.equal(matchMode(undefined, true), 'walk');  // Match is the default
  assert.equal(matchMode('claude', true), 'claude');
  assert.equal(matchMode('claude', false), 'walk');
  for (const k of ['MATCH_ALL_MODES', 'matchAllPlan', 'moreText', 'matchPromptShows', 'matchPromptText', 'matchPromptCount']) assert.ok(!(k in ROWMATCH), k);
  const rows = [un(1), ok(2), un(3, { skipped: true }), un(4)];
  const meal = (over) => ({ items: rows, match_prompt_dismissed: false, ...over });
  assert.equal(openCount(rows, {}), 2);
  assert.equal(openCount(rows, { 1: sug(1) }), 2);  // a waiting suggestion is still open
  assert.deepEqual(matchBlock(meal(), {}, { edit: true }), { choice: true, dismiss: true, link: false });
  assert.deepEqual(matchBlock(meal(), {}, { edit: false }), { choice: false, dismiss: false, link: false });
  assert.deepEqual(matchBlock(meal({ match_prompt_dismissed: true }), {}, { edit: true }), { choice: false, dismiss: false, link: true });
  assert.deepEqual(matchBlock(meal({ match_prompt_dismissed: true }), {}, { edit: true, expanded: true }), { choice: true, dismiss: false, link: false });
  assert.deepEqual(matchBlock({ items: [ok(1), un(2, { skipped: true })] }, {}, { edit: true }), { choice: false, dismiss: false, link: false });
});

test('Match With Claude: the rows to search, to ask Claude about and to accept on their own', () => {
  const items = [un(1), un(2), ok(3), un(4, { skipped: true }), un(5), un(6)];
  const props = { 2: sug(2), 5: sug(5, { confident: true }), 6: { item_id: 6, food: null } };
  assert.deepEqual(searchIds(items, props), [1, 6]);  // a row with a food suggested already has one; no result before: search again
  assert.deepEqual(searchIds(Array.from({ length: 45 }, (_, i) => un(i + 1)), {}).length, 45);
  assert.equal(isConfident(sug(1, { confident: true })), true);
  assert.equal(isConfident(sug(1)), false);
  assert.equal(isConfident({ item_id: 1, food: null, confident: true }), false);
  assert.deepEqual(claudeIds(items, props, false), [1, 2, 6]);
  assert.deepEqual(claudeIds(items, props, true), [1, 2, 5, 6]);
  assert.deepEqual(claudeIds(items, { 5: sug(5, { confident: true, from_previous: true }) }, true), [1, 2, 6]);
  assert.deepEqual(confidentIds(items, props), [5]);
  assert.deepEqual(confidentIds([ok(5)], props), []);  // matched meanwhile
  assert.deepEqual(chunks([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]);
  assert.deepEqual(chunks([], 15), []);
  assert.equal(claudeDoneText(8, 3, 1, ''), 'Matched 8 ingredients. 3 suggestions are waiting for a look. Tap Accept on a row or start Match to go through them. 1 ingredient had no match.');
  assert.equal(claudeDoneText(1, 0, 0, ''), 'Matched 1 ingredient.');
  assert.equal(claudeDoneText(0, 1, 0, ''), 'Nothing was sure enough to match on its own. 1 suggestion is waiting for a look. Tap Accept on a row or start Match to go through them.');
  assert.equal(walkDoneText(5, 2), 'Matched 5 ingredients. 2 ingredients are still open.');
  assert.equal(walkDoneText(1, 1), 'Matched 1 ingredient. 1 ingredient is still open.');
  assert.equal(walkDoneText(0, 0), 'Nothing was matched.');
  for (const t of [claudeDoneText(2, 2, 2, ''), walkDoneText(2, 2)]) assert.ok(!t.includes(':') && !t.includes('\u2014'));
});

test('Match walks unmatched and suggested rows in list order and skips rows matched meanwhile', () => {
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
