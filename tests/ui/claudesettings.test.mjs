import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CLAUDE_SPECS, personalBody, personalHints, parsePrice, buildChanges, PERSONAL_CAP_DEFAULT, DEFAULT_MODEL,
} from '../../app/static/js/adminutil.js';
import { aiFeature, aiFeatureOff, searchSources, startSource, sentence } from '../../app/static/js/util.js';

const AI = { personal_cap: 100, personal_model: '', personal_price_in: null, personal_price_out: null, server_model: 'claude-haiku-5-5', personal_cap_default: 100 };
const form = (over) => ({ key: '', cap: '100', model: '', priceIn: '', priceOut: '', ...over });

test('every Claude admin field has a hint with its default, written as sentences without em dashes', () => {
  const keys = CLAUDE_SPECS.map((s) => s.key);
  assert.deepEqual(keys, ['ai_global_key', 'ai_model', 'ai_monthly_cap', 'ai_price_in_per_mtok', 'ai_price_out_per_mtok',
    'ai_allow_label', 'ai_allow_lookup', 'ai_allow_recipe']);
  for (const s of CLAUDE_SPECS) {
    assert.ok(s.hint && /by default/.test(s.hint), s.key);
    assert.equal(sentence(s.hint), s.hint, s.key);
    assert.ok(!/—|–/.test(s.hint), s.key);
  }
  const by = Object.fromEntries(CLAUDE_SPECS.map((s) => [s.key, s]));
  assert.match(by.ai_model.hint, new RegExp('uses ' + DEFAULT_MODEL));
  assert.match(by.ai_monthly_cap.hint, /100 by default\. Set 0 to turn shared use off\./);
  assert.match(by.ai_global_key.hint, /console\.anthropic\.com/);
  assert.match(by.ai_price_in_per_mtok.hint, /input tokens/);
  assert.match(by.ai_price_out_per_mtok.hint, /output tokens/);
  assert.equal(by.ai_allow_label.label, 'Allow Claude Photo Label Reading');
  assert.equal(by.ai_allow_lookup.label, 'Allow Claude Typed Search');
  assert.equal(by.ai_allow_recipe.label, 'Allow Claude Recipe Import');
  for (const k of ['ai_allow_label', 'ai_allow_lookup', 'ai_allow_recipe']) assert.equal(by[k].kind, 'bool');
});

test('feature switches send only what changed', () => {
  const items = { ai_allow_label: { value: true }, ai_allow_lookup: { value: true }, ai_allow_recipe: { value: false } };
  const r = buildChanges(CLAUDE_SPECS, items, { ai_allow_label: { value: false }, ai_allow_lookup: { value: true }, ai_allow_recipe: { value: true } });
  assert.deepEqual(r.changes, { ai_allow_label: false, ai_allow_recipe: true });
});

test('parsePrice', () => {
  assert.deepEqual(parsePrice('', 'Input price'), { ok: true, value: '' });
  assert.deepEqual(parsePrice(' 3 ', 'Input price'), { ok: true, value: 3 });
  assert.deepEqual(parsePrice('0,25', 'Input price'), { ok: true, value: 0.25 });
  assert.deepEqual(parsePrice('.5', 'x'), { ok: true, value: 0.5 });
  assert.deepEqual(parsePrice('10000', 'x'), { ok: true, value: 10000 });
  for (const bad of ['-1', 'abc', '10001', '1e3', '1.2.3']) assert.match(parsePrice(bad, 'Output price').error, /^Output price must be a number from 0 to 10000\.$/);
});

test('personalBody sends only the changed fields', () => {
  assert.deepEqual(personalBody(form(), AI), { body: null });
  assert.deepEqual(personalBody(form({ model: ' claude-x ', priceIn: '3', priceOut: '15' }), AI).body, { model: 'claude-x', price_in: 3, price_out: 15 });
  assert.deepEqual(personalBody(form({ key: 'sk-ant-xyz', cap: '20' }), AI).body, { key: 'sk-ant-xyz', cap: 20 });
  const saved = { ...AI, personal_model: 'claude-x', personal_price_in: 3, personal_price_out: 15 };
  assert.deepEqual(personalBody(form({ model: 'claude-x', priceIn: '3', priceOut: '15' }), saved), { body: null });
  assert.deepEqual(personalBody(form(), saved).body, { model: '', price_in: '', price_out: '' });  // cleared
  assert.match(personalBody(form({ cap: '0' }), AI).error, /limit/);
  assert.match(personalBody(form({ priceIn: '-2' }), AI).error, /^Input price/);
  assert.match(personalBody(form({ priceOut: 'x' }), AI).error, /^Output price/);
});

test('personal hints state the defaults', () => {
  const h = personalHints(AI);
  assert.match(h.cap, /100 by default\.$/);
  assert.match(h.model, /Empty by default, which uses the server's model, claude-haiku-5-5\.$/);
  assert.match(h.priceIn, /input tokens.*no cost is shown\.$/);
  assert.match(h.priceOut, /output tokens.*no cost is shown\.$/);
  assert.match(personalHints({ ...AI, server_model: 'claude-other' }).model, /claude-other/);
  assert.match(personalHints(null).cap, new RegExp(PERSONAL_CAP_DEFAULT + ' by default'));
  for (const t of Object.values(h)) assert.equal(sentence(t), t);
});

test('aiFeature and aiFeatureOff', () => {
  const on = { enabled: true, features: { label: true, lookup: true, recipe: true } };
  assert.equal(aiFeature(on, 'label'), true);
  assert.equal(aiFeature({ ...on, features: { ...on.features, recipe: false } }, 'recipe'), false);
  assert.equal(aiFeature({ ...on, enabled: false }, 'label'), false);
  assert.equal(aiFeature({ enabled: true }, 'lookup'), true);  // older server without features
  assert.equal(aiFeature(null, 'label'), false);
  assert.equal(aiFeatureOff({ features: { lookup: false } }, 'lookup'), true);
  assert.equal(aiFeatureOff({ enabled: false }, 'lookup'), false);
});

test('search sources and the starting source', () => {
  assert.deepEqual(searchSources(null).map((s) => s.value), ['all', 'off', 'fdc', 'ai']);
  assert.deepEqual(searchSources({ features: { lookup: false } }).map((s) => s.value), ['all', 'off', 'fdc']);
  assert.equal(startSource(null, undefined, null), 'all');
  assert.equal(startSource(null, 'fdc', null), 'fdc');
  assert.equal(startSource('off', 'fdc', null), 'off');  // the session choice wins
  assert.equal(startSource(null, 'ai', { features: { lookup: true } }), 'ai');
  assert.equal(startSource(null, 'ai', { features: { lookup: false } }), 'all');
  assert.equal(startSource('ai', 'off', { features: { lookup: false } }), 'all');
  assert.equal(startSource(null, 'bogus', null), 'all');
});
