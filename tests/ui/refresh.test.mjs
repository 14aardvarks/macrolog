import test from 'node:test';
import assert from 'node:assert/strict';
import { missingMicros, canLookUp, canRefresh, refreshTargets, bulkSummary, REFRESH_CAP } from '../../app/static/js/util.js';

const FULL = { fiber: 1, sugars: 1, saturated_fat: 1, sodium: 1, cholesterol: 1, potassium: 1, calcium: 1, iron: 1, vitamin_d: 1 };

test('missingMicros lists null nutrients only, zero counts as known', () => {
  assert.deepEqual(missingMicros(FULL), []);
  assert.deepEqual(missingMicros({ ...FULL, iron: null, sodium: undefined, fiber: 0 }), ['sodium', 'iron']);
});

test('canLookUp needs a source id or a barcode', () => {
  assert.equal(canLookUp({ source: 'off', source_id: '3017620422003' }), true);
  assert.equal(canLookUp({ source: 'fdc', source_id: '777' }), true);
  assert.equal(canLookUp({ source: 'fdc', source_id: 'abc' }), false);
  assert.equal(canLookUp({ source: 'custom', source_id: null, barcode: '3017620422003' }), true);
  assert.equal(canLookUp({ source: 'custom', barcode: '12' }), false);
  assert.equal(canLookUp({ source: 'ai', barcode: null }), false);
  assert.equal(canLookUp(null), false);
});

test('canRefresh also needs a blank nutrient', () => {
  assert.equal(canRefresh({ source: 'off', source_id: '1', ...FULL }), false);
  assert.equal(canRefresh({ source: 'off', source_id: '1', ...FULL, calcium: null }), true);
  assert.equal(canRefresh({ source: 'custom', barcode: null }), false);
});

test('refreshTargets caps the batch and counts what is left', () => {
  const foods = [];
  for (let i = 0; i < 14; i++) foods.push({ id: i, source: 'fdc', source_id: String(100 + i) });
  foods.push({ id: 99, source: 'custom', barcode: null });
  const r = refreshTargets(foods);
  assert.equal(REFRESH_CAP, 10);
  assert.equal(r.todo.length, 10);
  assert.equal(r.left, 4);
  assert.deepEqual(refreshTargets(foods, 3).todo.map((f) => f.id), [0, 1, 2]);
  assert.deepEqual(refreshTargets([]), { todo: [], left: 0 });
});

test('bulkSummary says how many were done', () => {
  assert.equal(bulkSummary({ checked: 10, filled: 23, failed: 0, left: 4, stopped: false }),
    'Checked 10 foods and filled 23 values. 4 foods left, tap again to continue');
  assert.equal(bulkSummary({ checked: 1, filled: 1, failed: 0, left: 0, stopped: false }), 'Checked 1 food and filled 1 value');
  assert.equal(bulkSummary({ checked: 3, filled: 0, failed: 1, left: 5, stopped: true }),
    'Checked 3 foods and filled 0 values. 1 food could not be refreshed. Stopped at the rate limit, try again later');
});
