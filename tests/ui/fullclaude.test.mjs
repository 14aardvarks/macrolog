import test from 'node:test';
import assert from 'node:assert/strict';
import {
  autoClaudePlan, aiMicrosText, 
  bulkSummary, CLAUDE_CAP_NOTE, FALLBACK_TEXT, FALLBACK_FAILED, sentence,
} from '../../app/static/js/util.js';
import { claudeKeep } from '../../app/static/js/recipeimport.js';
import { claudeIds } from '../../app/static/js/rowmatch.js';
import { GUIDE } from '../../app/static/js/guide.js';

const ON = { full_claude: true };
const st = (over) => ({ enabled: true, remaining: 10, cap: 100, features: { label: true, lookup: true, recipe: true }, ...over });

test('Match With Claude asks about rows the search was not sure of, and Full Claude Use about every row (issue #40)', () => {
  const items = [1, 2, 3].map((id) => ({ id, food: null, skipped: false, check: false }));
  const props = { 1: { item_id: 1, food: { id: 7 }, confident: true }, 2: { item_id: 2, food: { id: 8 } }, 3: { item_id: 3, food: { id: 9 }, confident: true } };
  assert.deepEqual(claudeIds(items, props, false), [2]);  // a sure search pick needs no Claude
  assert.deepEqual(claudeIds(items, props, true), [1, 2, 3]);  // Full Claude Use asks about all of them
  assert.deepEqual(claudeIds(items, {}, false), [1, 2, 3]);
});

test('a proposal from a previous recipe is not sent to Claude, and Claude finding nothing keeps the Search proposal', () => {
  const items = [1, 2, 3].map((id) => ({ id, food: null, skipped: false, check: false }));
  const props = { 1: { item_id: 1, food: { id: 7 }, from_previous: true, confident: true }, 2: { item_id: 2, food: { id: 8 } }, 3: { item_id: 3, food: null } };
  assert.deepEqual(claudeIds(items, props, true), [2, 3]);
  const answers = [{ item_id: 2, food: null }, { item_id: 3, food: null }, { item_id: 4, food: { id: 1 } }];
  assert.deepEqual(claudeKeep(answers, props).map((p) => p.item_id), [3, 4]);  // row 2 keeps Search, row 3 had nothing to lose
  assert.deepEqual(claudeKeep(undefined, props), []);
  assert.ok(/^[A-Z].*\.$/.test(CLAUDE_CAP_NOTE) && !CLAUDE_CAP_NOTE.includes('\u2014'));
});

test('autoClaudePlan: setting, switch, key and cap', () => {
  assert.equal(autoClaudePlan({ full_claude: false }, st(), 'lookup'), 'off');
  assert.equal(autoClaudePlan({}, st(), 'lookup'), 'off');
  assert.equal(autoClaudePlan(null, st(), 'lookup'), 'off');
  assert.equal(autoClaudePlan(ON, st({ enabled: false }), 'lookup'), 'off');  // no key: silent
  assert.equal(autoClaudePlan(ON, st({ features: { lookup: false } }), 'lookup'), 'off');  // switch off: silent
  assert.equal(autoClaudePlan(ON, null, 'lookup'), 'off');
  assert.equal(autoClaudePlan(ON, st({ remaining: 0 }), 'lookup'), 'cap');
  assert.equal(autoClaudePlan(ON, st({ remaining: undefined }), 'lookup'), 'cap');  // unknown counts as none left: never past the cap
  assert.equal(autoClaudePlan(ON, st(), 'lookup'), 'run');
  assert.equal(autoClaudePlan({ full_claude: true }, st(), 'lookup'), 'run');
  assert.equal(autoClaudePlan({ full_claude: true }, st({ remaining: 0 }), 'recipe'), 'cap');
});

test('aiMicrosText names the Claude estimates in nutrient order', () => {
  assert.equal(aiMicrosText({ ai_micros: [] }), '');
  assert.equal(aiMicrosText({}), '');
  assert.equal(aiMicrosText(null), '');
  assert.equal(aiMicrosText({ ai_micros: ['iron'] }), 'Claude estimated iron. These are estimates.');
  assert.equal(aiMicrosText({ ai_micros: ['iron', 'sodium', 'bogus'] }), 'Claude estimated sodium and iron. These are estimates.');
  assert.equal(aiMicrosText({ ai_micros: ['iron', 'sodium', 'fiber'] }), 'Claude estimated fiber, sodium and iron. These are estimates.');
});

test('bulk summary counts Claude estimates and adds the cap note once', () => {
  const base = { checked: 3, filled: 5, failed: 0, left: 0, stopped: false };
  assert.equal(bulkSummary(base), 'Checked 3 foods and filled 5 values');
  assert.equal(bulkSummary({ ...base, byClaude: 2, note: CLAUDE_CAP_NOTE }),
    'Checked 3 foods and filled 5 values (2 estimated by Claude). Monthly Claude limit reached, so Claude was not used.');
});

test('Full Claude steps never ask and stop quietly at the cap', async () => {
  const { autoClaude } = await import('../../app/static/js/notice.js');
  assert.deepEqual(await autoClaude({ full_claude: true }, st(), 'lookup'), { go: true, note: '' });
  assert.deepEqual(await autoClaude({ full_claude: true }, st({ remaining: 0 }), 'lookup'), { go: false, note: CLAUDE_CAP_NOTE });
});

test('Full Claude copy: sentences end with a period, no em dashes, guide covers it', () => {
  for (const t of [CLAUDE_CAP_NOTE, FALLBACK_TEXT, FALLBACK_FAILED]) {
    assert.equal(t, sentence(t));
    assert.ok(t.endsWith('.') && !t.includes('—'));
  }
  assert.ok(FALLBACK_TEXT.includes('Claude Estimate'));
  const g = GUIDE.find((x) => x.heading === 'Full Claude Use');
  assert.ok(g && g.bullets.some((b) => b.includes('off by default')));
});

test('the Full Claude Use hint states the default first', async () => {
  const { FULL_CLAUDE_HELP } = await import('../../app/static/js/claudekey.js');
  assert.ok(FULL_CLAUDE_HELP.startsWith('Off by default.'));
  assert.ok(!FULL_CLAUDE_HELP.includes('—'));
  assert.ok(FULL_CLAUDE_HELP.includes('monthly request limit'));
});
