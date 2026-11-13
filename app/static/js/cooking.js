// Cooking View: a large, easy to read page of one recipe for use at the stove. Ingredients are scaled to the servings shown,
// steps are numbered, and tapping an ingredient or step ticks it off. Ticks live in memory only. The screen is kept awake with
// the Wake Lock API when the browser has it; without it nothing changes and nothing is shown.
import { api } from './api.js';
import { h, clear } from './dom.js';
import { loadPhotoConfig, photoFigure } from './photo.js';
import { servingText, cookBase, cookServingsNext, cookIngredients, cookSteps, cookToggle } from './util.js';

// Asks for a screen wake lock and asks again when the page comes back to the front (the browser drops it when the page is hidden).
// Feature detected and silent on any failure. Returns a function that lets the screen sleep again.
export function keepAwake(nav = typeof navigator === 'undefined' ? null : navigator, doc = typeof document === 'undefined' ? null : document) {
  if (!nav || !doc || !nav.wakeLock || typeof nav.wakeLock.request !== 'function') return () => {};
  let lock = null;
  let stopped = false;
  const acquire = async () => {
    try {
      const got = await nav.wakeLock.request('screen');
      if (stopped) { await got.release(); return; }
      lock = got;
    } catch (e) { /* denied or unsupported: stay quiet */ }
  };
  const again = () => { if (doc.visibilityState === 'visible' && !stopped) acquire(); };
  doc.addEventListener('visibilitychange', again);
  acquire();
  return () => {
    stopped = true;
    doc.removeEventListener('visibilitychange', again);
    if (lock) { try { const l = lock; lock = null; Promise.resolve(l.release()).catch(() => {}); } catch (e) { /* ignore */ } }
  };
}

// params: { mealId }. ctx: { back }. Returns the cleanup that releases the wake lock.
export async function renderCooking(root, params, ctx) {
  const [meal] = await Promise.all([api.meal(params.mealId), loadPhotoConfig()]);
  const base = cookBase(meal);
  let shown = base;
  let checked = new Set();
  const ingBox = h('ul', { class: 'cook-list cook-ings' });
  const stepBox = h('ol', { class: 'cook-list cook-steps' });
  const count = h('span', { class: 'cook-count', 'aria-live': 'polite' });

  // One tappable row. The box shows the state as well as the line through, so colour is never the only signal.
  const row = (it, label) => {
    const on = checked.has(it.key);
    return h('li', { class: 'cook-row' + (on ? ' done' : '') },
      h('button', { class: 'cook-tick', type: 'button', 'aria-pressed': on ? 'true' : 'false', 'aria-label': label + (on ? ', done' : ''),
        onclick: () => { checked = cookToggle(checked, it.key); paint(); } },
      h('span', { class: 'cook-box', 'aria-hidden': 'true' }, on ? '✓' : ''),
      h('span', { class: 'cook-text' }, it.text)));
  };
  function paint() {
    clear(ingBox);
    cookIngredients(meal, shown).forEach((it) => ingBox.appendChild(row(it, it.text)));
    clear(stepBox);
    cookSteps(meal).forEach((st, i) => stepBox.appendChild(row(st, 'Step ' + (i + 1) + ', ' + st.text)));
    count.textContent = servingText(shown) + (shown === 1 ? ' serving' : ' servings');
    less.disabled = shown <= cookServingsNext(shown, base, -1);
  }
  const bump = (dir) => { shown = cookServingsNext(shown, base, dir); paint(); };
  const less = h('button', { class: 'btn cook-step', type: 'button', 'aria-label': 'Fewer Servings', onclick: () => bump(-1) }, '−');
  const more = h('button', { class: 'btn cook-step', type: 'button', 'aria-label': 'More Servings', onclick: () => bump(1) }, '+');
  paint();
  const steps = cookSteps(meal);
  root.appendChild(h('section', { class: 'screen cooking' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, meal.name),
    photoFigure(meal, 'cook-photo'),
    h('div', { class: 'cook-servings', role: 'group', 'aria-label': 'Servings' }, less, count, more),
    h('p', { class: 'sub' }, 'Tap an item to check it off.'),
    h('h2', null, 'Ingredients'),
    meal.items.length ? ingBox : h('p', { class: 'sub' }, 'No ingredients yet.'),
    h('h2', null, 'Steps'),
    steps.length ? stepBox : h('p', { class: 'sub' }, 'No steps yet.')));
  return keepAwake();
}
