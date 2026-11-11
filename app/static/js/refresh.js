// Refresh Nutrients: fills blank micronutrients from the food's original source. Never changes existing values.
import { api } from './api.js';
import { h, message, show } from './dom.js';
import { missingMicros, refreshTargets, bulkSummary } from './util.js';

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

// Refresh All Missing for My Foods. At most REFRESH_CAP foods per tap, one after another, stopping at a rate limit.
// getFoods() returns the current foods, reload() fetches fresh data and repaints. Call update() after every repaint.
export function refreshAllControl(getFoods, reload) {
  const status = h('div', { 'aria-live': 'polite' });
  const btn = h('button', { class: 'btn', type: 'button', onclick: run }, 'Refresh All Missing');
  const el = h('div', { class: 'refresh' }, btn, status);
  function update() { btn.hidden = refreshTargets(getFoods()).todo.length === 0; }
  async function run() {
    const { todo, left } = refreshTargets(getFoods());
    const sum = { checked: 0, filled: 0, failed: 0, left, stopped: false };
    btn.disabled = true;
    for (const food of todo) {
      try {
        const res = await api.refreshNutrients(food.id);
        sum.filled += res.filled.length;
      } catch (e) {
        sum.failed++;
        if (e.status === 429) { sum.stopped = true; sum.left += todo.length - sum.checked; break; }
      }
      sum.checked++;
    }
    try { await reload(); } catch (e) { /* the summary below still applies */ }
    show(status, message(bulkSummary(sum), sum.failed ? 'error' : ''));
    btn.disabled = false;
    update();
  }
  return { el, update };
}
