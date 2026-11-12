import { api, setUnauthorizedHandler } from './api.js';
import { h, clear, select, field, message, show, cameraIcon, sourceBadge } from './dom.js';
import {
  MEALS, MEAL_LABELS, parseDecimal, parseAmount, amountText, servingText, qtyText, setAmountFormat, unitLabel, fmtNum, fmtAmount, groupByMeal, mealGroupsAll, quickLabel, checkedItems, canSaveRecipe, rowAmountText, applyRowPick, draftFits, localDate, progressText, remainingText,
  sentence, matchAmount, newRecipeDraft, recipeAddRow, recipeSetRow, stepsBack, barWidth, debounce, digitsOnly, guessMeal, pctTotal, latestGuard, MEAL_FILTERS, MEAL_FILTER_LABELS, filterByMeal, filterSaved, pageOf, PAGE_SIZE, emptyText,
  DEFAULT_DISPLAY, searchSource, searchAction, searchHint, DESCRIPTION_TEXT, aiFeature, aiFeatureOff, searchSources, startSource,
} from './util.js';
import { microSection, displaySection, microTargets } from './micros.js';
import { viewToggle, dayTable } from './daytable.js';
import { todayView } from './tablemodel.js';
import { renderPicker } from './picker.js';
import { renderScan } from './scan.js';
import { renderAi } from './ai.js';
import { confirmClaude } from './notice.js';
import { renderFoodForm } from './foodform.js';
import { splitChart, macroBar } from './chart.js';
import { renderGuide } from './guide-view.js';
import { renderSetup } from './setup.js';
import { renderAdmin } from './admin.js';
import { renderSaved } from './saved.js';
import { renderRecipe } from './recipe.js';
import { renderRecipes, renderRecipeView } from './recipes.js';
import { renderImport, renderReview, renderMatch } from './recipeflow.js';
import { recipeSubText, notCounted, notCountedText, portionUnits, portionFraction, portionItems, portionNote, portionAmount, autoMatchOn } from './recipeimport.js';
import { renderClaudeSection, renderSignIn } from './claudekey.js';
import { refreshLoggedControl } from './refresh.js';
import { startUpdates } from './update.js';

const main = document.getElementById('main');
const nav = document.getElementById('nav');
const state = { user: null, settings: { start_screen: 'today', default_meal: null, use_last: true, confirm_ai: true, amount_format: 'fraction' }, display: DEFAULT_DISPLAY, cleanup: null, depth: 0, tab: 'favorites', addMeal: null, quickMeal: null, draft: null, recipe: null, source: null, aiSt: null, claude: null,
  importInput: null, importDraft: null, importBase: 0, proposals: {}, selections: {}, matchFocus: null, matchBase: {}, matchMethod: 'search', autoMatch: null };  // Import Recipe and Match Ingredients  // addMeal, source (null = the Default Search Source setting), aiSt (last /api/ai/status) and claude (last Claude estimate) live for the session only
const NAV_OF = { today: 'today', settings: 'settings', admin: 'settings', saved: 'settings', editfood: 'settings',
  recipes: 'recipes', recipeview: 'recipes', recipe: 'recipes', import: 'recipes', importreview: 'recipes', match: 'recipes' };  // every other screen belongs to Add
const FINDER = ['add', 'picker', 'scan', 'lookup', 'manual', 'ai'];  // screens New Recipe and Match Ingredients borrow from Add

// The bottom bar button to mark: params.nav when a screen is opened from another tab, the Recipes tab while a recipe
// borrows the food finder, else the screen's own tab.
function navKey(entry) {
  const p = entry.params || {};
  if (p.nav) return p.nav;
  const r = state.recipe;
  if (r && FINDER.includes(entry.name) && (r.adding || r.picking != null)) return 'recipes';
  return NAV_OF[entry.name] || 'add';
}

const ctx = {
  go,
  back: () => (state.depth > 0 ? history.back() : go('today', {}, true)),
  get settings() { return state.settings; },
  get display() { return state.display; },
  // Saves display switches (micros_open included) and keeps the new values for every screen.
  async saveDisplay(patch) {
    const before = state.display;
    state.display = { ...before, ...patch };
    try { state.display = await api.saveDisplay(patch); } catch (e) { state.display = before; throw e; }
    if ('search_source' in patch) state.source = null;  // a new default applies to Add at once
    return state.display;
  },
  lookup: (code) => go('lookup', { code }),
  // Recipes tab buttons. Import remembers where it started so Save and Continue and Cancel come back to the Recipes tab.
  newRecipe: () => { state.recipe = newRecipeDraft(); return go('recipe', {}); },
  importRecipe: () => { state.importBase = state.depth; return go('import', {}); },
  defaultMeal: () => defaultMeal(),
  // Create Recipe screen hooks. The draft is state.recipe.
  get recipe() { return state.recipe; },
  refresh: () => go('recipe', {}, true),
  addIngredient: () => { state.recipe.adding = true; return go('add', { ingredient: true }); },
  adjustIngredient(i) {
    const r = state.recipe.rows[i];
    state.recipe.adding = false;
    state.recipe.picking = i;
    return go('picker', { foodId: r.food_id, adjust: { index: i }, amount: r.amount, unit: r.unit });
  },
  saved() { state.recipe = null; return ctx.back(); },  // back to the Recipes tab, which lists the new recipe
  // Import Recipe (step 1) and Match Ingredients (step 2). See js/recipeflow.js.
  flow: {
    get input() { return state.importInput || (state.importInput = { kind: 'text', text: '', note: '' }); },
    get draft() { return state.importDraft; },
    set draft(d) { state.importDraft = d; },
    // Save and Continue: the recipe exists now, so the import screens leave history and step 2 opens on top of Add.
    saved(meal) {
      state.importDraft = null;
      state.importInput = null;
      state.autoMatch = autoMatchOn(state.display) ? meal.id : null;  // Auto-Match After Import runs once, on this opening only
      backThen(state.depth - state.importBase, () => go('match', { mealId: meal.id, saved: true }));
    },
    cancel() { state.importDraft = null; state.importInput = null; backThen(state.depth - state.importBase, () => {}); },
    exit() { return ctx.back(); },  // to wherever matching was opened from: Recipes, Add or Saved
    proposals(id) { return state.proposals[id] || (state.proposals[id] = {}); },
    selection(id) { return state.selections[id] || []; },
    setSelection(id, ids) { state.selections[id] = ids; },
    // Match Selected With: search (default) or claude, kept for the session. searchSource is what Search looks in: the Source
    // chosen on Add (else the Default Search Source), as all, off or fdc; Claude estimates are not a database source, so ai means all.
    get method() { return state.matchMethod; },
    set method(m) { state.matchMethod = m === 'claude' ? 'claude' : 'search'; },
    searchSource() { const s = state.source == null ? state.display.search_source : state.source; return s === 'off' || s === 'fdc' ? s : 'all'; },
    // True once for the recipe that was just imported when Auto-Match After Import is on. Held in memory only, so reopening the recipe
    // later, a return from the food finder or a reload never searches again.
    takeAuto(id) { const on = state.autoMatch === id; state.autoMatch = null; return on; },
    takeFocus() { const f = state.matchFocus; state.matchFocus = null; return f; },
    // One visit of Match Ingredients, kept in its history entry, so a return from the food finder is the same visit.
    visit(params) {
      if (!params.visit) {
        params.visit = 'v' + Date.now() + '-' + Math.floor(Math.random() * 1e6);
        const hs = history.state;
        if (hs && hs.name === 'match') history.replaceState({ ...hs, params: { ...hs.params, visit: params.visit } }, '');
      }
      return params.visit;
    },
    // The last saved state of a visit (matchSnapshot): set on opening and by Next, written back by Back.
    base(v) { return state.matchBase[v]; },
    setBase(v, snap) { state.matchBase[v] = snap; return snap; },
    endVisit(v) { delete state.matchBase[v]; },
    // Search or Scan for one ingredient. The finder runs in ingredient mode; picking a food skips the amount screen
    // (autoMatch works the amount out from the recipe line, saves the match and returns to Match Ingredients).
    find(meal, item, how) {
      const src = item.src || {};
      // line: what the recipe says ("1 cup"), from which the amount is worked out once a food is picked (autoMatch).
      const line = item.src ? { amount: src.amount, unit: src.unit } : { amount: item.amount, unit: item.unit };
      state.recipe = { match: { mealId: meal.id, itemId: item.id, amount: item.food ? item.amount : src.amount, unit: item.food ? item.unit : src.unit,
        line, label: src.text || (item.food && item.food.name) || '' }, name: '', meals: [], rows: [], depth: state.depth, adding: true, picking: null };
      state.matchFocus = item.id;
      return how === 'scan' ? go('scan', { autostart: true }) : go('add', { ingredient: true, q: src.name || (item.food && item.food.name) || '' });
    },
  },
  // Recipe row adjust: the picker hands back the chosen amount and unit, then the recipe screen is shown again with its draft.
  async finishAdjust(index, amount, unit, food) {
    const r = state.recipe;
    if (r && r.match) {  // Match Ingredients: save the match, then go back past the finder to the match screen
      await api.matchItem(r.match.mealId, r.match.itemId, { food_id: food.id, amount, unit });
      delete ctx.flow.proposals(r.match.mealId)[r.match.itemId];
      const n = stepsBack(state.depth, r.depth);
      state.recipe = null;
      return history.go(-n);
    }
    if (r && r.picking != null) {  // Create Recipe: a new ingredient comes from the finder, so go back past it to the recipe screen
      r.rows = r.picking >= r.rows.length ? recipeAddRow(r.rows, food, amount, unit) : recipeSetRow(r.rows, r.picking, amount, unit);
      const n = r.adding ? stepsBack(state.depth, r.depth) : 1;
      r.adding = false;
      r.picking = null;
      return history.go(-n);
    }
    if (state.draft) state.draft.rows = applyRowPick(state.draft.rows, index, amount, unit);
    return ctx.back();
  },
};

// ---------- routing ----------

function go(name, params, replace) {
  const d = replace ? state.depth : state.depth + 1;
  const entry = { name, params: params || {}, d };
  if (replace) history.replaceState(entry, ''); else history.pushState(entry, '');
  state.depth = d;
  return render(entry);
}

// Go back n history steps, then run fn once the screen there has started to render.
function backThen(n, fn) {
  if (n <= 0) { fn(); return; }
  const once = () => { window.removeEventListener('popstate', once); setTimeout(fn, 0); };
  window.addEventListener('popstate', once);
  history.go(-n);
}

window.addEventListener('popstate', (e) => {
  const entry = e.state && e.state.name ? e.state : { name: 'today', params: {}, d: 0 };
  state.depth = entry.d || 0;
  render(entry);
});

const guard = latestGuard();

// While a recipe is being built, the ingredient finder (Add with ingredient), lookup, scan, manual and Claude screens lead to the
// picker in "ingredient" mode. Any other screen ends that mode, so a normal Add never hands its pick to a recipe.
function trackRecipeFlow(entry) {
  const r = state.recipe;
  if (!r) return;
  const p = entry.params || (entry.params = {});
  if (entry.name === 'add') r.adding = !!p.ingredient;
  else if (entry.name === 'picker') {
    if (r.adding && !p.adjust && p.entryId == null) {
      p.adjust = { index: r.rows.length };
      r.picking = r.rows.length;
      if (r.match && p.amount == null && r.match.unit) { p.amount = r.match.amount; p.unit = r.match.unit; }  // start from the recipe's own amount
    }
  } else {
    if (!['lookup', 'scan', 'manual', 'ai'].includes(entry.name)) r.adding = false;
    r.picking = null;
  }
}

// Each screen is built in a detached box and swapped in only if no newer render started meanwhile.
async function render(entry) {
  const ticket = guard.next();
  if (state.cleanup) { state.cleanup(); state.cleanup = null; }
  trackRecipeFlow(entry);
  const screen = SCREENS[entry.name] || SCREENS.today;
  const key = navKey(entry);
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
      h('button', { class: 'btn', type: 'button', onclick: () => render(entry) }, 'Try Again')));
  }
  if (!guard.isLatest(ticket)) { if (cleanup) cleanup(); return; }
  state.cleanup = cleanup;
  clear(main).appendChild(box);
  box.dispatchEvent(new Event('mounted'));
  window.scrollTo(0, 0);
  main.focus({ preventScroll: true });
  hideSplash();
}

nav.addEventListener('click', (e) => {
  const b = e.target.closest('button[data-go]');
  if (b) { state.quickMeal = null; go(b.dataset.go, {}, false); }
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
  if (s === 'scan') return go('scan', { autostart: true }, true);
  if (s === 'search') return go('add', { focus: true }, true);
  if (s === 'ai') return go('ai', {}, true);
  return go('today', {}, true);
}

async function afterLogin() {
  try { state.settings = await api.settings(); } catch (e) { /* keep defaults */ }
  try { state.display = await api.display(); } catch (e) { /* keep defaults */ }
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

function foodRow(title, sub, onclick, extra, macros, source) {
  const badge = sourceBadge(source, true);
  return h('li', { class: 'item' },
    h('button', { class: 'item-main', type: 'button', onclick }, h('span', { class: 'item-title' }, title), h('span', { class: 'item-sub' }, sub, badge ? ' ' : null, badge), macros && state.display.show_macro_bar !== false ? macroBar(macros) : null),
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
  } }, user, pass, status, h('button', { class: 'btn primary', type: 'submit' }, 'Sign In'));
  root.appendChild(h('section', { class: 'screen login' }, h('h1', null, 'Macrolog'),
    cfg.local ? form : null,
    cfg.oidc ? h('a', { class: 'btn', href: '/auth/oidc/login' }, 'Sign In With ' + (cfg.oidc_name || 'single sign-on')) : null,
    !cfg.local && !cfg.oidc ? message('Sign-in is not configured on this server.', 'error') : null));
}

// ---------- today ----------

async function todayScreen(root) {
  state.quickMeal = null;
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
  // Opens Add, Scan or Search with this meal chosen. Scan and a barcode lookup keep it through to the picker.
  const quick = (kind, meal) => () => {
    state.quickMeal = meal;
    if (kind === 'scan') return go('scan', { autostart: true });
    return go('add', kind === 'search' ? { focus: true } : {});
  };
  const quickRow = (g) => h('div', { class: 'quick-row', role: 'group', 'aria-label': 'Add to ' + g.label },
    h('button', { class: 'btn', type: 'button', 'aria-label': quickLabel('add', g.meal), onclick: quick('add', g.meal) }, 'Add'),
    h('button', { class: 'btn', type: 'button', 'aria-label': quickLabel('scan', g.meal), onclick: quick('scan', g.meal) }, cameraIcon(), 'Scan'),
    h('button', { class: 'btn', type: 'button', 'aria-label': quickLabel('search', g.meal), onclick: quick('search', g.meal) }, 'Search'));
  const groups = () => mealGroupsAll(d.entries).map((g) => h('div', null,
    h('h2', { class: 'group' }, g.label, h('span', null, fmtNum(g.kcal, 0) + ' kcal')),
    g.entries.length ? h('ul', { class: 'list' }, g.entries.map((e) => entryRow(e, root))) : null,
    g.meal ? quickRow(g) : null, g.entries.length ? saveMealBox(g, status) : null));
  const removeEntry = async (e) => {
    try { await api.deleteEntry(e.id); await go('today', {}, true); } catch (err) { show(status, message(err.message, 'error')); }
  };
  const openEntry = (e) => go('picker', { foodId: e.food_id, entryId: e.id, amount: e.amount, unit: e.unit, meal: e.meal });
  const disp = state.display;
  const micros = microSection(d, disp, (open) => { ctx.saveDisplay({ micros_open: open }).catch(() => {}); });
  const nutrients = disp.show_macros !== false || micros ? h('div', { class: 'nutrients' },
    disp.show_macros !== false ? [h('h2', null, 'Macro Nutrients'), h('div', { class: 'bars' }, bars)] : null, micros,
    micros ? refreshLoggedControl({ scope: 'day:' + d.day, label: 'Refresh Nutrients', quiet: true,
      load: () => api.missingNutrients(d.day), onFinish: () => go('today', {}, true) }).el : null) : null;
  const body = h('div', { class: 'entries-body' });
  const grid = h('div', { class: 'two-col today' });
  const paint = (view) => {
    grid.classList.toggle('table-mode', view === 'table' && d.entries.length > 0);
    clear(body);
    if (!d.entries.length) body.appendChild(message('Tap Add to log your first food.'));
    if (d.entries.length && view === 'table') body.appendChild(dayTable(d.entries, { display: disp, onOpen: openEntry, onDelete: removeEntry }));
    else groups().forEach((g) => body.appendChild(g));
  };
  const view = disp.show_table === false ? 'list' : todayView(disp);
  paint(view);
  grid.append(h('div', { class: 'col-a' }, disp.show_split !== false ? h('div', { class: 'split-box' }, h('h2', null, 'Calorie Split'), splitChart(d)) : null, nutrients),
    h('div', { class: 'col-b' }, h('button', { class: 'btn primary add-food', type: 'button', onclick: () => go('add', {}) }, 'Add Food'),
      d.entries.length && disp.show_table !== false ? viewToggle(view, (v) => { paint(v); ctx.saveDisplay({ today_view: v }).catch(() => {}); }) : null, body, status));
  root.appendChild(h('section', { class: 'screen wide' }, h('h1', null, 'Today'), grid));
}

function entryRow(e, root) {
  const sub = unitText(e.amount, e.unit) + ' - ' + fmtNum(e.kcal, 0) + ' kcal';
  const title = e.brand ? e.name + ' (' + e.brand + ')' : e.name;
  const open = () => go('picker', { foodId: e.food_id, entryId: e.id, amount: e.amount, unit: e.unit, meal: e.meal });
  const del = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + e.name, onclick: async () => {
    try { await api.deleteEntry(e.id); await go('today', {}, true); } catch (err) { show(root.querySelector('[aria-live]'), message(err.message, 'error')); }
  } }, '×');
  if (e.food_id == null) return h('li', { class: 'item' }, h('div', { class: 'item-main' }, h('span', { class: 'item-title' }, title), h('span', { class: 'item-sub' }, sub), state.display.show_macro_bar !== false ? macroBar(e) : null), del);
  return foodRow(title, sub, open, del, e, e.source);
}

// One Save as recipe button per meal group. It opens a checklist of that group's entries, all ticked.
function saveMealBox(g, status) {
  const box = h('div', { class: 'save-meal' });
  const reset = () => show(box, h('button', { class: 'btn', type: 'button', onclick: ask }, 'Save As Recipe'));
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
// quickMeal is set by Today's per meal buttons and lasts until Today is shown again, another tab is tapped or Meal is changed on Add; it never touches addMeal.
const addMeal = () => (state.quickMeal != null ? state.quickMeal : state.addMeal == null ? defaultMeal() : state.addMeal);  // until picked, follows the Default Meal setting or the time of day
const chosenMeal = () => (addMeal() === 'all' ? undefined : addMeal());
const foodTitle = (f) => (f.brand ? f.name + ' (' + f.brand + ')' : f.name);

// params.ingredient: the finder used by Create Recipe. It shows Favorites and Past Foods only. Its Meal choice starts on All and
// is its own (it does not change the meal chosen on Add).
function addScreen(root, params) {
  const ing = !!(params.ingredient && state.recipe);
  const matching = ing && state.recipe.match ? state.recipe.match : null;  // finding a food for one imported ingredient
  let tab = ing ? 'favorites' : state.tab;
  const listBox = h('div', { 'aria-live': 'polite' });
  const q = h('input', { type: 'search', placeholder: 'Search foods', 'aria-label': 'Search foods', enterkeyhint: 'search', autocomplete: 'off' });
  const tabNames = ing ? [['favorites', 'Favorites'], ['recent', 'Past Foods']] : [['favorites', 'Favorites'], ['yesterday', 'Yesterday'], ['recipes', 'Recipes']];
  const tabBar = h('div', { class: 'tabs', role: 'tablist' }, tabNames.map(([k, label]) => h('button', {
    type: 'button', role: 'tab', 'data-tab': k, onclick: () => { tab = k; if (!ing) state.tab = k; q.value = ''; liveSearch.cancel(); paintTabs(); } }, label)));
  let ingMeal = 'all';
  const curMeal = () => (ing ? ingMeal : addMeal());
  const mealSel = select(MEAL_FILTERS.map((m) => ({ value: m, label: MEAL_FILTER_LABELS[m] })), curMeal(), { 'aria-label': 'Meal' });
  mealSel.addEventListener('change', () => { if (ing) ingMeal = mealSel.value; else { state.addMeal = mealSel.value; state.quickMeal = null; } if (!q.value.trim()) paintTabs(); });
  const mealPick = h('label', { class: 'meal-pick' }, h('span', null, 'Meal'), mealSel);
  let searchSeq = 0;
  // Where the search box looks: the Default Search Source setting, then whatever is picked here for the session.
  // Claude is only asked on Search or Enter, never while typing.
  state.source = startSource(state.source, state.display.search_source, state.aiSt);
  const srcSel = select(searchSources(state.aiSt), state.source);
  const srcPick = h('label', { class: 'meal-pick source-pick' }, h('span', null, 'Source'), srcSel);  // the wrapping label names the select
  const srcNote = h('div', { 'aria-live': 'polite' });
  let aiOn = null;  // null until /api/ai/status answers
  // Fresh status on every visit, so a feature the administrator turned off disappears from the Source choice.
  const loadAi = () => api.aiStatus().then((st) => { state.aiSt = st; aiOn = aiFeature(st, 'lookup'); applyFeatures(st); }, () => { aiOn = false; });
  function applyFeatures(st) {
    if (!aiFeatureOff(st, 'lookup')) return;
    const opt = srcSel.querySelector('option[value="ai"]');
    if (opt) opt.remove();
    if (state.source === 'ai') { state.source = 'all'; srcSel.value = 'all'; }
  }
  const paintSource = () => {
    const ai = state.source === 'ai';
    q.placeholder = ai ? 'Describe a food for Claude' : 'Search foods';
    q.setAttribute('aria-label', ai ? 'Describe a food for Claude' : 'Search foods');
    show(srcNote, ai && aiOn === false && !q.value.trim() ? message(searchHint('ai', 'off')) : null);  // with text the list says it
  };
  const paintSearch = () => {
    paintSource();
    const text = q.value.trim();
    if (state.source === 'ai' && state.claude && state.claude.text === text) { showClaude(state.claude); return; }
    if (text) search(false); else paintTabs();
  };
  srcSel.addEventListener('change', async () => {
    state.source = searchSource(srcSel.value);
    liveSearch.cancel();
    if (state.source === 'ai' && aiOn == null) await loadAi();
    paintSearch();
  });

  // remote false while typing (local only), true for Enter or the Search button.
  async function search(remote) {
    const text = q.value.trim();
    const mine = ++searchSeq;
    if (state.source === 'ai' && aiOn == null) await loadAi();
    const act = searchAction(state.source, text, remote, aiOn);
    paintSource();
    if (act.kind === 'tabs') { paintTabs(); return; }
    if (act.kind === 'wait' && state.claude && state.claude.text === text) { showClaude(state.claude); return; }
    tabBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', 'false'));
    if (act.kind === 'barcode') { ctx.lookup(act.code); return; }
    if (act.kind === 'claude') { askClaude(act.text, mine); return; }
    if (act.kind !== 'search') { show(listBox, message(searchHint(state.source, act.kind), act.kind === 'long' ? 'error' : undefined)); return; }
    if (remote) show(listBox, message('Searching...'));
    try {
      const r = (await api.search(text, remote, act.source)).results;
      if (mine !== searchSeq) return;
      const manual = h('button', { class: 'btn', type: 'button', onclick: () => go('manual', {}) }, 'Enter Manually');
      const empty = message(searchHint(act.source, remote ? 'none' : 'press'));
      show(listBox, h('div', null, r.length ? h('ul', { class: 'list' }, r.map((f) => foodRow(foodTitle(f),
        (f.label_text || unitText(f.serving_amount, f.serving_unit)) + ' - ' + fmtNum(f.kcal, 0) + ' kcal',
        () => go('picker', { foodId: f.id }), null, f, f.source))) : empty, r.length ? null : manual));
    } catch (e) { if (mine === searchSeq) show(listBox, message(e.message, 'error')); }
  }

  // One Claude estimate for the typed description, after the usual confirm step. Nothing is saved until the draft is checked.
  async function askClaude(text, mine) {
    if (!(await confirmClaude(ctx.settings, { what: DESCRIPTION_TEXT, chars: text.length }))) {
      if (mine === searchSeq) show(listBox, message(searchHint('ai', 'wait')));
      return;
    }
    if (mine !== searchSeq) return;
    show(listBox, message('Asking Claude...'));
    try {
      const r = await api.aiLookup(text);
      state.claude = { text, r };
      if (mine === searchSeq) showClaude(state.claude);
    } catch (e) { if (mine === searchSeq) show(listBox, message(e.message, 'error')); }
  }

  function showClaude({ r }) {
    const d = r.draft;
    const kcal = d.kcal == null ? '' : ' - ' + fmtNum(d.kcal, 0) + ' kcal';
    const open = () => go('ai', { draft: d, warnings: r.warnings, cost: r.cost });
    tabBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', 'false'));
    show(listBox, h('div', null, h('ul', { class: 'list' }, foodRow(foodTitle({ name: d.name || 'Unnamed food', brand: d.brand }),
      (d.label_text || unitText(d.serving_amount, d.serving_unit)) + kcal, open, null, d, 'ai')),
    h('p', { class: 'sub' }, 'Values are estimates from Claude. Tap the result to check and save it.')));
  }
  const liveSearch = debounce(() => search(false), 400);
  q.addEventListener('input', liveSearch);

  async function paintTabs() {
    tabBar.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === tab ? 'true' : 'false'));
    show(listBox, message('Loading...'));
    const want = tab;
    try {
      const meal = curMeal();
      const node = want === 'recipes' ? await recipesList(meal) : want === 'yesterday' ? await yesterdayList(meal) : await quickList(want, meal);
      if (want === tab && meal === curMeal() && !q.value.trim()) show(listBox, node);
    } catch (e) { show(listBox, message(e.message, 'error')); }
  }

  // Enter Manually and Scan Barcode, Search, Source and the meal filter sit above the lists, in that order, so a long list never pushes them off screen.
  root.appendChild(h('section', { class: 'screen wide add' },
    ing ? h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')) : null,
    ing ? h('h1', null, matching ? 'Find Ingredient' : 'Add Ingredient') : null,
    matching && matching.label ? h('p', { class: 'sub' }, 'For: ' + matching.label) : null,
    h('div', { class: 'row add-scan' },
      h('button', { class: 'btn', type: 'button', onclick: () => go('manual', {}) }, 'Enter Manually'),
      h('button', { class: 'btn primary scan-btn', type: 'button', onclick: () => go('scan', { autostart: true }) }, cameraIcon(), 'Scan Barcode')),
    h('form', { class: 'row add-search', role: 'search', onsubmit: (e) => { e.preventDefault(); liveSearch.cancel(); search(true); } },
      q, h('button', { class: 'btn', type: 'submit' }, 'Search')),
    srcPick, srcNote,
    mealPick, tabBar, h('div', { class: 'tab-list' }, listBox)));
  if (state.source === 'ai' && state.claude) q.value = state.claude.text;  // back from the draft: the estimate is still here, no second request
  if (matching && params.q && state.source !== 'ai') { q.value = params.q; search(true); loadAi(); }  // the ingredient's name, searched at once
  else if (state.source === 'ai') loadAi().then(paintSearch); else { paintTabs(); loadAi(); }
  if (params.focus) root.addEventListener('mounted', () => setTimeout(() => q.focus(), 0));  // after render() moves focus to main
}

// A list of at most PAGE_SIZE items with a Show more button. build(visibleItems) returns the node for them.
function paged(items, build) {
  const box = h('div');
  let shown = PAGE_SIZE;
  const paint = () => {
    const page = pageOf(items, shown);
    clear(box).appendChild(build(page.items));
    if (page.more) box.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => { shown += PAGE_SIZE; paint(); } }, 'Show More'));
  };
  paint();
  return box;
}

// Favorites are filtered by their meal tags. Past Foods (recent) are filtered by the server: only foods logged as that meal, plus
// foods never logged with a meal, newest first.
async function quickList(kind, meal) {
  const all = (await api.quick(kind, localDate(), meal)).items;
  const items = kind === 'recent' ? all : filterSaved(all, meal);
  if (!items.length) return message(emptyText(kind === 'recent' ? 'recent' : 'favorites', meal, kind === 'recent' || all.length > 0));
  // With "start from my last entry" off a food opens on its label serving, so the row shows that serving too.
  const useLast = state.settings.use_last !== false;
  return paged(items, (page) => h('ul', { class: 'list' }, page.map((it) => foodRow(foodTitle(it.food),
    useLast ? unitText(it.amount, it.unit) + ' - ' + fmtNum(it.kcal, 0) + ' kcal, ' + fmtNum(it.protein, 0) + ' g protein'
      : (it.food.label_text || unitText(it.food.serving_amount, it.food.serving_unit)) + ' - ' + fmtNum(it.food.kcal, 0) + ' kcal, ' + fmtNum(it.food.protein, 0) + ' g protein',
    pickerOf({ food_id: it.food.id, amount: it.amount, unit: it.unit }, chosenMeal()), null, it.food, it.food.source))));
}

// With All the items are grouped under meal headings. With one meal chosen it is a plain list.
async function yesterdayList(meal) {
  const items = filterByMeal((await api.quick('yesterday', localDate())).items, meal);
  if (!items.length) return message(emptyText('yesterday', meal, true));
  const row = (it) => foodRow(foodTitle(it.food), unitText(it.amount, it.unit) + ' - ' + fmtNum(it.kcal, 0) + ' kcal',
    pickerOf({ food_id: it.food.id, amount: it.amount, unit: it.unit }, meal === 'all' ? it.meal : meal), null, it.food, it.food.source);
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
    const open = () => go('meal', { mealId: m.id, meal: chosenMeal() });
    return foodRow(m.name, recipeSubText(m, fmtNum(m.kcal, 0)), open, del);
  })));
}

// ---------- lookup result, recipe checklist ----------

async function lookupScreen(root, params) {
  root.appendChild(h('section', { class: 'screen' }, message('Looking up ' + params.code + '...')));
  const r = await api.barcode(params.code);
  if (r.food) { await go('picker', state.quickMeal != null ? { foodId: r.food.id, meal: state.quickMeal } : { foodId: r.food.id }, true); return; }
  clear(root);
  root.appendChild(h('section', { class: 'screen' }, h('h1', null, 'Not Found'),
    h('p', { class: 'sub' }, sentence(r.note) || 'No product matched ' + params.code + '.'),
    h('div', { class: 'row wrap' },
      r.can_ask_ai ? h('button', { class: 'btn primary', type: 'button', onclick: () => go('ai', { barcode: params.code }) }, 'Ask Claude') : null,
      h('button', { class: 'btn', type: 'button', onclick: () => go('manual', { barcode: params.code }) }, 'Enter Manually'),
      h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back'))));
}

// The log checklist of a recipe. How much of the recipe (params.amount and params.unit: servings, % of the recipe or a
// yield unit; older callers send params.servings) sets the starting amounts. Changing it scales every row, keeping edits.
async function mealScreen(root, params) {
  const found = (await api.meals()).meals.find((m) => m.id === params.mealId);
  if (!found) throw new Error('Recipe not found');
  const units = portionUnits(found);
  const draft = draftFits(state.draft, found.id, state.depth, portionItems(found, 1).length) ? state.draft : null;
  state.draft = null;
  const start = draft && draft.portion ? draft.portion
    : { amount: params.amount != null ? params.amount : params.servings != null ? params.servings : 1, unit: params.unit || 'serving' };
  let unit = units.some((u) => u.unit === start.unit) ? start.unit : 'serving';
  let pf = portionFraction(found, start.amount, unit);
  if (pf.error) { unit = 'serving'; pf = portionFraction(found, 1, unit); }
  let frac = pf.fraction;
  let shareAmount = pf.amount;
  const meal = { ...found, items: portionItems(found, frac) };  // skipped ingredients are left out
  const status = h('div', { 'aria-live': 'polite' });
  const mealSel = mealSelect(params.meal || defaultMeal());
  if (draft && draft.meal !== undefined) mealSel.value = draft.meal;
  const amountBox = field('Amount', { inputmode: 'decimal', autocomplete: 'off', value: qtyText(shareAmount, unit) });
  const unitSel = select(units.map((u) => ({ value: u.unit, label: u.label })), unit, { 'aria-label': 'Amount unit' });
  const note = h('p', { class: 'sub', 'aria-live': 'polite' }, portionNote(found, shareAmount, unit));
  const rows = meal.items.map((it, i) => {
    const d = draft ? draft.rows[i] : null;
    const row = { it, unit: d ? d.unit : it.unit };
    row.num = d ? parseAmount(d.amount) : it.amount;
    row.box = h('input', { type: 'checkbox', checked: d ? d.checked : true, 'aria-label': 'Include ' + it.food.name });
    row.amt = h('input', { type: 'text', inputmode: 'decimal', value: d ? d.amount : rowAmountText(it.amount, it.unit), 'aria-label': 'Amount of ' + it.food.name });
    row.amt.addEventListener('input', () => { row.num = parseAmount(row.amt.value); });
    row.unitEl = h('span', { class: 'unit' }, unitLabel(row.unit));
    const name = h('button', { class: 'item-name', type: 'button', 'aria-label': 'Adjust ' + it.food.name, onclick: () => adjust(i) },
      h('span', { class: 'item-name-text' }, it.food.name), h('span', { class: 'item-name-hint', 'aria-hidden': 'true' }, 'Adjust \u203A'));
    row.el = h('li', { class: 'item meal-item' }, row.box, name, row.amt, row.unitEl);
    return row;
  });
  // A new amount or unit for the recipe scales every row by the same factor, so amounts changed by hand keep their ratio.
  function rescale() {
    const r = portionFraction(found, amountBox.input.value, unitSel.value);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    show(status, null);
    const k = r.fraction / frac;
    frac = r.fraction;
    shareAmount = r.amount;
    unit = unitSel.value;
    rows.forEach((x) => { if (x.num != null) { x.num = Math.round(x.num * k * 10000) / 10000; x.amt.value = rowAmountText(x.num, x.unit); } });
    note.textContent = portionNote(found, shareAmount, unit);
  }
  amountBox.input.addEventListener('change', rescale);
  unitSel.addEventListener('change', () => {
    // Switching units keeps the same share of the recipe: 1 of 4 servings becomes 25% or 300 g of 1200 g.
    amountBox.input.value = qtyText(portionAmount(found, frac, unitSel.value), unitSel.value);
    rescale();
  });
  // Open the picker for one ingredient. The screen is rebuilt on return, so every row is saved first.
  function adjust(i) {
    const r = rows[i];
    state.draft = { mealId: meal.id, depth: state.depth, meal: mealSel.value, portion: { amount: shareAmount, unit },
      rows: rows.map((x) => ({ checked: x.box.checked, amount: x.amt.value, unit: x.unit })) };
    const a = parseAmount(r.amt.value);
    go('picker', { foodId: r.it.food_id, adjust: { index: i }, ...(a != null && a > 0 ? { amount: a, unit: r.unit } : { unit: r.unit }) });
  }
  async function log() {
    const { items, error } = checkedItems(rows.map((r) => ({ checked: r.box.checked, amount: r.amt.value, food_id: r.it.food_id, unit: r.unit, name: r.it.food.name })));
    if (error) { show(status, message(error, 'error')); return; }
    try { await api.logMeal(meal.id, { items, meal: mealSel.value === 'none' ? null : mealSel.value }); await go('today', {}, true); } catch (e) {
      show(status, message(e.message, 'error'));
    }
  }
  root.appendChild(h('section', { class: 'screen' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, meal.name),
    h('div', { class: 'grid2 recipe-log' }, amountBox, h('label', { class: 'field' }, h('span', null, 'Of the recipe'), unitSel)),
    note,
    h('ul', { class: 'list' }, rows.map((r) => r.el)),
    notCounted(found) ? h('p', { class: 'sub not-counted' }, notCountedText(notCounted(found))) : null,
    h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel), status,
    h('button', { class: 'btn primary', type: 'button', onclick: log }, 'Log')));
}

// ---------- Match Ingredients: a picked food goes straight back ----------

// Instead of the amount screen: the amount and unit come from the recipe line (util.js matchAmount). When they cannot be
// worked out, or the line has no amount, the food is attached with one label serving and flagged Check Amount, and the
// row on Match Ingredients asks for the amount. Then back past the finder to Match Ingredients.
async function autoMatch(root, params) {
  const r = state.recipe;
  const m = r.match;
  root.appendChild(h('section', { class: 'screen' }, message('Matching...')));
  const food = await api.food(params.foodId);
  const label = food.units[0];
  const pick = matchAmount(food.units, m.line && m.line.amount, m.line && m.line.unit) || { amount: label.default_amount, unit: label.unit, check: true };
  await api.matchItem(m.mealId, m.itemId, { food_id: food.id, amount: pick.amount, unit: pick.unit, ...(pick.check ? { check: true } : {}) });
  delete ctx.flow.proposals(m.mealId)[m.itemId];
  const n = stepsBack(state.depth, r.depth);
  state.recipe = null;
  history.go(-n);
}

// ---------- settings ----------

async function settingsScreen(root) {
  const [s, g, ai, me, cfg, mg, disp] = await Promise.all([api.settings(), api.goals(), api.aiStatus().catch(() => null), api.me(),
    api.authConfig().catch(() => null), api.microGoals(), api.display()]);
  state.display = disp;
  const micro = microTargets(mg.micros);
  const starts = [['today', 'Today'], ['scan', 'Scan'], ['search', 'Search'], ['ai', 'Ask Claude']]
    .filter((x) => x[0] !== 'ai' || s.start_screen === 'ai' || !aiFeatureOff(ai, 'label'));  // label reading turned off by the administrator
  const startSel = select(starts.map((x) => ({ value: x[0], label: x[1] })), s.start_screen, { 'aria-label': 'Start screen' });
  const mealSel = select([{ value: 'none', label: 'Guess from the time' }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))],
    s.default_meal || 'none', { 'aria-label': 'Default meal' });
  const useLast = h('input', { type: 'checkbox', id: 'use-last', checked: s.use_last !== false, 'aria-describedby': 'use-last-help' });
  const confirmAi = h('input', { type: 'checkbox', id: 'confirm-ai', checked: s.confirm_ai !== false, 'aria-describedby': 'confirm-ai-help' });
  const fmtSel = select([{ value: 'fraction', label: 'Fractions (1/2)' }, { value: 'decimal', label: 'Decimals (0.5)' }],
    s.amount_format === 'decimal' ? 'decimal' : 'fraction', { 'aria-label': 'Show amounts as', 'aria-describedby': 'amount-format-help' });
  fmtSel.addEventListener('change', () => setAmountFormat(fmtSel.value));  // applies at once; Save keeps it
  const kcal = field('Calories per day', { inputmode: 'decimal', value: fmtAmount(g.kcal) });
  const pcts = [['carb_pct', 'Carbs %'], ['protein_pct', 'Protein %'], ['fat_pct', 'Fat %']].map(([k, label]) => [k, field(label, { inputmode: 'decimal', value: fmtAmount(g[k]) })]);
  const total = h('p', { class: 'sub' });
  const status = h('div', { 'aria-live': 'polite' });
  const dispStatus = h('div', { 'aria-live': 'polite' });
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
    const mt = micro.read();
    if (mt.error) { show(status, message(mt.error, 'error')); return; }
    try {
      state.settings = await api.saveSettings({ start_screen: startSel.value, default_meal: mealSel.value === 'none' ? null : mealSel.value, use_last: useLast.checked, confirm_ai: confirmAi.checked, amount_format: fmtSel.value });
      setAmountFormat(state.settings.amount_format);
      await api.saveGoals({ kcal: k, carb_pct: v[0], protein_pct: v[1], fat_pct: v[2] });
      await api.saveMicroGoals(mt.targets);
      show(status, message('Saved.'));
    } catch (err) { show(status, message(err.message, 'error')); }
  }
  root.appendChild(h('section', { class: 'screen wide' }, h('h1', null, 'Settings'), h('div', { class: 'two-col' },
    h('form', { class: 'col-a', onsubmit: save },
      h('label', { class: 'field' }, h('span', null, 'Start screen'), startSel),
      h('div', { class: 'switch-row' },
        h('label', { for: 'use-last' }, useLast, h('span', null, 'Start from my last entry')),
        h('p', { class: 'sub', id: 'use-last-help' }, 'On: a food opens with the amount and unit you used last time. Off: it opens with the label\'s serving.')),
      h('label', { class: 'field' }, h('span', null, 'Default meal'), mealSel),
      h('label', { class: 'field' }, h('span', null, 'Show amounts as'), fmtSel),
      h('p', { class: 'sub', id: 'amount-format-help' }, 'Fractions apply to servings, cups, spoons and counts. Grams, millilitres, ounces and pounds always show decimals.'),
      h('div', { class: 'switch-row' },
        h('label', { for: 'confirm-ai' }, confirmAi, h('span', null, 'Confirm before using Claude')),
        h('p', { class: 'sub', id: 'confirm-ai-help' }, 'On: you see the request count and estimated cost before anything is sent.')),
      h('h2', null, 'Daily Goals'), kcal, h('div', { class: 'grid3' }, pcts.map((p) => p[1])), total, micro.node, status,
      h('button', { class: 'btn primary', type: 'submit' }, 'Save')),
    h('div', { class: 'col-b' },
    displaySection(disp, searchSources(ai), async (patch) => {
      try { const d = await ctx.saveDisplay(patch); clear(dispStatus); return d; } catch (err) { show(dispStatus, message(err.message, 'error')); throw err; }
    }), dispStatus,
    h('h2', null, 'Claude'), ai ? renderClaudeSection(ai, me.use_global_ai) : h('p', { class: 'sub' }, 'Claude status is not available.'),
    h('h2', null, 'Saved'), h('p', { class: 'sub' }, 'Favorites, recipes and your own foods, with meal tags.'),
    h('button', { class: 'btn', type: 'button', onclick: () => go('saved') }, 'Open Saved'),
    h('p', { class: 'sub' }, 'Fill blank nutrients of every food you have logged from where it came from. It never changes values that are already there.'),
    refreshLoggedControl({ scope: 'all', label: 'Refresh All Logged Foods', load: () => api.missingNutrients() }).el,
    renderSignIn(cfg, me),
    me.is_admin ? h('div', null, h('h2', null, 'Admin'), h('p', { class: 'sub' }, 'Users, sign-in, Claude and server settings.'),
      h('button', { class: 'btn', type: 'button', onclick: () => go('admin') }, 'Open Admin')) : null,
    renderGuide(),
    h('button', { class: 'btn', type: 'button', onclick: async () => { try { await api.logout(); } catch (e) { /* ignore */ } showLogin(); } }, 'Sign Out')))));
}

const SCREENS = {
  login: loginScreen, admin: (root) => renderAdmin(root, ctx), today: todayScreen, add: addScreen, lookup: lookupScreen, meal: mealScreen, settings: settingsScreen,
  saved: (root) => renderSaved(root, ctx),
  recipes: (root) => renderRecipes(root, ctx),
  recipeview: (root, p) => renderRecipeView(root, p, ctx),
  recipe: (root) => { if (!state.recipe) state.recipe = newRecipeDraft(); state.recipe.depth = state.depth; return renderRecipe(root, ctx); }, editfood: (root, p) => renderFoodForm(root, { edit: p.food }, ctx),
  picker: (root, p) => (state.recipe && state.recipe.match && p.adjust && p.entryId == null ? autoMatch(root, p) : renderPicker(root, p, ctx)),
  scan: (root, p) => { const auto = !!p.autostart; p.autostart = false; return renderScan(root, ctx, { autostart: auto }); },
  ai: (root, p) => renderAi(root, p, ctx),
  import: (root) => renderImport(root, ctx),
  importreview: (root) => renderReview(root, ctx),
  match: (root, p) => { if (state.recipe && state.recipe.match) state.recipe = null; return renderMatch(root, p, ctx); },
  manual: (root, p) => renderFoodForm(root, { barcode: p.barcode }, ctx),
};

// ---------- boot ----------

// Fade out the launch splash once the first screen is ready (or has failed), then remove it.
function hideSplash() {
  const el = document.getElementById('splash');
  if (!el) return;
  el.classList.add('done');
  setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, 300);
}

(async function boot() {
  try {
    state.user = await api.me();
  } catch (e) {
    if (e.status !== 401) showLogin();  // 401 already showed the login screen
    hideSplash();
    return;
  }
  await afterLogin();
  hideSplash();
})();

startUpdates();
