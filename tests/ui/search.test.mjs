import test from 'node:test';
import assert from 'node:assert/strict';
import { SEARCH_SOURCES, searchSource, searchAction, searchHint, MAX_AI_TEXT, DESCRIPTION_TEXT, noticeLines, sentence } from '../../app/static/js/util.js';
import { api } from '../../app/static/js/api.js';

test('source options are the four choices in order, labels in Title Case', () => {
  assert.deepEqual(SEARCH_SOURCES.map((s) => [s.value, s.label]),
    [['all', 'All Sources'], ['off', 'Open Food Facts'], ['fdc', 'USDA'], ['ai', 'Claude']]);
  for (const s of SEARCH_SOURCES) assert.ok(s.label.split(' ').every((w) => /^[A-Z]/.test(w)), s.label);
});

test('searchSource falls back to All Sources', () => {
  assert.equal(searchSource('off'), 'off');
  assert.equal(searchSource('ai'), 'ai');
  for (const bad of [undefined, null, '', 'claude', 'custom']) assert.equal(searchSource(bad), 'all');
});

test('database sources search while typing and on Search, never Claude', () => {
  for (const src of ['all', 'off', 'fdc']) {
    assert.deepEqual(searchAction(src, ' rice ', false, true), { kind: 'search', source: src, remote: false });
    assert.deepEqual(searchAction(src, 'rice', true, true), { kind: 'search', source: src, remote: true });
  }
  assert.deepEqual(searchAction('nonsense', 'rice', true, true), { kind: 'search', source: 'all', remote: true });
});

test('empty box shows the tabs and typed digits look up a barcode for every source', () => {
  for (const src of ['all', 'off', 'fdc', 'ai']) {
    assert.deepEqual(searchAction(src, '   ', true, true), { kind: 'tabs' });
    assert.deepEqual(searchAction(src, '0 73472-00101 1', true, true), { kind: 'barcode', code: '073472001011' });
  }
});

test('Claude is asked only on Search, only when set up, and only for short text', () => {
  assert.deepEqual(searchAction('ai', 'oatmeal', false, true), { kind: 'wait' });
  assert.deepEqual(searchAction('ai', ' bowl of oatmeal ', true, true), { kind: 'claude', text: 'bowl of oatmeal' });
  assert.deepEqual(searchAction('ai', 'oatmeal', true, false), { kind: 'off' });
  assert.deepEqual(searchAction('ai', 'oatmeal', false, false), { kind: 'off' });
  assert.deepEqual(searchAction('ai', 'oatmeal', true, null), { kind: 'claude', text: 'oatmeal' });  // status unknown: the server decides
  assert.deepEqual(searchAction('ai', 'a'.repeat(MAX_AI_TEXT), true, true).kind, 'claude');
  assert.deepEqual(searchAction('ai', 'a'.repeat(MAX_AI_TEXT + 1), true, true), { kind: 'long' });
  assert.equal(MAX_AI_TEXT, 200);
});

test('hints name the source and are full sentences', () => {
  assert.equal(searchHint('all', 'press'), 'Press Search to check Open Food Facts and USDA.');
  assert.equal(searchHint('off', 'press'), 'Press Search to check Open Food Facts.');
  assert.equal(searchHint('fdc', 'press'), 'Press Search to check USDA.');
  assert.equal(searchHint('fdc', 'none'), 'No results.');
  assert.match(searchHint('ai', 'off'), /not set up.*Settings/);
  assert.match(searchHint('ai', 'wait'), /^Press Search to ask Claude/);
  assert.match(searchHint('ai', 'long'), /200 characters/);
  for (const k of ['press', 'none', 'off', 'wait', 'long']) {
    const t = searchHint('ai', k);
    assert.equal(sentence(t), t);
    assert.ok(!t.includes('—'));
  }
});

test('confirm notice for a description reads naturally', () => {
  const st = { remaining: 9, cap: 100, est_cost_label: 0.001 };
  assert.equal(noticeLines(st, DESCRIPTION_TEXT).lines[0], 'Sends your food description to Claude.');
});

test('api: search passes the source, aiStatus asks for a text estimate, aiLookup posts JSON', async () => {
  const seen = [];
  const orig = globalThis.fetch;
  globalThis.fetch = async (url, init) => { seen.push({ url, init }); return { ok: true, status: 200, json: async () => ({}) }; };
  try {
    await api.search('rice', true, 'off');
    await api.search('rice', false, 'all');
    await api.aiStatus(null, 12);
    await api.aiStatus(2);
    await api.aiStatus();
    await api.aiLookup('oatmeal');
  } finally { globalThis.fetch = orig; }
  assert.equal(seen[0].url, '/api/foods/search?q=rice&remote=1&source=off');
  assert.equal(seen[1].url, '/api/foods/search?q=rice&remote=0');
  assert.equal(seen[2].url, '/api/ai/status?chars=12');
  assert.equal(seen[3].url, '/api/ai/status?images=2');
  assert.equal(seen[4].url, '/api/ai/status');
  assert.equal(seen[5].url, '/api/ai/lookup');
  assert.equal(seen[5].init.method, 'POST');
  assert.deepEqual(JSON.parse(seen[5].init.body), { text: 'oatmeal' });
});
