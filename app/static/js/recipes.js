// Recipes tab: New Recipe, Import Recipe and the list of my recipes, plus one recipe's screen with Log and the edit tools
// from Saved. Matching is optional: a recipe with unmatched ingredients opens and logs like any other.
import { api } from './api.js';
import { h, clear, field, message, show, select } from './dom.js';
import { MEALS, MEAL_LABELS, fmtNum, pageOf, PAGE_SIZE, stepsCheck, amountMemo, SAVED_FILTERS, SAVED_FILTER_LABELS, filterSavedItems,
  RECIPE_SORTS, RECIPE_SORT_LABELS, sortRecipes, sentence, RECIPE_OWNERS, RECIPE_OWNER_LABELS, recipeOwner, filterRecipeOwner, ownerText,
  ownerEmptyText, groupRecipesByMeal, pageGroups } from './util.js';
import { recipeListSub, notCounted, notCountedText, servingsText, perServingText, tagsText, portionUnits, portionFraction, portionAmount, yieldText } from './recipeimport.js';
import { servingSizeEditor } from './servingsize.js';
import { ingredientSection } from './ingrows.js';
import { sourceNode } from './recipeflow.js';
import { chips, renameRecipe, deleteRecipe } from './saved.js';
import { stepsList, stepsEditor } from './steps.js';
import { deletedHint, deletedTitle, daysLeftText, deleteForeverConfirm, restoredText, purgedText, sortDeleted, withoutDeleted } from './trash.js';
import { closeUndo } from './undo.js';
import { loadPhotoConfig, photosOn, recipeImage, photoHero, choosePhoto } from './photo.js';
import { summaryParts, cardChips, cardLabel, cardGridClass, cardMenuItems, menuLabel } from './recipecards.js';
import { menuButton } from './menu.js';

// Steps with Edit Steps: the editor works on a copy, Save Steps sends it (PATCH steps), Cancel drops it.
function stepsSection(meal) {
  const box = h('div');
  const status = h('div', { 'aria-live': 'polite' });
  function view(focusEdit) {
    const edit = h('button', { class: 'btn', type: 'button', onclick: editMode }, meal.steps.length ? 'Edit Steps' : 'Add Steps');
    show(box, h('div', null, stepsList(meal.steps), edit));
    if (focusEdit) edit.focus();
  }
  function editMode() {
    const draft = { steps: meal.steps.slice() };
    if (!draft.steps.length) draft.steps.push('');
    const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      const r = stepsCheck(draft.steps);
      if (r.error) { show(status, message(r.error, 'error')); return; }
      save.disabled = true;
      try { meal.steps = (await api.patchMeal(meal.id, { steps: r.steps })).steps; show(status, message('Steps saved.')); view(true); } catch (e) {
        save.disabled = false;
        show(status, message(e.message, 'error'));
      }
    } }, 'Save Steps');
    show(box, h('div', null, stepsEditor(draft), h('div', { class: 'row wrap' }, save,
      h('button', { class: 'btn ghost', type: 'button', onclick: () => { show(status, null); view(true); } }, 'Cancel'))));
    const first = box.querySelector('textarea');
    if (first) first.focus();
  }
  view(false);
  return h('div', null, box, status);
}

// One recipe card: the photo or placeholder on the left, the title, the summary and the chips on the right, the whole card
// one button that opens the recipe, and the menu button at the bottom right. act(key, meal, card) runs a menu action.
function recipeCard(m, open, act) {
  const card = h('li', { class: 'rcard' });
  const chipList = cardChips(m);
  card.appendChild(h('button', { class: 'rcard-open', type: 'button', 'aria-label': cardLabel(m), onclick: () => open(m) },
    recipeImage(m, 'rcard-img'),
    h('span', { class: 'rcard-body' },
      h('span', { class: 'rcard-title' }, m.name),
      h('span', { class: 'rcard-sum' }, summaryParts(m).flatMap((t, i) => [i ? ' · ' : null, h('span', { class: 'nowrap' }, t)])),
      // The bottom row: chips on the left, the menu button (outside this button) at the right edge.
      h('span', { class: 'rcard-chips' }, chipList.map((c) => h('span', { class: 'tag tag-' + c.kind }, c.label))))));
  card.appendChild(menuButton(card, cardMenuItems(m, photosOn()), menuLabel(m), (key) => act(key, m, card)));
  return card;
}

// The chosen meal filter and sort stay for the session (this module lives as long as the page); the search text does not.
const listView = { meal: 'all', sort: 'name', deletedOpen: false };

// ctx: { go, back, newRecipe(), importRecipe(), defaultMeal(), display, saveDisplay(patch) }
// The owner filter (Mine, Shared With Me, All) is the Display setting recipe_owner, saved when it changes.
export async function renderRecipes(root, ctx) {
  const [list, trash] = await Promise.all([api.meals('all'), api.deletedMeals().catch(() => ({ meals: [] })), loadPhotoConfig()]);
  let all = list.meals;
  let owner = recipeOwner(ctx.display && ctx.display.recipe_owner);
  const listBox = h('div');
  let shown = PAGE_SIZE;
  let query = '';
  const open = (m) => ctx.go('recipeview', { mealId: m.id });
  const status = h('div', { class: 'cards-status', 'aria-live': 'polite' });
  // Menu actions. A failure shows above the list; Delete and a new photo repaint from fresh data.
  async function act(key, m, card) {
    show(status, null);
    const menuBtn = () => { const b = listBox.querySelector('[data-id="' + m.id + '"] .card-menu-btn'); if (b) b.focus(); };
    try {
      if (key === 'log') await ctx.go('recipeview', { mealId: m.id, focus: 'log' });
      else if (key === 'cooking') await ctx.go('cooking', { mealId: m.id });
      else if (key === 'duplicate') { const d = await api.duplicateMeal(m.id); await ctx.go('recipeview', { mealId: d.id }); }
      else if (key === 'delete') { if (await deleteRecipe(m, () => ctx.repaint())) await ctx.repaint(); else card.querySelector('.card-menu-btn').focus(); }
      else if (key === 'photo') {
        if (await choosePhoto(m, 'meal', (t) => show(status, message(t)))) { show(status, message('Photo saved.')); paint(); menuBtn(); }
        else card.querySelector('.card-menu-btn').focus();
      }
    } catch (e) { show(status, message(e.message, 'error')); }
  }
  const row = (m) => { const c = recipeCard(m, open, act); c.setAttribute('data-id', String(m.id)); return c; };
  const grid = (items) => h('ul', { class: cardGridClass(photosOn()) }, items.map(row));
  const q = h('input', { type: 'search', placeholder: 'Search recipes', 'aria-label': 'Search recipes', autocomplete: 'off', enterkeyhint: 'search' });
  const sortSel = select(RECIPE_SORTS.map((s) => ({ value: s, label: RECIPE_SORT_LABELS[s] })), listView.sort, { 'aria-label': 'Sort recipes' });
  const filterBox = h('div', { class: 'chips', role: 'group', 'aria-label': 'Meal filter' });
  const paintChips = () => filterBox.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.meal === listView.meal ? 'true' : 'false'));
  for (const m of SAVED_FILTERS) {
    filterBox.appendChild(h('button', { class: 'chip', type: 'button', 'data-meal': m, onclick: () => { listView.meal = m; shown = PAGE_SIZE; paintChips(); paint(); } }, SAVED_FILTER_LABELS[m]));
  }
  paintChips();
  const ownerBox = h('div', { class: 'chips', role: 'group', 'aria-label': 'Owner filter' });
  const paintOwner = () => ownerBox.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.owner === owner ? 'true' : 'false'));
  for (const o of RECIPE_OWNERS) {
    ownerBox.appendChild(h('button', { class: 'chip', type: 'button', 'data-owner': o, onclick: () => {
      owner = o; shown = PAGE_SIZE; paintOwner(); paint();
      if (ctx.saveDisplay) ctx.saveDisplay({ recipe_owner: o }).catch(() => {});
    } }, RECIPE_OWNER_LABELS[o]));
  }
  paintOwner();
  q.addEventListener('input', () => { query = q.value; shown = PAGE_SIZE; paint(); });
  sortSel.addEventListener('change', () => { listView.sort = sortSel.value; shown = PAGE_SIZE; paint(); });
  function paint() {
    clear(listBox);
    const mine = filterRecipeOwner(all, owner);
    if (!mine.length) { listBox.appendChild(message(ownerEmptyText(owner))); return; }
    const items = sortRecipes(filterSavedItems(mine, query, listView.meal, (r) => r.name), listView.sort);
    if (!items.length) { listBox.appendChild(h('p', { class: 'sub', role: 'status' }, sentence('No recipes match your search'))); return; }
    let more;
    if (ctx.display && ctx.display.group_recipes === false) {
      const page = pageOf(items, shown);
      more = page.more;
      listBox.appendChild(grid(page.items));
    } else {
      const page = pageGroups(groupRecipesByMeal(items, listView.meal), shown);
      more = page.more > 0;
      for (const g of page.groups) listBox.appendChild(h('div', { class: 'recipe-group' }, h('h2', { class: 'group' }, g.label), grid(g.items)));
    }
    if (more) listBox.appendChild(h('button', { class: 'btn show-more', type: 'button', onclick: () => { shown += PAGE_SIZE; paint(); } }, 'Show More'));
  }
  paint();
  const deleted = recentlyDeleted(trash, async () => { all = (await api.meals('all')).meals; paint(); });
  root.appendChild(h('section', { class: 'screen recipes wide' }, h('h1', null, 'Recipes'),
    h('div', { class: 'row wrap recipes-actions' },
      h('button', { class: 'btn primary', type: 'button', onclick: ctx.newRecipe }, 'New Recipe'),
      h('button', { class: 'btn', type: 'button', onclick: ctx.importRecipe }, 'Import Recipe')),
    h('p', { class: 'sub' }, 'Tap a recipe to log or edit it. Ingredients that are not matched are not counted.'),
    h('div', { class: 'saved-filter', role: 'search' }, q, ownerBox, filterBox, h('label', { class: 'meal-pick' }, h('span', null, 'Sort'), sortSel)),
    status, listBox, deleted));
}

// Recently Deleted at the bottom of the Recipes tab: my deleted recipes, newest first, with days left, Restore and Delete
// Forever (asks first). A collapsible section shown only when something is there. restored() repaints the recipe list.
function recentlyDeleted(trash, restored) {
  let items = sortDeleted(trash.meals);
  const days = trash.purge_days;
  const status = h('div', { 'aria-live': 'polite' });
  const listEl = h('ul', { class: 'list deleted-list' });
  const summary = h('summary', null, '');
  const box = h('details', { class: 'more recently-deleted', id: 'recently-deleted' }, summary,
    h('p', { class: 'sub' }, deletedHint(days)), listEl, status);
  box.open = listView.deletedOpen;
  box.addEventListener('toggle', () => { listView.deletedOpen = box.open; });
  const wrap = h('div', null, box);
  // After a row leaves, focus goes to the same place in the list, else the summary, else main.
  function refocus(index) {
    const btns = listEl.querySelectorAll('.deleted-restore');
    const next = btns[Math.min(index, btns.length - 1)];
    if (next) next.focus(); else if (!box.hidden) summary.focus(); else document.getElementById('main').focus({ preventScroll: true });
  }
  function drop(id) {
    const index = items.findIndex((m) => m.id === id);
    items = withoutDeleted(items, id);
    paintList();
    refocus(index);
  }
  const row = (m) => {
    const restore = h('button', { class: 'btn deleted-restore', type: 'button', 'aria-label': 'Restore ' + m.name, onclick: async () => {
      restore.disabled = true;
      try {
        await api.restoreMeal(m.id);
        closeUndo();
        show(status, message(restoredText(m.name)));
        await restored();
        drop(m.id);
      } catch (e) { restore.disabled = false; show(status, message(e.message, 'error')); }
    } }, 'Restore');
    const forever = h('button', { class: 'btn danger-text', type: 'button', 'aria-label': 'Delete ' + m.name + ' Forever', onclick: async () => {
      if (!window.confirm(deleteForeverConfirm(m.name))) return;
      forever.disabled = true;
      try {
        await api.purgeMeal(m.id);
        closeUndo();
        show(status, message(purgedText(m.name)));
        drop(m.id);
      } catch (e) { forever.disabled = false; show(status, message(e.message, 'error')); }
    } }, 'Delete Forever');
    return h('li', { class: 'item deleted-item' },
      h('div', { class: 'item-main' }, h('span', { class: 'item-title' }, m.name),
        h('span', { class: 'item-sub' }, daysLeftText(m.days_left) + ' · ' + recipeListSub(m, fmtNum(m.kcal, 0)))),
      h('div', { class: 'row deleted-actions' }, restore, forever));
  };
  function paintList() {
    summary.textContent = deletedTitle(items.length);
    clear(listEl);
    items.forEach((m) => listEl.appendChild(row(m)));
    box.hidden = !items.length;
  }
  paintList();
  return wrap;
}

// params: { mealId, saved? (just saved by Import: a Saved note, the Ingredients in view and Auto-Match After Import once),
// focus? ('log' or 'ingredients') }. Log (meal and how much: servings, % of the recipe or a yield unit, worked out by the server);
// the ingredients, matched in place (js/ingrows.js); meal tags, Rename, Steps, Serving Size and Delete Recipe.
// The checklist with Adjust is only for logging a recipe from Add.
export async function renderRecipeView(root, params, ctx) {
  const [meal, st] = await Promise.all([api.meal(params.mealId), api.aiStatus().catch(() => ({ enabled: false })), loadPhotoConfig()]);
  const status = h('div', { 'aria-live': 'polite' });
  const mealSel = select([{ value: 'none', label: MEAL_LABELS.none }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))],
    ctx.defaultMeal(), { 'aria-label': 'Meal' });
  const amount = field('Amount', { inputmode: 'decimal', autocomplete: 'off', value: '1' });
  const memo = amountMemo(1, 'serving');
  let units = portionUnits(meal);
  const unitSel = select(units.map((u) => ({ value: u.unit, label: u.label })), 'serving', { 'aria-label': 'Amount unit' });
  let lastUnit = 'serving';
  const subText = () => servingsText(meal) + (meal.yield ? ', ' + yieldText(meal.yield) + ' in all' : '') + ' · ' + tagsText(meal.meals);
  const sub = h('p', { class: 'sub' }, subText());
  const perText = () => 'Per serving: ' + perServingText(meal, (v) => fmtNum(v, 0)) + '.' + (meal.complete ? '' : ' ' + sentence('Only matched ingredients count'));
  const per = h('p', { class: 'sub per-line', 'aria-live': 'polite' }, perText());
  const uncounted = h('p', { class: 'sub not-counted' });
  const paintUncounted = () => { uncounted.textContent = notCounted(meal) ? notCountedText(notCounted(meal)) : ''; uncounted.hidden = !notCounted(meal); };
  paintUncounted();
  // After Save Serving Size: new servings or yield change the units and the per serving line, without a repaint.
  function sizeSaved(m) {
    Object.assign(meal, m);
    units = portionUnits(meal);
    if (!units.some((u) => u.unit === unitSel.value)) { unitSel.value = 'serving'; amount.input.value = memo.set(1, 'serving'); }
    const keep = unitSel.value;
    clear(unitSel);
    units.forEach((u) => unitSel.appendChild(h('option', { value: u.unit, selected: u.unit === keep }, u.label)));
    unitSel.value = keep;
    lastUnit = keep;
    sub.textContent = subText();
    per.textContent = perText();
  }
  unitSel.addEventListener('change', () => {  // keep the same share of the recipe in the new unit when the amount reads
    const from = portionFraction(meal, memo.read(amount.input.value), lastUnit);
    if (!from.error) amount.input.value = memo.set(portionAmount(meal, from.fraction, unitSel.value), unitSel.value);
    lastUnit = unitSel.value;
  });
  const chosenMeal = () => (mealSel.value === 'none' ? null : mealSel.value);
  const logBtn = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const r = portionFraction(meal, memo.read(amount.input.value), unitSel.value);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    logBtn.disabled = true;
    try { await api.logMeal(meal.id, { amount: r.amount, unit: unitSel.value, meal: chosenMeal() }); await ctx.go('today', {}, true); } catch (e) {
      logBtn.disabled = false;
      show(status, message(e.message, 'error'));
    }
  } }, 'Log');
  const deleteStatus = h('div', { 'aria-live': 'polite' });
  async function removeRecipe() {  // back to the Recipes tab list, which sits just below this screen
    try { if (await deleteRecipe(meal, () => ctx.repaint())) await ctx.back(); } catch (e) { show(deleteStatus, message(e.message, 'error')); }
  }
  const again = () => ctx.go('recipeview', { mealId: meal.id }, true);  // rename and tags repaint from fresh data
  const edit = meal.can_edit !== false;  // the owner, or an admin for a shared recipe; the server checks every write again
  const dupStatus = h('div', { 'aria-live': 'polite' });
  const dupBtn = h('button', { class: 'btn', type: 'button', onclick: async () => {
    dupBtn.disabled = true;
    try { const d = await api.duplicateMeal(meal.id); await ctx.go('recipeview', { mealId: d.id }, true); } catch (e) {
      dupBtn.disabled = false;
      show(dupStatus, message(e.message, 'error'));
    }
  } }, 'Duplicate');
  // Each match, skip or removal changes the totals: the per serving line, the not counted note and the portions follow at once.
  const focusRow = ctx.flow.takeFocus();
  const ings = ingredientSection(meal, ctx, { st, edit, onMeal: (m) => { sizeSaved(m); paintUncounted(); } });
  const owned = ownerText(meal);
  const tagStatus = h('div', { 'aria-live': 'polite' });
  const renameBox = h('div');
  root.appendChild(h('section', { class: 'screen recipe-view' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    photoHero(meal, edit),
    h('h1', null, meal.name),
    owned ? h('p', { class: 'owner-line' }, owned) : null,
    sub, per, sourceNode(meal.source_url),
    h('h2', { id: 'log-head' }, 'Log'),
    h('label', { class: 'field' }, h('span', null, 'Meal'), mealSel),
    h('div', { class: 'grid2 recipe-log' }, amount, h('label', { class: 'field' }, h('span', null, 'Of the recipe'), unitSel)),
    uncounted,
    status,
    h('div', { class: 'row wrap' }, logBtn),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('cooking', { mealId: meal.id }) }, 'Cooking')),
    params.saved ? h('p', { class: 'saved-note', role: 'status' }, h('span', { class: 'saved-tag' }, 'Saved'),
      h('span', null, sentence('Match the ingredients below to count them'))) : null,
    ings.el,
    edit ? editTools() : viewOnly()));
  if (params.saved || params.focus === 'ingredients' || focusRow != null) {  // after an import, from Saved, or back from the food finder
    root.addEventListener('mounted', () => setTimeout(() => {
      if (focusRow != null) { ings.focus(focusRow); return; }
      const head = root.querySelector('#ing-head');
      if (head && head.scrollIntoView) head.scrollIntoView({ block: 'start' });
    }, 0), { once: true });
  }
  if (params.saved && edit && ctx.flow.takeAuto(meal.id)) ings.autoRun();
  if (params.focus === 'log') {  // Log from a card menu: the Log section in view with the amount ready, once the screen shows
    root.addEventListener('mounted', () => setTimeout(() => {
      const head = root.querySelector('#log-head');
      if (head && head.scrollIntoView) head.scrollIntoView({ block: 'start' });
      amount.input.focus({ preventScroll: true });
    }, 0), { once: true });
  }

  // Someone else's shared recipe: steps to read and Duplicate to make my own private copy.
  function viewOnly() {
    return h('div', null,
      meal.steps.length ? h('h2', null, 'Steps') : null,
      meal.steps.length ? stepsList(meal.steps) : null,
      h('h2', null, 'Make It Yours'),
      h('p', { class: 'sub' }, sentence('Only the owner can change this recipe. Duplicate makes a private copy you can edit')),
      dupStatus, h('div', { class: 'row wrap' }, dupBtn));
  }

  function editTools() {
    return h('div', null,
    h('h2', null, 'Sharing'),
    shareSwitch(meal),
    h('h2', null, 'Meal Tags'),
    chips(meal.meals, async (m) => { await api.patchMeal(meal.id, { meals: m }); meal.meals = m; sub.textContent = subText(); }, tagStatus),
    tagStatus,
    h('h2', null, 'Recipe Name'),
    h('div', { class: 'row wrap' }, h('button', { class: 'btn', type: 'button', onclick: () => renameRecipe(meal, renameBox, again, (e) => show(renameBox, message(e.message, 'error'))) }, 'Rename')),
    renameBox,
    h('h2', null, 'Steps'),
    stepsSection(meal),
    h('h2', null, 'Serving Size'),
    servingSizeEditor(meal, { onSaved: sizeSaved }).el,
    h('h2', null, 'Duplicate'),
    h('p', { class: 'sub' }, sentence('Duplicate makes a private copy of this recipe')),
    dupStatus, h('div', { class: 'row wrap' }, dupBtn),
    deleteStatus,
    h('button', { class: 'btn danger', type: 'button', onclick: removeRecipe }, 'Delete Recipe'));
  }
}

// The Shared switch, saved at once (PATCH shared). Off is the default for every recipe.
function shareSwitch(meal) {
  const id = 'share-' + meal.id;
  const status = h('div', { 'aria-live': 'polite' });
  const box = h('input', { type: 'checkbox', id, checked: !!meal.shared, 'aria-describedby': id + '-help' });
  box.addEventListener('change', async () => {
    const want = box.checked;
    box.disabled = true;
    try {
      meal.shared = (await api.patchMeal(meal.id, { shared: want })).shared;
      show(status, message(meal.shared ? 'Shared with other users.' : meal.mine === false ? 'Private. Only the owner can see it now.' : 'Private. Only you can see it.'));
    } catch (e) { box.checked = !want; show(status, message(e.message, 'error')); }
    box.disabled = false;
  });
  const others = meal.mine === false ? sentence('This recipe belongs to ' + ((meal.owner && meal.owner.name) || 'another user') + '. As an admin you can change or unshare it') : '';
  return h('div', { class: 'switch-row' },
    h('label', { for: id }, box, h('span', null, 'Share With Other Users')),
    h('p', { class: 'sub', id: id + '-help' }, sentence('Off by default, so a recipe stays private') + ' '
      + sentence('When on, everyone on this server can see, log and duplicate it, but only you and admins can change it')
      + (others ? ' ' + others : '')),
    status);
}
