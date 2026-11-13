// Refresh Nutrients: fills blank micronutrients from the food's original source. Never changes existing values.
import { api } from './api.js';
import { h, message, show, clear } from './dom.js';
import { missingMicros, kcalEstimated, refreshTargets, bulkSummary, pendingPlan, microsWhat, sentence, CLAUDE_CAP_NOTE, REFRESH_CAPPED, resolveRefreshMode, refreshFallbackNote } from './util.js';
import { refreshClaude } from './notice.js';

// app.js hands over the signed-in user's settings (Full Claude Use, Confirm before using Claude) and the display settings (refresh_mode),
// so every Refresh Nutrients button uses the Search Only or Search Then Claude choice saved in Settings, Display.
let settingsOf = () => null;
let displayOf = () => null;
export function useSettings(get, getDisplay) {
  settingsOf = get;
  if (getDisplay) displayOf = getDisplay;
}
const fullOn = () => { const s = settingsOf(); return !!(s && s.full_claude === true); };

const STATUS_MS = 20000;
let seen = { st: null, at: 0 };
async function claudeStatus(fresh) {
  if (!fresh && seen.at && Date.now() - seen.at < STATUS_MS) return seen.st;
  let st = null;
  try { st = await api.aiStatus(null, null, { micros: 1 }); } catch (e) { st = null; }
  seen = { st, at: Date.now() };
  return st;
}
const modeNow = (st) => { const d = displayOf() || {}; return resolveRefreshMode(d.refresh_mode, d.refresh_mode_set, fullOn(), st); };

// Whether the next run asks Claude (Search Then Claude chosen and available), from the last status read.
const wantsClaude = () => modeNow(seen.st).value === 'search_claude';

// Whether Claude may fill blanks for the next n foods: nothing for Search Only (even with Full Claude Use on). A chosen Search Then Claude
// that cannot be used falls back to Search Only with one quiet note naming the reason (Full Claude Use as the default stays silent,
// except a note at the cap). Else the usual confirm with the cost (Confirm before using Claude on) or nothing (off).
export async function claudeGo(n) {
  if (!n) return { go: false, note: '' };
  const st = await claudeStatus(true);
  const m = modeNow(st);
  if (m.value !== 'search_claude') {
    if (m.wanted === 'search_claude' && (!m.forced || m.reason === REFRESH_CAPPED)) return { go: false, note: refreshFallbackNote(m.reason) };
    return { go: false, note: '' };
  }
  return refreshClaude(settingsOf(), st, { what: microsWhat(n), requests: n, query: { micros: Math.min(10, n) } });
}

// food is updated in place. onDone(result) runs after a successful call. Returns { el } with a button and a status line.
export function refreshControl(food, onDone) {
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'btn', type: 'button', onclick: run }, 'Refresh Nutrients');
  async function run() {
    btn.disabled = true;
    try {
      const ai = await claudeGo(1);
      const res = await api.refreshNutrients(food.id, ai.go);
      Object.assign(food, res.food);
      show(status, message(ai.note ? sentence(res.message) + ' ' + ai.note : res.message, res.filled.length ? 'ok' : ''));
      if (!missingMicros(food).length && !kcalEstimated(food)) { btn.hidden = true; }
      if (onDone) onDone(res);
    } catch (e) {
      show(status, message(e.message, 'error'));
    }
    btn.disabled = false;
  }
  return { el: h('div', { class: 'refresh' }, btn, status) };
}

// Refreshes the foods one after another and stops at a rate limit (429). left is how many more wait after this batch.
// Returns { checked, filled, failed, left, stopped, checkedIds }. The food that hit the limit is not counted as checked.
// claude: Full Claude Use was cleared for this batch; it stops for the rest of the batch at the monthly cap, with one note.
export async function refreshBatch(todo, left, claude) {
  const sum = { checked: 0, filled: 0, failed: 0, left, stopped: false, checkedIds: [], byClaude: 0, note: claude && claude.note };
  let ask = !!(claude && claude.go);
  for (const food of todo) {
    const id = typeof food === 'object' ? food.id : food;
    try {
      const res = await api.refreshNutrients(id, ask);
      sum.filled += res.filled.length;
      sum.byClaude += (res.claude_filled || []).length;
      if (res.claude_capped) { ask = false; sum.note = CLAUDE_CAP_NOTE; }
    } catch (e) {
      sum.failed++;
      if (e.status === 429) { sum.stopped = true; sum.left += todo.length - sum.checked; break; }
    }
    sum.checked++;
    sum.checkedIds.push(id);
  }
  return sum;
}

// Refresh All Missing for My Foods. At most REFRESH_CAP foods per tap, one after another, stopping at a rate limit.
// getFoods() returns the current foods, reload() fetches fresh data and repaints. Call update() after every repaint.
export function refreshAllControl(getFoods, reload) {
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'btn', type: 'button', onclick: run }, 'Refresh All Missing');
  const el = h('div', { class: 'refresh' }, btn, status);
  function update() { btn.hidden = refreshTargets(getFoods()).todo.length === 0; }
  async function run() {
    const { todo, left } = refreshTargets(getFoods());
    btn.disabled = true;
    const sum = await refreshBatch(todo, left, await claudeGo(todo.length));
    try { await reload(); } catch (e) { /* the summary below still applies */ }
    show(status, message(bulkSummary(sum), sum.failed ? 'error' : ''));
    btn.disabled = false;
    update();
  }
  return { el, update };
}

// Per scope (a day or "all") the ids already checked in this visit and the last summary, kept across repaints.
const NOTE_MS = 8000;
const scopes = new Map();
function scopeState(key) {
  if (!scopes.has(key)) scopes.set(key, { done: new Set(), note: null });
  return scopes.get(key);
}

// Refresh the foods the user has logged. scope names the set ("day:YYYY-MM-DD" or "all"), load(claude) returns { ids } from
// the server (claude true: with Full Claude Use, foods only Claude can fill count too), label is the button text. quiet hides the whole control when nothing needs a refresh (Today).
// onFinish() runs after a batch (Today repaints the day); without it the control updates itself.
export function refreshLoggedControl({ scope, load, label, quiet, onFinish }) {
  const st = scopeState(scope);
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'btn', type: 'button', onclick: run }, label);
  const el = h('div', { class: 'refresh' }, btn, status);
  el.hidden = !!quiet;  // starts hidden when quiet, so a repaint of Today does not shift the page when the control turns out unneeded
  async function paint() {
    try {
      await claudeStatus(false);
      const plan = pendingPlan((await load(wantsClaude())).ids, st.done);
      btn.hidden = !plan.todo.length;
      el.hidden = !!quiet && !plan.total && !st.note;
      if (st.note && Date.now() >= st.note.until) st.note = null;
      show(status, st.note ? message(st.note.text, st.note.kind) : '');
      if (st.note) setTimeout(paint, st.note.until - Date.now() + 50);  // the summary shows only for a few seconds
    } catch (e) {
      el.hidden = !!quiet;
      show(status, message(e.message, 'error'));
    }
  }
  async function run() {
    btn.disabled = true;
    try {
      await claudeStatus(true);
      const asked = wantsClaude();
      let plan = pendingPlan((await load(asked)).ids, st.done);
      const ai = await claudeGo(plan.todo.length);
      if (asked && !ai.go) plan = pendingPlan((await load(false)).ids, st.done);  // without Claude only foods with a source
      const sum = await refreshBatch(plan.todo, plan.left, ai);
      sum.checkedIds.forEach((id) => st.done.add(id));
      st.note = { text: bulkSummary(sum), kind: sum.failed ? 'error' : '', until: Date.now() + NOTE_MS };
    } catch (e) {
      st.note = { text: e.message, kind: 'error', until: Date.now() + NOTE_MS };
    }
    btn.disabled = false;
    if (onFinish) onFinish(); else await paint();
  }
  paint();
  return { el };
}
