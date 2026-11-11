import { api, setUnauthorizedHandler } from './api.js';
import { h, clear, select, field, message, show, cameraIcon } from './dom.js';
import {
  MEALS, MEAL_LABELS, parseDecimal, parseAmount, amountText, servingText, setAmountFormat, unitLabel, fmtNum, fmtAmount, groupByMeal, checkedItems, canSaveRecipe, localDate, progressText, remainingText,
  barWidth, debounce, digitsOnly, guessMeal, pctTotal, latestGuard, MEAL_FILTERS, MEAL_FILTER_LABELS, filterByMeal, filterSaved, pageOf, PAGE_SIZE, emptyText,
} from './util.js';
import { renderPicker } from './picker.js';
import { renderScan, barcodeForm } from './scan.js';
import { renderAi } from './ai.js';
import { renderFoodForm } from './foodform.js';
import { splitChart } from './chart.js';
import { renderGuide } from './guide-view.js';
import { renderSetup } from './setup.js';
import { renderAdmin } from './admin.js';
import { renderSaved } from './saved.js';
import { renderClaudeSection, renderSignIn } from './claudekey.js';

const main = document.getElementById('main');
const nav = document.getElementById('nav');
const state = { user: null, settings: { start_screen: 'today', default_meal: null, use_last: true, confirm_ai: true, amount_format: 'fraction' }, cleanup: null, depth: 0, tab: 'favorites', addMeal: 'all' };  // addMeal lives for the session only
const NAV_OF = { today: 'today', settings: 'settings', admin: 'settings', saved: 'settings', editfood: 'settings' };  // every other screen belongs to Add

const ctx = {
  go,
  back: () => (state.depth > 0 ? history.back() : go('today', {}, true)),
  get settings() { return state.settings; },
  lookup: (code) => go('lookup', { code }),
};

// ---------- routing ----------

function go(name, params, replace) {
  const d = replace ? state.depth : state.depth + 1;
  const entry = { name, params: params || {}, d };
  if (replace) history.replaceState(entry, ''); else history.pushState(entry, '');
  state.depth = d;
  return render(entry);
}

window.addEventListener('popstate', (e) => {
  const entry = e.state && e.state.name ? e.state : { name: 'today', params: {}, d: 0 };
  state.depth = entry.d || 0;
  render(entry);
});

const guard = latestGuard();

// Each screen is built in a detached box and swapped in only if no newer render started meanwhile.
async function render(entry) {
  const ticket = guard.next();
  if (state.cleanup) { state.cleanup(); state.cleanup = null; }
  const screen = SCREENS[entry.name] || SCREENS.today;
  const key = NAV_OF[entry.name] || 'add';
  nav.hidden = entry.name === 'login';
  nav.querySelectorAll('button').forEach((b) => {
    if (b.dataset.go === key) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  clear(main);
  const box = h('div', { class: 'view' });
  let cleanup = null;
  try {
    const out = await screen(box, entry.params || {}, ctx);
    if (typeof out === 'function') cleanup = out;
  } catch (e) {
    if (!guard.isLatest(ticket) || e.status === 401) return;
    box.appendChild(h('section', { class: 'screen' }, message(e.message || 'Something went wrong', 'error'),
      h('button', { class: 'btn', type: 'button', onclick: () => render(entry) }, 'Try again')));
  }
  if (!guard.isLatest(ticket)) { if (cleanup) cleanup(); return; }
  state.cleanup = cleanup;
  clear(main).appendChild(box);
  box.dispatchEvent(new Event('mounted'));
  window.scrollTo(0, 0);
  main.focus({ preventScroll: true });
}

nav.addEventListener('click', (e) => {
  const b = e.target.closest('button[data-go]');
  if (b) go(b.dataset.go, {}, false);
});

function showLogin() {
  state.user = null;
  state.depth = 0;
  history.replaceState({ name: 'login', params: {}, d: 0 }, '');
  render({ name: 'login', params: {}, d: 0 });
}
setUnauthorizedHandler(showLogin);

function startScreen() {
  const s = state.settings.start_screen;
  if (s === 'scan') return go('scan', {}, true);
  if (s === 'search') return go('add', { focus: true }, true);
  if (s === 'ai') return go('ai', {}, true);
  return go('today', {}, true);
}

async function afterLogin() {
  try { state.settings = await api.settings(); } catch (e) { /* keep defaults */ }
  setAmountFormat(state.settings.amount_format);
  if (location.hash === '#settings') {  // the SSO link flow returns here
    history.replaceState(history.state, '', location.pathname + location.search);
    return go('settings', {}, true);
  }
  return startScreen();
}

// ---------- shared bits ----------

function mealSelect(value) {
  const opts = [{ value: 'none', label: MEAL_LABELS.none }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))];
  return select(opts, value || 'none', { 'aria-label': 'Meal' });
}
const defaultMeal = () => state.settings.default_meal || guessMeal(new Date().getHours());
const unitText = amountText;

function foodRow(title, sub, onclick, extra) {
  return h('li', { class: 'item' },
    h('button', { class: 'item-main', type: 'button', onclick }, h('span', { class: 'item-title' }, title), h('span', { class: 'item-sub' }, sub)),
    extra || null);
}

// ---------- login ----------

async function loginScreen(root) {
  nav.hidden = true;
  const cfg = await api.authConfig().catch(() => ({ local: true, oidc: false, oidc_name: '' }));
  if (cfg.needs_setup) {
    renderSetup(root, async (me) => { state.user = me; await afterLogin(); });
    return;
  }
  const user = field('Username', { autocomplete: 'username', autocapitalize: 'none', required: '' });
  const pass = field('Password', { type: 'password', autocomplete: 'current-password', required: '' });
  const status = h('div', { 'aria-live': 'polite' });
  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault();
    show(status, null);
    try {
      state.user = await api.login(user.input.value.trim(), pass.input.value);
      await afterLogin();
    } catch (err) { show(status, message(err.status === 401 ? 'Wrong username or password.' : err.message, 'error')); }
  } }, user, pass, status, h('button', { class: 'btn primary', type: 'submit' }, 'Sign in'));
  root.appendChild(h('section', { class: 'screen login' }, h('h1', null, 'Macrolog'),
    cfg.local ? form : null,
    cfg.oidc ? h('a', { class: 'btn', href: '/auth/oidc/login' }, 'Sign in with ' + (cfg.oidc_name || 'single sign-on')) : null,
    !cfg.local && !cfg.oidc ? message('Sign-in is not configured on this server.', 'error') : null));
}

// ---------- today ----------

async function todayScreen(root) {
  const d = await api.day(localDate());
  const bars = [['kcal', 'Calories', ''], ['carbs', 'Carbs', ' g'], ['protein', 'Protein', ' g'], ['fat', 'Fat', ' g']].map(([k, label, unit]) => {
    const text = progressText(d.totals[k], d.targets[k], d.percent[k], unit);
    return h('div', { class: 'bar-row' },
      h('div', { class: 'bar-head' }, h('span', null, label), h('span', null, text)),
      h('div', { class: 'track', role: 'progressbar', 'aria-label': label, 'aria-valuemin': '0', 'aria-valuemax': '100',
        'aria-valuenow': String(barWidth(d.percent[k])), 'aria-valuetext': text },
      h('div', { class: 'fill' + (d.percent[k] > 100 ? ' over' : ''), style: 'width:' + barWidth(d.percent[k]) + '%' })),
      h('div', { class: 'bar-left' }, remainingText(d.remaining[k], unit)));
  });
  const status = h('div', { 'aria-live': 'polite' });
  const groups = groupByMeal(d.entries).map((g) => h('div', null,
    h('h2', { class: 'group' }, g.label, h('span', null, fmtNum(g.kcal, 0) + ' kcal')),
    h('ul', { class: 'list' }, g.entries.map((e) => entryRow(e, root))), saveMealBox(g, status)));
  root.appendChild(h('section', { class: 'screen' }, h('h1', null, 'Today'),
    h('h2', null, 'Calorie Split'), splitChart(d), bars,
    d.entries.length ? groups : message('Tap Add to log your first food.'),
    status));
}

function entryRow(e, root) {
  const sub = unitText(e.amount, e.unit) + ' - ' + fmtNum(e.kcal, 0) + ' kcal';
  const title = e.brand ? e.name + ' (' + e.brand + ')' : e.name;
  const open = () => go('picker', { foodId: e.food_id, entryId: e.id, amount: e.amount, unit: e.unit, meal: e.meal });
  const del = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + e.name, onclick: async () => {
    try { await api.deleteEntry(e.id); await go('today', {}, true); } catch (err) { show(root.querySelector('[aria-live]'), message(err.message, 'error')); }
  } }, '×');
  if (e.food_id == null) return h('li', { class: 'item' }, h('div', { class: 'item-main' }, h('span', { class: 'item-title' }, title), h('span', { class: 'item-sub' }, sub)), del);
  return foodRow(title, sub, open, del);
}

// One Save as recipe button per meal group. It opens a checklist of that group's entries, all ticked.
function saveMealBox(g, status) {
  const box = h('div', { class: 'save-meal' });
  const reset = () => show(box, h('button', { class: 'btn', type: 'button', onclick: ask }, 'Save as recipe'));
  function ask() {
    const rows = g.entries.filter((e) => e.food_id != null).map((e) => ({ e,
      box: h('input', { type: 'checkbox', checked: true, 'aria-label': 'Include ' + e.name }) }));
    const name = field('Recipe name', { autocomplete: 'off', value: g.label });
    const save = h('button', { class: 'btn primary', type: 'submit' }, 'Save');
    const sync = () => { save.disabled = !canSaveRecipe(rows.filter((r) => r.box.checked).length, name.input.value); };
    rows.forEach((r) => r.box.addEventListener('change', sync));
    name.input.addEventListener('input', sync);
    show(box, h('form', { class: 'sheet', onsubmit: async (ev) => {
      ev.preventDefault();
      const ids = rows.filter((r) => r.box.checked).map((r) => r.e.id);
      if (save.disabled) return;
      try {
        const m = await api.mealFromMeal(name.input.value.trim(), g.meal, ids, localDate());
        show(status, message('Saved recipe "' + m.name + '".'));
        reset();
      } catch (err) { show(status, message(err.message, 'error')); }
    } },
    h('ul', { class: 'list' }, rows.map((r) => h('li', { class: 'item meal-item' }, r.box,
      h('span', { class: 'item-title' }, r.e.name), h('span', { class: 'unit' }, unitText(r.e.amount, r.e.unit))))),
    name, h('div', { class: 'row' }, save, h('button', { class: 'btn ghost', type: 'button', onclick: reset }, 'Cancel'))));
    sync();
  }
  reset();
  return box;
}

// ---------- add ----------

const pickerOf = (it, meal) => () => go('picker', { foodId: it.food_id, amount: it.amount, unit: it.unit, meal });
// The meal to preselect in the picker or checklist: the chosen one, or undefined so the usual default applies.
const chosenMeal = () => (state.addMeal === 'all' ? undefined : state.addMeal);
const foodTitle = (f) => (f.brand ? f.name + ' (' + f.brand + ')' : f.name);

function addScreen(root, params) {
  const listBox = h('div', { 'aria-live': 'polite' });
  const q = h('input', { type: 'search', placeholder: 'Search foods', 'aria-label': 'Search foods', enterkeyhint: 'search', autocomplete: 'off' });
  const tabNames = [['favorites', 'Favorites'], ['yesterday', 'Yesterday'], ['recipes', 'Recipes']];
  const tabBar = h('div', { class: 'tabs', role: 'tablist' }, tabNames.map(([k, label]) => h('button', {
    type: 'button', role: 'tab', 'data-tab': k, onclick: () => { state.tab = k; q.value = ''; liveSearch.cancel(); paintTabs(); } }, label)));
  const mealSel = select(MEAL_FILTERS.map((m) => ({ value: m, label: MEAL_FILTER_LABELS[m] })), state.addMeal, { 'aria-label': 'Meal' });
  mealSel.addEventListener('change', () => { state.addMeal = mealSel.value; if (!q.value.trim()) paintTabs(); });
  const mealPick = h('label', { class: 'meal-pick' }, h('span', null, 'Meal'), mealSel);
  let searchSeq = 0;

  // remote false while typing (local only), true for Enter or the Search button.
  async function search(remote) {
    const text = q.value.trim();
    const mine = ++searchSeq;
    if (!text) { paintTabs(); return; }
    tabBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', 'false'));
    if (/^\d{8,14}$/.test(digitsOnly(text)) && /^[\d\s-]+$/.test(text)) { ctx.lookup(digitsOnly(text)); return; }
    if (remote) show(listBox, message('Searching...'));
    try {
      const r = (await api.search(text, remote)).results;
      if (mine !== searchSeq) return;
      const manual = h('button', { class: 'btn', type: 'button', onclick: () => go('manual', {}) }, 'Enter manually');
      const empty = remote ? message('No results.') : message('Press Search to check Open Food Facts and USDA');
      show(listBox, h('div', null, r.length ? h('ul', { class: 'list' }, r.map((f) => foodRow(foodTitle(f),
        (f.label_text || unitText(f.serving_amount, f.serving_unit)) + ' - ' + fmtNum(f.kcal, 0) + ' kcal',
        () => go('picker', { foodId: f.id })))) : empty, r.length ? null : manual));
    } catch (e) { if (mine === searchSeq) show(listBox, message(e.message, 'error')); }
  }
  const liveSearch = debounce(() => search(false), 400);
  q.addEventListener('input', liveSearch);

  async function paintTabs() {
    tabBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === state.tab ? 'true' : 'false'));
    show(listBox, message('Loading...'));
    const want = state.tab;
    try {
      const meal = state.addMeal;
      const node = want === 'recipes' ? await recipesList(meal) : want === 'yesterday' ? await yesterdayList(meal) : await quickList(want, meal);
      if (want === state.tab && meal === state.addMeal && !q.value.trim()) show(listBox, node);
    } catch (e) { show(listBox, message(e.message, 'error')); }
  }

  // Search, scan and the meal filter sit above the lists so a long list never pushes them off screen.
  root.appendChild(h('section', { class: 'screen add' },
    h('form', { class: 'row', role: 'search', onsubmit: (e) => { e.preventDefault(); liveSearch.cancel(); search(true); } },
      q, h('button', { class: 'btn', type: 'submit' }, 'Search')),
    h('div', { class: 'row' }, h('button', { class: 'btn primary scan-btn', type: 'button', onclick: () => go('scan') }, cameraIcon(), 'Scan barcode'),
      h('button', { class: 'btn', type: 'button', onclick: () => go('manual', {}) }, 'Enter manually')),
    barcodeForm(ctx.lookup), mealPick, tabBar, h('div', { class: 'tab-list' }, listBox)));
  paintTabs();
  if (params.focus) root.addEventListener('mounted', () => q.focus());
}

// A list of at most PAGE_SIZE items with a Show more button. build(visibleItems) returns the node for them.
function paged(items, build) {
  const box = h('div');
  let shown = PAGE_SIZE;
  const paint = () => {
    const page = pageOf(items, shown);
    clear(box).appendChild(build(page.items));
    if (page.more) box.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => { shown += PAGE_SIZE; paint(); } }, 'Show more'));
  };
  paint();
  return box;
}

async function quickList(kind, meal) {
  const all = (await api.quick(kind, localDate())).items;
  const items = filterSaved(all, meal);
  if (!items.length) return message(emptyText('favorites', meal, all.length > 0));
  // With "start from my last entry" off a food opens on its label serving, so the row shows that serving too.
  const useLast = state.settings.use_last !== false;
  return paged(items, (page) => h('ul', { class: 'list' }, page.map((it) => foodRow(foodTitle(it.food),
    useLast ? unitText(it.amount, it.unit) + ' - ' + fmtNum(it.kcal, 0) + ' kcal, ' + fmtNum(it.protein, 0) + ' g protein'
      : (it.food.label_text || unitText(it.food.serving_amount, it.food.serving_unit)) + ' - ' + fmtNum(it.food.kcal, 0) + ' kcal, ' + fmtNum(it.food.protein, 0) + ' g protein',
    pickerOf({ food_id: it.food.id, amount: it.amount, unit: it.unit }, chosenMeal())))));
}

// With All the items are grouped under meal headings. With one meal chosen it is a plain list.
async function yesterdayList(meal) {
  const items = filterByMeal((await api.quick('yesterday', localDate())).items, meal);
  if (!items.length) return message(emptyText('yesterday', meal, true));
  const row = (it) => foodRow(foodTitle(it.food), unitText(it.amount, it.unit) + ' - ' + fmtNum(it.kcal, 0) + ' kcal',
    pickerOf({ food_id: it.food.id, amount: it.amount, unit: it.unit }, meal === 'all' ? it.meal : meal));
  if (meal !== 'all') return paged(items, (page) => h('ul', { class: 'list' }, page.map(row)));
  return paged(items, (page) => h('div', null, groupByMeal(page, 'Other').map((g) => h('div', null,
    h('h2', { class: 'group' }, g.label, h('span', null, fmtNum(g.kcal, 0) + ' kcal')),
    h('ul', { class: 'list' }, g.entries.map(row))))));
}

async function recipesList(meal) {
  const all = (await api.meals()).meals;
  const recipes = filterSaved(all, meal);
  if (!recipes.length) return message(emptyText('recipes', meal, all.length > 0));
  return paged(recipes, (page) => h('ul', { class: 'list' }, page.map((m) => {
    const del = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Delete recipe ' + m.name, onclick: async () => {
      if (!window.confirm('Delete the recipe "' + m.name + '"?')) return;
      try { await api.deleteMeal(m.id); await go('add', {}, true); } catch (e) { del.parentNode.appendChild(message(e.message, 'error')); }
    } }, '×');
    return foodRow(m.name, m.items.length + ' items - ' + fmtNum(m.kcal, 0) + ' kcal', () => go('meal', { mealId: m.id, meal: chosenMeal() }), del);
  })));
}

// ---------- lookup result, recipe checklist ----------

async function lookupScreen(root, params) {
  root.appendChild(h('section', { class: 'screen' }, message('Looking up ' + params.code + '...')));
  const r = await api.barcode(params.code);
  if (r.food) { await go('picker', { foodId: r.food.id }, true); return; }
  clear(root);
  root.appendChild(h('section', { class: 'screen' }, h('h1', null, 'Not found'),
    h('p', { class: 'sub' }, r.note || 'No product matched ' + params.code + '.'),
    h('div', { class: 'row wrap' },
      r.can_ask_ai ? h('button', { class: 'btn primary', type: 'button', onclick: () => go('ai', { barcode: params.code }) }, 'Ask Claude') : null,
      h('button', { class: 'btn', type: 'button', onclick: () => go('manual', { barcode: params.code }) }, 'Enter manually'),
      h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back'))));
}

async function mealScreen(root, params) {
  const meal = (await api.meals()).meals.find((m) => m.id === params.mealId);
  if (!meal) throw new Error('Recipe not found');
  const status = h('div', { 'aria-live': 'polite' });
  const mealSel = mealSelect(params.meal || defaultMeal());
  const rows = meal.items.map((it) => {
    const box = h('input', { type: 'checkbox', checked: true, 'aria-label': 'Include ' + it.food.name });
    const amt = h('input', { type: 'text', inputmode: 'decimal', value: it.unit === 'serving' ? servingText(it.amount) : fmtAmount(it.amount), 'aria-label': 'Amount of ' + it.food.name });
    return { it, box, amt, el: h('li', { class: 'item meal-item' }, box, h('span', { class: 'item-title' }, it.food.name), amt, h('span', { class: 'unit' }, unitLabel(it.unit))) };
  });
  async function log() {
    const { items, error } = checkedItems(rows.map((r) => ({ checked: r.box.checked, amount: r.amt.value, food_id: r.it.food_id, unit: r.it.unit, name: r.it.food.name })));
    if (error) { show(status, message(error, 'error')); return; }
    try { await api.logMeal(meal.id, { items, meal: mealSel.value === 'none' ? null : mealSel.value }); await go('today', {}, true); } catch (e) {
      show(status, message(e.message, 'error'));
    }
  }
  root.appendChild(h('section', { class: 'screen' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, meal.name), h('ul', { class: 'list' }, rows.map((r) => r.el)),
    h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel), status,
    h('button', { class: 'btn primary', type: 'button', onclick: log }, 'Log')));
}

// ---------- settings ----------

async function settingsScreen(root) {
  const [s, g, ai, me, cfg] = await Promise.all([api.settings(), api.goals(), api.aiStatus().catch(() => null), api.me(),
    api.authConfig().catch(() => null)]);
  const startSel = select([['today', 'Today'], ['scan', 'Scan'], ['search', 'Search'], ['ai', 'Ask Claude']].map((x) => ({ value: x[0], label: x[1] })),
    s.start_screen, { 'aria-label': 'Start screen' });
  const mealSel = select([{ value: 'none', label: 'Guess from the time' }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))],
    s.default_meal || 'none', { 'aria-label': 'Default meal' });
  const useLast = h('input', { type: 'checkbox', id: 'use-last', checked: s.use_last !== false, 'aria-describedby': 'use-last-help' });
  const confirmAi = h('input', { type: 'checkbox', id: 'confirm-ai', checked: s.confirm_ai !== false, 'aria-describedby': 'confirm-ai-help' });
  const fmtSel = select([{ value: 'fraction', label: 'Fractions (1/2)' }, { value: 'decimal', label: 'Decimals (0.5)' }],
    s.amount_format === 'decimal' ? 'decimal' : 'fraction', { 'aria-label': 'Show servings as' });
  fmtSel.addEventListener('change', () => setAmountFormat(fmtSel.value));  // applies at once; Save keeps it
  const kcal = field('Calories per day', { inputmode: 'decimal', value: fmtAmount(g.kcal) });
  const pcts = [['carb_pct', 'Carbs %'], ['protein_pct', 'Protein %'], ['fat_pct', 'Fat %']].map(([k, label]) => [k, field(label, { inputmode: 'decimal', value: fmtAmount(g[k]) })]);
  const total = h('p', { class: 'sub' });
  const status = h('div', { 'aria-live': 'polite' });
  const vals = () => pcts.map((p) => parseDecimal(p[1].input.value) || 0);
  const paintTotal = () => { total.textContent = 'Split totals ' + fmtNum(pctTotal(...vals()), 2) + '%. It must be 100.'; };
  pcts.forEach((p) => p[1].input.addEventListener('input', paintTotal));
  paintTotal();

  async function save(e) {
    e.preventDefault();
    const k = parseDecimal(kcal.input.value);
    const v = vals();
    if (!k || k <= 0) { show(status, message('Enter calories above zero.', 'error')); return; }
    if (Math.abs(pctTotal(...v) - 100) > 0.01) { show(status, message('Carbs, protein and fat must total 100%.', 'error')); return; }
    try {
      state.settings = await api.saveSettings({ start_screen: startSel.value, default_meal: mealSel.value === 'none' ? null : mealSel.value, use_last: useLast.checked, confirm_ai: confirmAi.checked, amount_format: fmtSel.value });
      setAmountFormat(state.settings.amount_format);
      await api.saveGoals({ kcal: k, carb_pct: v[0], protein_pct: v[1], fat_pct: v[2] });
      show(status, message('Saved.'));
    } catch (err) { show(status, message(err.message, 'error')); }
  }
  root.appendChild(h('section', { class: 'screen' }, h('h1', null, 'Settings'),
    h('form', { onsubmit: save },
      h('label', { class: 'field' }, h('span', null, 'Start screen'), startSel),
      h('div', { class: 'switch-row' },
        h('label', { for: 'use-last' }, useLast, h('span', null, 'Start from my last entry')),
        h('p', { class: 'sub', id: 'use-last-help' }, 'On: a food opens with the amount and unit you used last time. Off: it opens with the label\'s serving.')),
      h('label', { class: 'field' }, h('span', null, 'Default meal'), mealSel),
      h('label', { class: 'field' }, h('span', null, 'Show servings as'), fmtSel),
      h('div', { class: 'switch-row' },
        h('label', { for: 'confirm-ai' }, confirmAi, h('span', null, 'Confirm before using Claude')),
        h('p', { class: 'sub', id: 'confirm-ai-help' }, 'On: you see the request count and estimated cost before anything is sent.')),
      h('h2', null, 'Daily goals'), kcal, h('div', { class: 'grid3' }, pcts.map((p) => p[1])), total, status,
      h('button', { class: 'btn primary', type: 'submit' }, 'Save')),
    h('h2', null, 'Claude'), ai ? renderClaudeSection(ai, me.use_global_ai) : h('p', { class: 'sub' }, 'Claude status is not available.'),
    h('h2', null, 'Saved'), h('p', { class: 'sub' }, 'Favorites, recipes and your own foods, with meal tags.'),
    h('button', { class: 'btn', type: 'button', onclick: () => go('saved') }, 'Open Saved'),
    renderSignIn(cfg, me),
    me.is_admin ? h('div', null, h('h2', null, 'Admin'), h('p', { class: 'sub' }, 'Users, sign-in, Claude and server settings.'),
      h('button', { class: 'btn', type: 'button', onclick: () => go('admin') }, 'Open Admin')) : null,
    renderGuide(),
    h('button', { class: 'btn', type: 'button', onclick: async () => { try { await api.logout(); } catch (e) { /* ignore */ } showLogin(); } }, 'Sign out')));
}

const SCREENS = {
  login: loginScreen, admin: (root) => renderAdmin(root, ctx), today: todayScreen, add: addScreen, lookup: lookupScreen, meal: mealScreen, settings: settingsScreen,
  saved: (root) => renderSaved(root, ctx), editfood: (root, p) => renderFoodForm(root, { edit: p.food }, ctx),
  picker: (root, p) => renderPicker(root, p, ctx),
  scan: (root) => renderScan(root, ctx),
  ai: (root, p) => renderAi(root, p, ctx),
  manual: (root, p) => renderFoodForm(root, { barcode: p.barcode }, ctx),
};

// ---------- boot ----------

(async function boot() {
  try {
    state.user = await api.me();
  } catch (e) {
    if (e.status !== 401) showLogin();  // 401 already showed the login screen
    return;
  }
  await afterLogin();
})();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => {}); });
}
