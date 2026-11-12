// Refresh Nutrients: fills blank micronutrients from the food's original source. Never changes existing values.
import { api } from './api.js';
import { h, message, show } from './dom.js';
import { missingMicros, refreshTargets, bulkSummary, pendingPlan } from './util.js';

// food is updated in place. onDone(result) runs after a successful call. Returns { el } with a button and a status line.
export function refreshControl(food, onDone) {
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'btn', type: 'button', onclick: run }, 'Refresh Nutrients');
  async function run() {
    btn.disabled = true;
    try {
      const res = await api.refreshNutrients(food.id);
      Object.assign(food, res.food);
      show(status, message(res.message, res.filled.length ? 'ok' : ''));
      if (!missingMicros(food).length) btn.hidden = true;
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
async function refreshBatch(todo, left) {
  const sum = { checked: 0, filled: 0, failed: 0, left, stopped: false, checkedIds: [] };
  for (const food of todo) {
    const id = typeof food === 'object' ? food.id : food;
    try {
      const res = await api.refreshNutrients(id);
      sum.filled += res.filled.length;
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
    const sum = await refreshBatch(todo, left);
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

// Refresh the foods the user has logged. scope names the set ("day:YYYY-MM-DD" or "all"), load() returns { ids } from
// the server, label is the button text. quiet hides the whole control when nothing needs a refresh (Today).
// onFinish() runs after a batch (Today repaints the day); without it the control updates itself.
export function refreshLoggedControl({ scope, load, label, quiet, onFinish }) {
  const st = scopeState(scope);
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'btn', type: 'button', onclick: run }, label);
  const el = h('div', { class: 'refresh' }, btn, status);
  el.hidden = !!quiet;  // starts hidden when quiet, so a repaint of Today does not shift the page when the control turns out unneeded
  async function paint() {
    try {
      const plan = pendingPlan((await load()).ids, st.done);
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
      const plan = pendingPlan((await load()).ids, st.done);
      const sum = await refreshBatch(plan.todo, plan.left);
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
