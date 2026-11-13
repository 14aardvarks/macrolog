import test from 'node:test';
import assert from 'node:assert/strict';
import {
  REFRESH_MODES, refreshMode, resolveRefreshMode, refreshClaudeReason, refreshClaudePlan, refreshModeHint, sentence,
  REFRESH_NO_KEY, REFRESH_SWITCH, REFRESH_CAPPED, DEFAULT_DISPLAY, refreshFallbackNote,
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
  assert.deepEqual(resolveRefreshMode('search', false, false, st()), { wanted: 'search', value: 'search', reason: '', forced: false });
  assert.deepEqual(resolveRefreshMode(undefined, undefined, false, st()), { wanted: 'search', value: 'search', reason: '', forced: false });
  assert.deepEqual(resolveRefreshMode('search', false, true, st()), { wanted: 'search_claude', value: 'search_claude', reason: '', forced: true });
  assert.deepEqual(resolveRefreshMode('bogus', false, true, st()), { wanted: 'search_claude', value: 'search_claude', reason: '', forced: true });
});

test('resolveRefreshMode: an explicit choice holds with Full Claude Use on or off, including Search Only', () => {
  assert.equal(resolveRefreshMode('search_claude', true, false, st()).value, 'search_claude');
  assert.deepEqual(resolveRefreshMode('search_claude', true, true, st()), { wanted: 'search_claude', value: 'search_claude', reason: '', forced: false });
  assert.deepEqual(resolveRefreshMode('search', true, true, st()), { wanted: 'search', value: 'search', reason: '', forced: false });
  assert.equal(resolveRefreshMode('bogus', true, true, st()).wanted, 'search');
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
      assert.deepEqual(resolveRefreshMode('search_claude', true, full, stat), { wanted: 'search_claude', value: 'search', reason: why, forced: false });
    }
  }
  assert.equal(resolveRefreshMode('search', true, true, null).value, 'search');
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
  assert.ok(bullets.some((b) => /Settings, Display, Refresh Nutrients picks Search Only or Search Then Claude/.test(b)));
  assert.ok(bullets.some((b) => /Refresh uses Search Only and says why/.test(b)));
  for (const b of GUIDE.flatMap((g) => g.bullets)) assert.ok(b.split(/\s+/).length <= 16, b);
});

// ---------- the run itself, with fetch stubbed ----------

async function setup({ full, confirm = false, display = { refresh_mode: 'search', refresh_mode_set: false }, status = st() }) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method });
    const body = String(url).startsWith('/api/ai/status') ? status : { food: {}, filled: [], claude_filled: [] };
    return { ok: true, status: 200, json: async () => body };
  };
  const mod = await import('../../app/static/js/refresh.js?' + Math.random());
  mod.useSettings(() => ({ full_claude: full, confirm_ai: confirm }), () => display);
  return { mod, calls };
}

const refreshes = (t) => t.calls.filter((c) => c.url.includes('/refresh-nutrients'));

test('an explicit Search Only makes no Claude request, even with Full Claude Use on', async () => {
  const t = await setup({ full: true, display: { refresh_mode: 'search', refresh_mode_set: true } });
  const go = await t.mod.claudeGo(3);
  assert.deepEqual(go, { go: false, note: '' });
  const sum = await t.mod.refreshBatch([1, 2, 3], 0, go);
  assert.equal(sum.checked, 3);
  assert.equal(refreshes(t).length, 3);
  assert.ok(refreshes(t).every((c) => !/claude=/.test(c.url)), 'no claude parameter was sent');
});

test('the default follows Full Claude Use: Search Then Claude on, Search Only off', async () => {
  const on = await setup({ full: true });
  assert.deepEqual(await on.mod.claudeGo(2), { go: true, note: '' });
  const off = await setup({ full: false });
  assert.deepEqual(await off.mod.claudeGo(2), { go: false, note: '' });
});

test('a saved Search Then Claude asks Claude for the run with Full Claude Use off', async () => {
  const t = await setup({ full: false, display: { refresh_mode: 'search_claude', refresh_mode_set: true } });
  const go = await t.mod.claudeGo(2);
  assert.deepEqual(go, { go: true, note: '' });
  await t.mod.refreshBatch([1, 2], 0, go);
  assert.equal(refreshes(t).filter((c) => /refresh-nutrients\?claude=1/.test(c.url)).length, 2);
});

test('a chosen Search Then Claude that is unavailable falls back to Search Only with one note naming the reason', async () => {
  for (const [status, why] of [[st({ enabled: false }), REFRESH_NO_KEY], [st({ features: { lookup: false } }), REFRESH_SWITCH], [st({ remaining: 0 }), REFRESH_CAPPED]]) {
    for (const full of [true, false]) {
      const t = await setup({ full, display: { refresh_mode: 'search_claude', refresh_mode_set: true }, status });
      const go = await t.mod.claudeGo(2);
      assert.equal(go.go, false);
      assert.equal(go.note, refreshFallbackNote(why));
      assert.ok(go.note.includes(why) && go.note.startsWith('Search Then Claude is not available, so Search Only ran.'));
      await t.mod.refreshBatch([1, 2], 0, go);
      assert.ok(refreshes(t).every((c) => !/claude=/.test(c.url)));
    }
  }
});

test('Full Claude Use as the default stays silent when Claude is off, and notes the cap', async () => {
  assert.deepEqual(await (await setup({ full: true, status: st({ enabled: false }) })).mod.claudeGo(2), { go: false, note: '' });
  assert.deepEqual(await (await setup({ full: true, status: st({ features: { lookup: false } }) })).mod.claudeGo(2), { go: false, note: '' });
  const capped = await (await setup({ full: true, status: st({ remaining: 0 }) })).mod.claudeGo(2);
  assert.equal(capped.go, false);
  assert.ok(capped.note.includes(REFRESH_CAPPED));
});

test('no Refresh button shows the choice any more', async () => {
  const fs = await import('node:fs');
  for (const f of ['refresh', 'saved', 'picker', 'foodform']) assert.ok(!/refresh-mode|modeControl|chooseRefreshMode/.test(fs.readFileSync(`app/static/js/${f}.js`, 'utf8')), f);
});
