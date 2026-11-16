import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MATCH_MAX, methodBatch, proposalHead, proposalText, parseIngredientLine,
} from '../../app/static/js/recipeimport.js';

const F = { id: 9, name: 'Oats' };

test('Claude sends up to 15 rows, Search up to 40, and the rest wait for the next run', () => {
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

test('a Search proposal says it is a search result, and no match reads as a short note', () => {
  assert.equal(proposalHead({ method: 'search', food: F }), 'Suggested Match');
  assert.equal(proposalHead({ method: 'search', food: null }), 'Search Result');
  assert.equal(proposalHead({ kind: 'candidate', food: F }), 'Claude Suggests');
  assert.equal(proposalText({ method: 'search', kind: 'none', food: null, note: 'No match found.' }), 'No match found.');
  assert.equal(proposalText({ method: 'search', kind: 'candidate', food: F, amount: 2, unit: 'cup', grams: null, check: true }), 'Oats, 2 cup (check the amount)');
});

test('a typed ingredient line is split into amount, unit and name for Add Ingredient', () => {
  assert.deepEqual(parseIngredientLine('1 tbsp olive oil'), { text: '1 tbsp olive oil', amount: 1, unit: 'tbsp', name: 'olive oil', note: null });
  assert.deepEqual(parseIngredientLine('2 eggs, beaten'), { text: '2 eggs, beaten', amount: 2, unit: 'count', name: 'eggs', note: 'beaten' });
  assert.equal(parseIngredientLine('   '), null);
});
