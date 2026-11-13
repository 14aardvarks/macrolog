import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MATCH_METHODS, MATCH_MAX, matchMethod, matchRunText, methodBatch, matchDoneText, proposalHead, proposalText,
  matchSnapshot, restoreBody, changedSince, parseIngredientLine,
} from '../../app/static/js/recipeimport.js';

const F = { id: 9, name: 'Oats' };
const src = (text) => ({ text, amount: null, unit: null, name: text, note: null });
const un = (id, text) => ({ id, food: null, food_id: null, amount: null, unit: null, skipped: false, check: false, src: src(text || 'row ' + id) });
const ok = (id, over) => ({ id, food: F, food_id: 9, amount: 2, unit: 'cup', skipped: false, check: false, src: null, ...over });
const meal = (items, over) => ({ id: 1, servings: 2, yield: null, items, ...over });

test('the method switch has Search first and falls back to Search without Claude', () => {
  assert.deepEqual(MATCH_METHODS, [['search', 'Search'], ['claude', 'Claude']]);
  assert.equal(matchMethod(undefined, true), 'search');
  assert.equal(matchMethod('search', true), 'search');
  assert.equal(matchMethod('claude', true), 'claude');
  assert.equal(matchMethod('claude', false), 'search');
  assert.equal(matchRunText('search'), 'Match Selected With Search');
  assert.equal(matchRunText('claude'), 'Match Selected With Claude');
});

test('Claude sends up to 15 rows, Search up to 40, and the rest stay ticked', () => {
  const ids = Array.from({ length: 45 }, (_, i) => i + 1);
  assert.equal(MATCH_MAX.claude, 15);
  assert.equal(MATCH_MAX.search, 40);
  const c = methodBatch('claude', ids);
  assert.equal(c.send.length, 15);
  assert.equal(c.rest.length, 30);
  const s = methodBatch('search', ids);
  assert.deepEqual([s.send.length, s.rest.length, s.rest[0]], [40, 5, 41]);
  assert.equal(methodBatch('search', ids.slice(0, 12)).rest.length, 0);
  assert.equal(methodBatch('anything', ids).send.length, 40);
});

test('the note after a run counts rows without a match and rows still ticked', () => {
  const found = { food: F }, none = { food: null };
  assert.equal(matchDoneText('search', [found, found], 0), 'Check the suggestions, then accept them all or one by one.');
  assert.equal(matchDoneText('search', [found, none, none], 0), 'Check the suggestions, then accept them all or one by one. 2 ingredients had no match.');
  assert.equal(matchDoneText('search', [found, none], 5), 'Check the suggestions, then accept them all or one by one. 1 ingredient had no match. 5 more are still ticked. Tap Match Selected With Search again for them.');
  assert.equal(matchDoneText('search', [none], 0), 'No suggestions were found.');
  assert.equal(matchDoneText('claude', [found, none], 3, 'This cost about 2 cents.'),
    'Check the suggestions, then accept them all or one by one. This cost about 2 cents. 3 more are still ticked. Tap Match Selected With Claude again for them.');
});

test('a Search proposal says it is a search result, and no match reads as a short note', () => {
  assert.equal(proposalHead({ method: 'search', food: F }), 'Suggested Match');
  assert.equal(proposalHead({ method: 'search', food: null }), 'Search Result');
  assert.equal(proposalHead({ kind: 'candidate', food: F }), 'Claude Suggests');
  assert.equal(proposalText({ method: 'search', kind: 'none', food: null, note: 'No match found.' }), 'No match found.');
  assert.equal(proposalText({ method: 'search', kind: 'candidate', food: F, amount: 2, unit: 'cup', grams: null, check: true }), 'Oats, 2 cup (check the amount)');
});

test('Back puts back a removed row at its place and drops rows added since', () => {
  const base = matchSnapshot(meal([ok(1), un(2, '1 tbsp oil'), ok(3, { skipped: true, src: src('salt') }), ok(4, { check: true })]));
  assert.deepEqual(base.items[1].src, src('1 tbsp oil'));
  const now = meal([ok(1), ok(4, { check: true }), un(7, 'new row')]);  // 2 and 3 removed, 7 added
  const r = restoreBody(base, now);
  assert.deepEqual(r.remove, [7]);
  assert.deepEqual(r.add, [
    { position: 1, src: src('1 tbsp oil') },
    { position: 2, src: src('salt'), food_id: 9, amount: 2, unit: 'cup', skipped: true },
  ]);
  assert.deepEqual(r.items, []);
  assert.equal(r.meal, null);
  assert.equal(changedSince(base, now), true);
  assert.equal(changedSince(base, meal([ok(1), un(2, '1 tbsp oil'), ok(3, { skipped: true, src: src('salt') }), ok(4, { check: true })])), false);
  assert.equal(changedSince(base, meal([...base.items.map((b) => ({ ...b, food: b.food_id ? F : null })), un(8, 'x')])), true);
});

test('a removed Check Amount row comes back with check, and the snapshot is a copy of the line', () => {
  const m = meal([ok(1, { check: true, src: src('a') }), ok(2)]);
  const base = matchSnapshot(m);
  m.items[0].src.text = 'changed';
  assert.equal(base.items[0].src.text, 'a');
  const r = restoreBody(base, meal([ok(2)]));
  assert.deepEqual(r.add, [{ position: 0, src: src('a'), food_id: 9, amount: 2, unit: 'cup', check: true }]);
});

test('a typed ingredient line is split into amount, unit and name for Add Ingredient', () => {
  assert.deepEqual(parseIngredientLine('1 tbsp olive oil'), { text: '1 tbsp olive oil', amount: 1, unit: 'tbsp', name: 'olive oil', note: null });
  assert.deepEqual(parseIngredientLine('2 eggs, beaten'), { text: '2 eggs, beaten', amount: 2, unit: 'count', name: 'eggs', note: 'beaten' });
  assert.equal(parseIngredientLine('   '), null);
});
