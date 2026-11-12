import test from 'node:test';
import assert from 'node:assert/strict';
import {
  effectiveAutoMatch, autoClaudePlan, fullClaudeRows, fullClaudePriceNote, aiMicrosText, microsWhat, recipeTextCostLine,
  noticeLines, bulkSummary, CLAUDE_CAP_NOTE, FALLBACK_TEXT, FALLBACK_FAILED, sentence,
} from '../../app/static/js/util.js';
import { autoMatchPlan } from '../../app/static/js/recipeimport.js';
import { GUIDE } from '../../app/static/js/guide.js';

const ON = { full_claude: true, confirm_ai: true };
const st = (over) => ({ enabled: true, remaining: 10, cap: 100, features: { label: true, lookup: true, recipe: true }, ...over });

test('effectiveAutoMatch: Full Claude Use turns only Search (or unset) into Search Then Claude', () => {
  assert.deepEqual(effectiveAutoMatch('search', true), { value: 'search_claude', forced: true });
  assert.deepEqual(effectiveAutoMatch(undefined, true), { value: 'search_claude', forced: true });
  assert.deepEqual(effectiveAutoMatch('bogus', true), { value: 'search_claude', forced: true });
  for (const v of ['claude', 'search_claude', 'off']) assert.deepEqual(effectiveAutoMatch(v, true), { value: v, forced: false });
  assert.deepEqual(effectiveAutoMatch('search', false), { value: 'search', forced: false });
  assert.deepEqual(effectiveAutoMatch('off', false), { value: 'off', forced: false });
});

test('a forced Search Then Claude without Claude falls back to Search silently', () => {
  const eff = effectiveAutoMatch('search', true);
  assert.deepEqual(autoMatchPlan(eff.forced ? 'search' : eff.value, false), { search: true, claude: false, note: '' });
  assert.equal(autoMatchPlan(eff.value, true).claude, true);
  assert.ok(autoMatchPlan('search_claude', false).note);  // an explicit choice still says so
});

test('autoClaudePlan: setting, switch, key, cap and confirm', () => {
  assert.equal(autoClaudePlan({ full_claude: false, confirm_ai: true }, st(), 'lookup'), 'off');
  assert.equal(autoClaudePlan({}, st(), 'lookup'), 'off');
  assert.equal(autoClaudePlan(null, st(), 'lookup'), 'off');
  assert.equal(autoClaudePlan(ON, st({ enabled: false }), 'lookup'), 'off');  // no key: silent
  assert.equal(autoClaudePlan(ON, st({ features: { lookup: false } }), 'lookup'), 'off');  // switch off: silent
  assert.equal(autoClaudePlan(ON, null, 'lookup'), 'off');
  assert.equal(autoClaudePlan(ON, st({ remaining: 0 }), 'lookup'), 'cap');
  assert.equal(autoClaudePlan(ON, st({ remaining: undefined }), 'lookup'), 'cap');  // unknown counts as none left: never past the cap
  assert.equal(autoClaudePlan(ON, st(), 'lookup'), 'confirm');
  assert.equal(autoClaudePlan({ full_claude: true, confirm_ai: false }, st(), 'lookup'), 'run');
  assert.equal(autoClaudePlan({ full_claude: true, confirm_ai: false }, st({ remaining: 0 }), 'recipe'), 'cap');
});

test('cost rows come from the server numbers and are labelled estimates', () => {
  const costs = { label: 0.00043, lookup: 0.00027, micros: 0.000135, recipe_text: 0.00114, match: 0.00196,
    heavy_month: 0.0415, heavy_requests: 86, sample: true };
  const rows = fullClaudeRows(costs);
  assert.equal(rows.length, 6);
  assert.deepEqual(rows[0], { label: 'Claude lookup when a search finds nothing', text: 'about 0.03 cents' });
  assert.deepEqual(rows[2], { label: 'Label photo', text: 'about 0.04 cents' });
  assert.deepEqual(rows[5], { label: 'Heavy month (86 requests)', text: 'about $0.04' });
  assert.deepEqual(fullClaudeRows(null), []);
  assert.match(fullClaudePriceNote(costs), /^Estimates at the Haiku 5\.5 sample prices of 0\.10 USD input and 0\.50 USD output per million tokens/);
  assert.equal(fullClaudePriceNote({ ...costs, sample: false }), 'Estimates at your model prices.');
  assert.equal(fullClaudeRows({ ...costs, heavy_month: 0.004 })[5].text, 'about 0.4 cents');
  for (const r of rows) assert.ok(!r.text.includes('—') && !r.label.includes('—'));
});

test('aiMicrosText names the Claude estimates in nutrient order', () => {
  assert.equal(aiMicrosText({ ai_micros: [] }), '');
  assert.equal(aiMicrosText({}), '');
  assert.equal(aiMicrosText(null), '');
  assert.equal(aiMicrosText({ ai_micros: ['iron'] }), 'Claude estimated iron. These are estimates.');
  assert.equal(aiMicrosText({ ai_micros: ['iron', 'sodium', 'bogus'] }), 'Claude estimated sodium and iron. These are estimates.');
  assert.equal(aiMicrosText({ ai_micros: ['iron', 'sodium', 'fiber'] }), 'Claude estimated fiber, sodium and iron. These are estimates.');
});

test('notice lines say how many requests a batch may use', () => {
  const s = { remaining: 7, cap: 100, est_cost_label: 0.00135 };
  assert.equal(noticeLines(s, microsWhat(10), 10).lines[1], 'Uses up to 10 of your 100 monthly requests (7 left).');
  assert.equal(noticeLines(s, microsWhat(1)).lines[1], 'Uses 1 of your 100 monthly requests (7 left).');
  assert.equal(microsWhat(1), 'the name, serving and macros of 1 food to estimate missing nutrients');
  assert.equal(noticeLines({ ...s, remaining: 0 }, 'x', 3).blocked, true);
});

test('bulk summary counts Claude estimates and adds the cap note once', () => {
  const base = { checked: 3, filled: 5, failed: 0, left: 0, stopped: false };
  assert.equal(bulkSummary(base), 'Checked 3 foods and filled 5 values');
  assert.equal(bulkSummary({ ...base, byClaude: 2, note: CLAUDE_CAP_NOTE }),
    'Checked 3 foods and filled 5 values (2 estimated by Claude). Monthly Claude limit reached, so Claude was not used.');
});

test('recipe text line shows the cost before the tap', () => {
  const line = recipeTextCostLine(st({ remaining: 12, action_costs: { recipe_text: 0.00114, sample: true } }));
  assert.equal(line, 'Full Claude Use is on, so Read With Claude sends the text at once. Up to about 0.11 cents per import at sample prices. 12 of 100 Claude requests left this month.');
  assert.equal(recipeTextCostLine({}), 'Full Claude Use is on, so Read With Claude sends the text at once.');
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
