import test from 'node:test';
import assert from 'node:assert/strict';
import {
  REFRESH_MODES, refreshMode, resolveRefreshMode, refreshClaudeReason, refreshClaudePlan, refreshModeHint, sentence,
  REFRESH_NO_KEY, REFRESH_SWITCH, REFRESH_CAPPED, DEFAULT_DISPLAY,
} from '../../app/static/js/util.js';
import { GUIDE } from '../../app/static/js/guide.js';

const st = (over) => ({ enabled: true, remaining: 10, cap: 100, features: { label: true, lookup: true, recipe: true }, ...over });

test('refreshMode keeps the two known values and falls back to Search Only', () => {
  assert.deepEqual(REFRESH_MODES.map((m) => m.value), ['search', 'search_claude']);
  assert.deepEqual(REFRESH_MODES.map((m) => m.label), ['Search Only', 'Search Then Claude']);
  assert.equal(refreshMode('search_claude'), 'search_claude');
  for (const v of [undefined, null, '', 'claude', 'SEARCH', 5]) assert.equal(refreshMode(v), 'search');
  assert.equal(DEFAULT_DISPLAY.refresh_mode, 'search');
});

test('resolveRefreshMode: Search Only by default, Search Then Claude by default under Full Claude Use', () => {
  assert.deepEqual(resolveRefreshMode('search', false, null, st()), { value: 'search', reason: '', forced: false });
  assert.deepEqual(resolveRefreshMode(undefined, false, null, st()), { value: 'search', reason: '', forced: false });
  assert.deepEqual(resolveRefreshMode('search', true, null, st()), { value: 'search_claude', reason: '', forced: true });
  assert.deepEqual(resolveRefreshMode('bogus', true, null, st()), { value: 'search_claude', reason: '', forced: true });
});

test('resolveRefreshMode: a saved Search Then Claude holds with Full Claude Use on or off', () => {
  assert.equal(resolveRefreshMode('search_claude', false, null, st()).value, 'search_claude');
  assert.deepEqual(resolveRefreshMode('search_claude', true, null, st()), { value: 'search_claude', reason: '', forced: false });
});

test('resolveRefreshMode: a pick of Search Only this visit beats the Full Claude Use default', () => {
  assert.deepEqual(resolveRefreshMode('search', true, 'search', st()), { value: 'search', reason: '', forced: false });
  assert.equal(resolveRefreshMode('search_claude', true, 'search', st()).value, 'search');
  assert.equal(resolveRefreshMode('search', false, 'search_claude', st()).value, 'search_claude');
});

test('Claude unavailable: the run is Search Only and the reason says why, in order key, switch, cap', () => {
  assert.equal(refreshClaudeReason(st()), '');
  assert.equal(refreshClaudeReason(null), REFRESH_NO_KEY);
  assert.equal(refreshClaudeReason(st({ enabled: false })), REFRESH_NO_KEY);
  assert.equal(refreshClaudeReason(st({ enabled: false, features: { lookup: false } })), REFRESH_NO_KEY);
  assert.equal(refreshClaudeReason(st({ features: { label: true, lookup: false, recipe: true } })), REFRESH_SWITCH);
  assert.equal(refreshClaudeReason(st({ remaining: 0 })), REFRESH_CAPPED);
  assert.equal(refreshClaudeReason(st({ features: { lookup: false }, remaining: 0 })), REFRESH_SWITCH);
  for (const [stat, why] of [[null, REFRESH_NO_KEY], [st({ features: { lookup: false } }), REFRESH_SWITCH], [st({ remaining: 0 }), REFRESH_CAPPED]]) {
    for (const full of [true, false]) {
      assert.deepEqual(resolveRefreshMode('search_claude', full, null, stat), { value: 'search', reason: why, forced: false });
    }
  }
  assert.equal(resolveRefreshMode('search', true, null, null).value, 'search');
  for (const t of [REFRESH_NO_KEY, REFRESH_SWITCH, REFRESH_CAPPED]) assert.ok(/^[A-Z].*\.$/.test(t) && !/—/.test(t));
});

test('refreshClaudePlan follows Confirm before using Claude, with no Full Claude Use needed', () => {
  assert.equal(refreshClaudePlan({ confirm_ai: true }, st()), 'confirm');
  assert.equal(refreshClaudePlan({ confirm_ai: false, full_claude: false }, st()), 'run');
  assert.equal(refreshClaudePlan({ full_claude: true }, st()), 'confirm');
  assert.equal(refreshClaudePlan({}, st({ remaining: 0 })), 'cap');
  assert.equal(refreshClaudePlan({}, st({ enabled: false })), 'off');
  assert.equal(refreshClaudePlan({}, st({ features: { lookup: false } })), 'off');
});

test('the hint states both defaults as sentences without em dashes', () => {
  for (const full of [true, false]) {
    const t = refreshModeHint(full);
    assert.equal(sentence(t), t);
    assert.ok(!/—|–/.test(t) && /Search Only/.test(t) && /Search Then Claude/.test(t));
  }
  assert.match(refreshModeHint(false), /Search Only is the default/);
  assert.match(refreshModeHint(true), /Full Claude Use is on, so Search Then Claude is the default/);
});

test('the guide explains the choice in bullets of at most 16 words', () => {
  const bullets = GUIDE.flatMap((g) => g.bullets).filter((b) => /Search Only|Search Then Claude/.test(b) && /Refresh|Claude/.test(b));
  assert.ok(bullets.some((b) => /Refresh Nutrients asks Search Only or Search Then Claude/.test(b)));
  for (const b of bullets) assert.ok(b.split(/\s+/).length <= 16, b);
});

// ---------- the run itself, with fetch stubbed ----------

async function setup({ full, confirm = false, display = { refresh_mode: 'search' }, status = st() }) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method });
    const body = String(url).startsWith('/api/ai/status') ? status
      : String(url).startsWith('/api/settings/display') ? { ...display, refresh_mode: JSON.parse(init.body).refresh_mode }
      : { food: {}, filled: [], claude_filled: [] };
    return { ok: true, status: 200, json: async () => body };
  };
  const mod = await import('../../app/static/js/refresh.js?' + Math.random());
  let shown = display;
  mod.useSettings(() => ({ full_claude: full, confirm_ai: confirm }), () => shown, async (patch) => { shown = { ...shown, ...patch }; return (await (await fetch('/api/settings/display', { method: 'PUT', body: JSON.stringify(patch) })).json()); });
  return { mod, calls, display: () => shown };
}

test('Search Only makes no Claude request, even with Full Claude Use on', async () => {
  const t = await setup({ full: true });
  await t.mod.chooseRefreshMode('search');  // saved is search, Full Claude Use would make Search Then Claude the default
  const go = await t.mod.claudeGo(3);
  assert.deepEqual(go, { go: false, note: '' });
  const sum = await t.mod.refreshBatch([1, 2, 3], 0, go);
  assert.equal(sum.checked, 3);
  const refreshes = t.calls.filter((c) => c.url.includes('/refresh-nutrients'));
  assert.equal(refreshes.length, 3);
  assert.ok(refreshes.every((c) => !/claude=/.test(c.url)), 'no claude parameter was sent');
  assert.ok(!t.calls.some((c) => c.method === 'PUT'), 'Search Only under Full Claude Use lasts for the visit and is not saved');
});

test('Search Then Claude asks Claude for the run, with Full Claude Use off, and saves the choice', async () => {
  const t = await setup({ full: false });
  await t.mod.chooseRefreshMode('search_claude');
  assert.equal(t.display().refresh_mode, 'search_claude');
  const go = await t.mod.claudeGo(2);
  assert.deepEqual(go, { go: true, note: '' });
  await t.mod.refreshBatch([1, 2], 0, go);
  assert.equal(t.calls.filter((c) => /refresh-nutrients\?claude=1/.test(c.url)).length, 2);
});

test('Search Then Claude is refused and never sent when Claude is not available', async () => {
  for (const status of [st({ enabled: false }), st({ features: { lookup: false } }), st({ remaining: 0 })]) {
    const t = await setup({ full: true, display: { refresh_mode: 'search_claude' }, status });
    await t.mod.chooseRefreshMode('search_claude');
    assert.ok(!t.calls.some((c) => c.method === 'PUT'));
    assert.deepEqual(await t.mod.claudeGo(2), { go: false, note: '' });
  }
});
