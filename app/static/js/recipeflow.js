// Import Recipe (step 1: source, then a review draft) and Match Ingredients (step 2). The recipe is saved at the end of
// step 1 with every ingredient unmatched, so leaving step 2 never loses the recipe. On step 2 each change is written at once,
// but only Save makes it count as saved: Back writes the state of the last save back after asking Discard Changes?.
// Matching is optional: Save always saves. Rows still not matched are kept (to finish later) or removed, the user's choice.
import { api } from './api.js';
import { h, clear, field, message, show, select, sourceBadge, unitControl, kcalCue, extLink, checkBlock, weightTagNode } from './dom.js';
import { toJpeg } from './ai.js';
import { importPhotoChoice, loadPhotoConfig } from './photo.js';
import { confirmClaude } from './notice.js';
import { chips } from './saved.js';
import { stepsEditor } from './steps.js';
import { unitChoices, fmtNum, fmtAmount, servingText, centsText, sentence, amountMemo, rowAmountText, matchedAmountText, MICROS, microValue, aiFeature, aiFeatureOff, effectiveAutoMatch, CLAUDE_CAP_NOTE, recipeTextCostLine, checkReasonLine, ESTIMATE_SOURCES, weightTag, unitPreviewText } from './util.js';
import {
  parseIngredientText, parseIngredientLine, reviewDraft, reviewBody, blankRow, matchState, matchCountText, toggleAll, toggleId,
  proposalText, matchWhat, importWhat, matchSnapshot, restoreBody, changedSince, nextUnmatched, pendingProposals,
  acceptAllText, notMatchedText, saveChoice, canSaveWithout, SAVE_WITHOUT_NONE, unmatchedIds, photoPick, PHOTOS_TEXT, MATCH_METHODS, matchMethod, matchRunText, methodBatch, matchDoneText, proposalHead,
  importUnitOptions, reviewFlag, pkgNote, useGrams, AUTO_MATCH_LOADING, AUTO_MATCH_FAILED, autoMatchIds, autoMatchResult, autoMatchPlan, autoClaudeBatch, claudeKeep, claudeOffNote, previousCountText, PREVIOUS_CUE, AUTO_CLAUDE_FAILED, AUTO_CLAUDE_CANCELLED, rateLimitNote,
  urlCheck, urlImportOn, recipeUrlCostLine, sourceLink, URL_TEXT, URL_MAX,
  NOTE_MAX, noteCheck, NOTE_LABEL, NOTE_HINT, NOTE_EXAMPLES, RERUN_LABEL, RERUN_TEXT, canRerun, rerunInput, claudeRead,
} from './recipeimport.js';
import { servingSizeEditor } from './servingsize.js';

const MAX_TEXT = 20000;  // same as ai.RECIPE_TEXT_MAX on the server
const bar = (ctx) => h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back'));
const costLine = (cost, what) => (cost == null ? null : h('p', { class: 'sub' }, what + ' cost about ' + centsText(cost) + '.'));

// ---------- step 1: source ----------

// ctx.flow.input keeps { kind, text, url, files, note } for the visit, so Back from the review screen finds them again.
// params.rerun (Rerun With Notes on the review screen): the same screen with everything still filled in. The review in ctx.flow.draft
// is not replaced until the new read succeeds, so Back, Cancel and a failed read leave it exactly as it was.
export async function renderImport(root, ctx, params) {
  const rerun = !!(params && params.rerun && canRerun(ctx.flow.draft));
  if (rerun) Object.assign(ctx.flow.input, rerunInput(ctx.flow.input, ctx.flow.draft));
  const input = ctx.flow.input;
  let st = null;
  try { st = await api.aiStatus(); } catch (e) { st = { enabled: false }; }
  loadPhotoConfig();  // fresh for the review screen's Use As Recipe Photo
  const aiOn = aiFeature(st, 'recipe');
  // Full Claude Use: Read With Claude (text or photos) runs without the extra confirm, and the matching right after the import
  // uses Claude on its own. The cost is shown where the setting is turned on; the text line shows it again, and at the monthly
  // cap the buttons are off with one quiet note.
  const direct = aiOn && ctx.settings.full_claude === true;
  const capped = direct && !(st.remaining > 0);
  const status = h('div', { 'aria-live': 'polite' });
  const panel = h('div');
  const cancelRerun = rerun ? h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Cancel') : null;
  // Web Address shows only when the administrator allows URL import and Claude is usable for this user.
  const urlOn = urlImportOn(st);
  if (input.kind === 'url' && !urlOn) input.kind = 'text';
  const kinds = [['text', 'Paste Text'], ['photos', 'Photos'], ...(urlOn ? [['url', 'Web Address']] : [])];
  const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Recipe source' }, kinds.map(([k, label]) =>
    h('button', { type: 'button', role: 'tab', 'data-kind': k, onclick: () => { input.kind = k; paint(); } }, label)));
  const urlBox = field('Recipe web address', { type: 'url', inputmode: 'url', autocomplete: 'url', spellcheck: 'false', value: input.url || '',
    maxlength: String(URL_MAX), placeholder: 'https://example.com/pancakes', 'aria-describedby': 'import-url-help' });
  urlBox.input.addEventListener('input', () => { input.url = urlBox.input.value; });
  urlBox.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendUrl(); } });
  const urlHelp = h('p', { class: 'sub', id: 'import-url-help' }, URL_TEXT + ' ' + sentence('No photo is imported'));
  const readUrl = h('button', { class: 'btn primary', type: 'button', onclick: sendUrl, disabled: capped, 'aria-describedby': direct ? 'import-url-direct' : null }, 'Read With Claude');
  const urlDirect = direct ? h('p', { class: 'sub', id: 'import-url-direct' }, capped ? CLAUDE_CAP_NOTE : recipeUrlCostLine(st)) : null;

  const area = h('textarea', { rows: '10', maxlength: String(MAX_TEXT), autocomplete: 'off', placeholder: 'Paste the recipe or just its ingredient list' });
  area.value = input.text || '';
  area.addEventListener('input', () => { input.text = area.value; });
  const note = field(NOTE_LABEL, { autocomplete: 'off', value: input.note || '', maxlength: String(NOTE_MAX), 'aria-describedby': 'import-note-help' });
  note.input.addEventListener('input', () => { input.note = note.input.value; });
  const noteBox = h('div', { class: 'import-note' }, note, h('p', { class: 'sub', id: 'import-note-help' }, NOTE_HINT + ' ', NOTE_EXAMPLES));
  let chosen = input.files || [];  // the photos stay chosen when the screen comes back (Back from review, Rerun With Notes)
  const files = h('input', { type: 'file', accept: 'image/*', multiple: '', class: 'visually-hidden', onchange: onFiles });
  const fileList = h('p', { class: 'sub' }, 'No photos chosen.');
  const fileText = () => (chosen.length ? chosen.length + (chosen.length === 1 ? ' photo: ' : ' photos: ') + chosen.map((f) => f.name).join(', ') : 'No photos chosen.');
  fileList.textContent = fileText();
  const photoNote = h('div', { 'aria-live': 'polite' });

  const readText = h('button', { class: 'btn primary', type: 'button', onclick: sendText, disabled: capped, 'aria-describedby': direct ? 'import-direct' : null }, 'Read With Claude');
  const directNote = direct ? h('p', { class: 'sub', id: 'import-direct' }, capped ? CLAUDE_CAP_NOTE : recipeTextCostLine(st)) : null;
  const splitText = h('button', { class: 'btn', type: 'button', onclick: splitLocal }, 'Split Lines Without Claude');
  const readPhotos = h('button', { class: 'btn primary', type: 'button', disabled: capped || !chosen.length, onclick: sendPhotos }, 'Read With Claude');
  const noAi = aiOn ? null : message((aiFeatureOff(st, 'recipe') ? 'Claude recipe import is turned off on this server' : 'Claude is not set up for you')
    + ', so paste the ingredient list and split the lines without Claude.');

  function paint() {
    tabs.querySelectorAll('button').forEach((b) => b.setAttribute('aria-selected', b.dataset.kind === input.kind ? 'true' : 'false'));
    show(status, null);
    if (input.kind === 'url') {
      show(panel, h('div', null, urlBox, urlHelp, noteBox, h('div', { class: 'row wrap' }, readUrl, cancelRerun), urlDirect));
    } else if (input.kind === 'photos') {
      show(panel, h('div', null,
        h('p', { class: 'sub' }, PHOTOS_TEXT),
        aiOn ? [h('label', { class: 'btn' }, 'Choose or Take Photos', files), fileList, photoNote, noteBox, h('div', { class: 'row wrap' }, readPhotos, cancelRerun), capped ? h('p', { class: 'sub' }, CLAUDE_CAP_NOTE) : null] : noAi));
    } else {
      show(panel, h('div', null,
        h('label', { class: 'field' }, h('span', null, 'Recipe text'), area),
        h('p', { class: 'sub' }, 'Split Lines Without Claude reads one ingredient per line and costs nothing. Claude copes with whole pages.'),
        aiOn ? noteBox : noAi, h('div', { class: 'row wrap' }, aiOn ? readText : null, rerun ? null : splitText, cancelRerun), directNote));
    }
  }
  function onFiles() {
    const pick = photoPick(Array.prototype.slice.call(files.files || []));
    chosen = pick.files;
    input.files = chosen;
    show(photoNote, pick.warning ? message(pick.warning, 'error') : null);
    fileList.textContent = fileText();
    readPhotos.disabled = capped || !chosen.length;
  }
  const done = (draft) => {
    ctx.flow.draft = draft;
    if (rerun) ctx.back();  // the review this rerun came from shows the new result in its place
    else ctx.go('importreview');
  };
  function splitLocal() {
    const r = parseIngredientText(area.value);
    if (!r.ingredients.length) { show(status, message('Paste at least one ingredient line first.', 'error')); return; }
    done(reviewDraft(r, { warnings: [] }));
  }
  // One Claude read: a failure shows inline here and the review (if any) stays as it was; only a result replaces it.
  async function read(kind, send, extra) {
    const out = await claudeRead(kind, note.input.value, send, extra);
    if (out.error) { show(status, message(out.status === 429 && direct ? CLAUDE_CAP_NOTE : out.error, 'error')); return; }
    done(out.draft);
  }
  // The note is checked before the cost notice, so nobody confirms a request that would be refused.
  function noteOk() {
    const n = noteCheck(note.input.value);
    if (n.error) { show(status, message(n.error, 'error')); note.input.focus(); }
    return !n.error;
  }
  async function sendText() {
    const text = area.value;
    if (!text.trim()) { show(status, message('Paste the recipe text first.', 'error')); return; }
    if (!noteOk()) return;
    readText.disabled = true;
    try {
      if (!direct && !(await confirmClaude(ctx.settings, { what: importWhat('text', text.length), query: { recipe_chars: text.length } }))) return;
      show(status, message('Claude is reading the recipe...'));
      await read('text', (n) => api.recipeFromText(text, n));
    } finally { readText.disabled = capped; }
  }
  async function sendUrl() {
    if (readUrl.disabled) return;
    const c = urlCheck(urlBox.input.value);
    if (c.error) { show(status, message(c.error, 'error')); urlBox.input.focus(); return; }
    if (!noteOk()) return;
    readUrl.disabled = true;
    try {
      if (!direct && !(await confirmClaude(ctx.settings, { what: importWhat('url'), query: { recipe_url: 1 } }))) return;
      show(status, message('Claude is reading the page...'));
      await read('url', (n) => api.recipeFromUrl(c.url, n));
    } finally { readUrl.disabled = capped; }
  }
  async function sendPhotos() {
    if (!noteOk()) return;
    readPhotos.disabled = true;
    try {
      if (!direct && !(await confirmClaude(ctx.settings, { what: importWhat('photos', chosen.length), query: { recipe_images: chosen.length } }))) return;
      show(status, message('Preparing photos...'));
      const forms = new FormData();
      for (let i = 0; i < chosen.length; i++) forms.append('images', await toJpeg(chosen[i]), 'recipe' + (i + 1) + '.jpg');
      show(status, message('Claude is reading the recipe...'));
      await read('photos', (n) => { if (n) forms.append('note', n); return api.recipeFromPhotos(forms); }, { photoFiles: chosen.slice() });  // offered as the recipe photo on review
    } catch (e) { show(status, message(e.message, 'error')); } finally { readPhotos.disabled = capped || !chosen.length; }
  }

  root.appendChild(h('section', { class: 'screen import' }, bar(ctx), h('h1', null, rerun ? RERUN_LABEL : 'Import Recipe'),
    h('p', { class: 'sub' }, rerun ? RERUN_TEXT : 'Step 1 of 2. Bring in the ingredient list, then match each ingredient to a food.'),
    tabs, panel, status));
  paint();
  if (rerun) note.input.focus();
}

// ---------- step 1: review ----------

// "Source example.com" as a link that opens in a new tab, for http and https addresses only. Exported for the recipe screen.
export function sourceNode(url) {
  const l = sourceLink(url);
  if (!l) return null;
  const a = extLink(l.href, l.text);
  a.setAttribute('aria-label', 'Source, ' + l.text + ', opens in a new tab');
  return h('p', { class: 'sub source-line' }, 'Source ', a);
}

// One typical weight lookup per unit and name: the grams of one clove do not depend on how many.
const previewKey = (r) => String(r.unit || '').trim().toLowerCase() + '|' + String(r.name || '').trim().toLowerCase();

export function renderReview(root, ctx) {
  const draft = ctx.flow.draft;
  if (!draft) { ctx.go('import', {}, true); return; }
  const status = h('div', { 'aria-live': 'polite' });
  const name = field('Recipe name', { value: draft.name, autocomplete: 'off' });
  name.input.addEventListener('input', () => { draft.name = name.input.value; });
  const servings = field('Servings it makes (optional)', { value: draft.servings, inputmode: 'decimal', autocomplete: 'off' });
  servings.input.addEventListener('input', () => { draft.servings = servings.input.value; });
  const list = h('ol', { class: 'list import-rows' });
  const warns = (draft.warnings || []).map((w) => h('li', null, sentence(w)));

  function rowNode(r, i) {
    const box = (key, label, attrs) => {
      const f = field(label, { value: r[key], autocomplete: 'off', ...(attrs || {}) });
      f.input.addEventListener('input', () => { r[key] = f.input.value; });
      f.classList.add('import-' + key);
      return f;
    };
    const unitSel = unitControl(importUnitOptions(), String(r.unit == null ? '' : r.unit).trim(), { 'aria-label': 'Unit of ingredient ' + (i + 1) });
    const unitBox = h('label', { class: 'field import-unit' }, h('span', null, 'Unit'), unitSel);
    // A package or fuzzy unit with no printed size: the typical weight or standard package size its name gives (POST
    // /api/units/preview, an estimate until a food is matched), else the reason; Use Grams types grams at once either way.
    const flagText = h('span', null);
    const chip = h('span', { class: 'match-state match-check' }, 'Check Amount');
    const flag = h('p', { class: 'check-reason import-flag', id: 'flag-' + i }, chip, ' ', flagText, ' ',
      h('button', { class: 'link-btn', type: 'button', onclick: () => { useGrams(r); paintRows(); focusRow(i, '.import-amount input'); } }, 'Use Grams'));
    const pkg = h('p', { class: 'pkg-note' });
    const paintFlag = () => {
      const t = reviewFlag(r);
      const p = t ? previews[previewKey(r)] : null;
      const known = p ? unitPreviewText(p) : '';
      const est = !!(p && p.grams && !p.reason);
      chip.className = 'match-state ' + (est || p === undefined ? 'match-est' : 'match-check');
      chip.textContent = est ? 'Estimated' : p === undefined ? 'Weight' : 'Check Amount';
      flagText.textContent = p === undefined ? 'Looking up a typical weight' : known || t;
      flag.hidden = !t;
      pkg.textContent = pkgNote(r);
      pkg.hidden = !pkg.textContent;
    };
    flags.push(paintFlag);
    const changed = () => { paintFlag(); lookupSoon(); };
    unitSel.addEventListener('change', () => { r.unit = unitSel.value; changed(); });
    const fields = h('div', { class: 'import-fields' }, box('amount', 'Amount', { inputmode: 'decimal' }), unitBox,
      box('name', 'Ingredient'), box('note', 'Note'));
    fields.querySelector('.import-amount input').addEventListener('input', changed);
    fields.querySelector('.import-name input').addEventListener('input', changed);
    paintFlag();
    return h('li', { class: 'import-row' },
      h('div', null, fields, flag, pkg),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ingredient ' + (i + 1) + (r.name ? ', ' + r.name : ''),
        onclick: () => { draft.rows.splice(i, 1); paintRows(); } }, '×'));
  }
  function focusRow(i, sel) {
    const el = list.children[i] && list.children[i].querySelector(sel);
    if (el) el.focus();
  }
  // Typical weights before matching, looked up once per line (amount, unit and name) and kept on the draft for the visit.
  const previews = draft.unitPreviews || (draft.unitPreviews = {});
  let flags = [];
  let timer = null;
  function lookupSoon() { clearTimeout(timer); timer = setTimeout(lookup, 300); }
  async function lookup() {
    const want = draft.rows.filter((r) => reviewFlag(r) && !(previewKey(r) in previews));
    const keys = [...new Set(want.map(previewKey))];
    if (!keys.length) return;
    const lines = keys.map((k) => { const r = want.find((x) => previewKey(x) === k); return { amount: 1, unit: r.unit, name: r.name }; });
    let out = null;
    try { out = (await api.unitsPreview(lines)).lines; } catch (e) { out = null; }
    keys.forEach((k, n) => { previews[k] = (out && out[n]) || {}; });  // a failure shows the plain reason
    flags.forEach((f) => f());
  }
  function paintRows(focusLast) {
    flags = [];
    clear(list);
    draft.rows.forEach((r, i) => list.appendChild(rowNode(r, i)));
    if (!draft.rows.length) list.appendChild(h('li', { class: 'sub' }, 'No ingredients yet.'));
    if (focusLast) { const last = list.querySelector('li:last-child .import-name input'); if (last) last.focus(); }
    lookup();
  }
  const save = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
    const r = reviewBody(draft);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    save.disabled = true;
    let meal;
    try { meal = await api.importMeal(r.body); } catch (e) { save.disabled = false; show(status, message(e.message, 'error')); return; }
    if (draft.photoBlob) {  // the recipe exists now; a failed photo upload never blocks matching (Add Photo on the recipe screen)
      try { await api.mealPhoto(meal.id, draft.photoBlob); } catch (e) { /* the recipe is saved; the photo can be added later */ }
    }
    ctx.flow.saved(meal);
  } }, 'Save and Continue');

  root.appendChild(h('section', { class: 'screen import' }, bar(ctx), h('h1', null, 'Check the Recipe'),
    h('p', { class: 'sub' }, 'Step 1 of 2. Fix anything that looks wrong. Nothing is saved until you tap Save and Continue.'),
    costLine(draft.cost, 'This read'),
    sourceNode(draft.sourceUrl),
    warns.length ? h('ul', { class: 'warnings', role: 'alert' }, warns) : null,
    name, servings,
    h('h2', null, 'Ingredients'), list,
    h('button', { class: 'btn', type: 'button', onclick: () => { draft.rows.push(blankRow()); paintRows(true); } }, 'Add Ingredient'),
    h('h2', null, 'Steps'),
    h('p', { class: 'sub' }, 'The method, in order. Steps are notes only and never change the nutrition.'),
    stepsEditor(draft),
    h('h2', null, 'Meal Tags'),
    h('p', { class: 'sub' }, 'Tags decide where the recipe shows on Add. Untagged recipes show under every meal.'),
    chips(draft.meals, (m) => { draft.meals = m; }, status),
    importPhotoChoice(draft),
    status,
    h('div', { class: 'row wrap' }, save,
      canRerun(draft) ? h('button', { class: 'btn', type: 'button', onclick: () => ctx.go('import', { rerun: true }) }, RERUN_LABEL) : null,
      h('button', { class: 'btn ghost', type: 'button', onclick: ctx.flow.cancel }, 'Cancel'))));
  paintRows();
}

// ---------- step 2: match ingredients ----------

const NUTRIENT_ROWS = [['kcal', 'Calories', ''], ['carbs', 'Carbs', 'g'], ['protein', 'Protein', 'g'], ['fat', 'Fat', 'g'],
  ...MICROS.map((m) => [m.key, m.label, m.unit])];

function totalsTable(meal) {
  const per = meal.per_serving;
  return h('table', { class: 'match-totals' },
    h('caption', { class: 'visually-hidden' }, 'Nutrition per serving'),
    h('tbody', null, NUTRIENT_ROWS.map(([k, label, unit]) => h('tr', null, h('th', { scope: 'row' }, label),
      h('td', null, per[k] == null ? '-' : k === 'kcal' ? fmtNum(per[k], 0) : microValue(per[k], unit) + ' ' + unit)))));
}

// "Wheat flour [USDA] - 1 cup, 125 g - 455 kcal". A Check Amount row shows its tentative amount without calories. A row whose
// weight comes from a unit weight or an estimate carries the Estimated Weight tag (onSave: the grams typed in it).
function foodLine(it, onSave) {
  const f = it.food;
  const tag = it.check ? null : weightTagNode(it, f.name, onSave);
  return h('span', { class: 'item-sub' }, (f.brand ? f.name + ' (' + f.brand + ')' : f.name) + ' ', sourceBadge(f.source, true),
    ' - ' + matchedAmountText(it.amount, it.unit, it.grams) + (it.check ? '' : ' - ' + fmtNum(it.kcal, 0) + ' kcal'),
    it.check ? null : kcalCue(it),
    tag ? [' ', tag] : it.estimated && !it.check ? [' ', h('span', { class: 'src-est', title: 'From ' + (ESTIMATE_SOURCES[it.estimate_source] || ESTIMATE_SOURCES.guess) }, 'Estimated Conversion')] : null);
}

// Why a Check Amount row needs one, in words next to its chip: "No standard weight for clove, enter grams".
function reasonLine(it) {
  return h('span', { class: 'check-reason' }, checkReasonLine(it.check_reason, (it.src && it.src.unit) || it.unit));
}

// params: { mealId, saved? (just saved by Import, shows Step 2 of 2), edit? (opened to change a finished recipe: the same page,
// every row can be searched again, rescanned, re-amounted, skipped or removed, and rows can be added), visit? (set on the first
// render, so coming back from the food finder keeps the same last saved state) }
export async function renderMatch(root, params, ctx) {
  const visit = ctx.flow.visit(params);
  let meal = await api.meal(params.mealId);
  const base = () => ctx.flow.base(visit) || ctx.flow.setBase(visit, matchSnapshot(meal));
  const opened = !ctx.flow.base(visit);
  base();
  let st = null;
  try { st = await api.aiStatus(); } catch (e) { st = { enabled: false }; }
  const aiOn = aiFeature(st, 'recipe');
  const props = ctx.flow.proposals(meal.id);  // Claude proposals waiting for Accept, kept while the user searches
  // Opening the page pre-ticks every unmatched row, so Match Selected works in one tap. A return from the food finder keeps the ticks.
  let selected = opened ? unmatchedIds(meal.items) : ctx.flow.selection(meal.id).filter((id) => meal.items.some((i) => i.id === id && !i.skipped));
  let current = meal.items.findIndex((i) => i.id === ctx.flow.takeFocus());
  const status = h('div', { 'aria-live': 'polite' });
  const limitNote = h('div', { 'aria-live': 'polite' });  // the quiet USDA rate limit note, kept above the rows until the next search
  let busy = false;  // Auto-Match After Import is running
  const count = h('p', { class: 'match-count', 'aria-live': 'polite' });
  const checks = h('div');  // the amounts to check, with each reason
  const list = h('ul', { class: 'list match-list' });
  const totals = h('div');
  const allBox = h('input', { type: 'checkbox', id: 'match-all', onchange: () => { selected = toggleAll(meal.items, selected); keepSel(); paintRows(); } });
  let method = matchMethod(ctx.flow.method, aiOn);  // Search (default) or Claude; Claude only when it is on for this user
  const matchBtn = h('button', { class: 'btn', type: 'button', 'aria-describedby': 'match-hint', onclick: () => runMatch(selected) }, matchRunText(method));
  const matchHint = h('span', { class: 'sub match-hint', id: 'match-hint' }, 'Tick Ingredients to Match');
  const methodBtns = MATCH_METHODS.map(([k, label]) => h('button', { class: 'seg-btn', type: 'button', 'data-method': k,
    'aria-pressed': k === method ? 'true' : 'false', onclick: () => setMethod(k) }, label));
  const methodSwitch = aiOn ? h('div', { class: 'method-switch', role: 'group', 'aria-label': 'Match With' },
    h('span', { class: 'method-label', 'aria-hidden': 'true' }, 'Match With:'), h('div', { class: 'segmented' }, methodBtns)) : null;
  function setMethod(k) {
    method = matchMethod(k, aiOn);
    ctx.flow.method = method;
    methodBtns.forEach((b) => b.setAttribute('aria-pressed', b.dataset.method === method ? 'true' : 'false'));
    matchBtn.textContent = matchRunText(method);
  }
  const acceptBtn = h('button', { class: 'btn primary', type: 'button', onclick: acceptAll }, '');
  const previousNote = h('span', { class: 'sub match-previous' });
  previousNote.hidden = true;  // how many suggestions come from an earlier recipe
  const acceptRow = h('div', { class: 'row wrap match-bulk' }, acceptBtn, previousNote);
  const jumpBtn = h('button', { class: 'link-btn', type: 'button', onclick: jump }, 'Jump to Next Unmatched');
  const saveBtn = h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Save');
  const backBtn = h('button', { class: 'btn', type: 'button', onclick: leave }, 'Back');
  const choiceBox = h('div', { 'aria-live': 'polite' });
  const size = servingSizeEditor(meal, { live: true, status, onSaved: (m) => { meal = m; paintTotals(); paintHead(); } });
  const keepSel = () => ctx.flow.setSelection(meal.id, selected);
  const fail = (e) => show(status, message(e.message, 'error'));
  const setMeal = (m) => { meal = m; size.update(m); };
  const drop = (ids) => {
    ids.forEach((id) => { delete props[id]; });
    selected = selected.filter((x) => ids.indexOf(x) < 0);
    keepSel();
  };

  async function apply(itemId, body) {
    try {
      setMeal(await api.matchItem(meal.id, itemId, body));
      drop([itemId]);
      paintAll(itemId);
    } catch (e) { fail(e); }
  }
  // A Claude estimate becomes a food only on Accept. It is kept on the proposal, so trying again never saves it twice.
  async function foodOf(p) {
    if (!p.food.id) p.food = await api.createFood(p.food);
    return p.food;
  }
  async function accept(item, p) {
    try {
      const food = await foodOf(p);
      await apply(item.id, { food_id: food.id, amount: p.amount, unit: p.unit, ...(p.check ? { check: true } : {}) });
    } catch (e) { fail(e); }
  }
  // The grams typed in an Estimated Weight tag: a match in g with remember, so they become your weight of one of the line's unit
  // (Enter Grams does the same). On a suggestion it accepts it with those grams.
  async function typedGrams(item, foodId, grams) {
    setMeal(await api.matchItem(meal.id, item.id, { food_id: foodId, amount: grams, unit: 'g', remember: true }));
    drop([item.id]);
    paintAll(item.id);
    show(status, message('Saved ' + fmtNum(grams, 1) + ' g for ' + item.food_name + '. The weight is remembered for this food.'));
  }
  async function acceptGrams(item, p, grams) {
    const food = await foodOf(p);
    await typedGrams({ ...item, food_name: food.name }, food.id, grams);
  }
  async function acceptAll() {
    const pending = pendingProposals(meal.items, props);
    if (!pending.length) return;
    acceptBtn.disabled = true;
    try {
      const rows = [];
      for (const { item, p } of pending) {
        const food = await foodOf(p);
        rows.push({ id: item.id, food_id: food.id, amount: p.amount, unit: p.unit, ...(p.check ? { check: true } : {}) });
      }
      setMeal(await api.matchItems(meal.id, rows));
      drop(rows.map((r) => r.id));
      paintAll();
      show(status, message(rows.length + (rows.length === 1 ? ' suggestion accepted.' : ' suggestions accepted.')));
    } catch (e) { fail(e); } finally { acceptBtn.disabled = false; }
  }
  const showLimit = (r) => { const t = rateLimitNote(r); show(limitNote, t ? h('p', { class: 'sub match-limit', role: 'status' }, t) : null); };
  // Auto-Match After Import, once, right after the import. Search is the free name search, Claude asks Claude (same confirm, cap and
  // cost as Match Selected With Claude), Search Then Claude asks Claude only about rows Search left without a proposal. It never
  // blocks: the page is already usable, and a failure or a cancel only leaves the rows unmatched (and ticked) with a quiet note.
  async function autoRun() {
    // Full Claude Use turns the Search setting (the default, so it cannot be told from a choice) into Search Then Claude, and then
    // Claude is asked about every row Search did not take from a previous recipe. Without Claude, Search runs and a note says why.
    const full = ctx.settings.full_claude === true;
    const eff = effectiveAutoMatch(ctx.display.auto_match, full);
    const base = autoMatchPlan(eff.value, aiOn);
    const plan = base.note ? { ...base, note: claudeOffNote(st) } : base;
    if (!plan.search && !plan.claude) return;
    busy = true;
    status.setAttribute('aria-busy', 'true');
    paintHead();
    const keep = (r) => {  // keeps the proposals, un-ticks only rows that got a food, so the rest stay ticked for a manual Match
      const { fresh, found } = autoMatchResult(meal.items, r.proposals);
      fresh.forEach((p) => { props[p.item_id] = p; });
      selected = selected.filter((id) => found.indexOf(id) < 0);
      keepSel();
      return fresh;
    };
    let text = '';
    try {
      if (plan.search) {
        const ids = autoMatchIds(meal.items);
        if (ids.length) {
          show(status, message(AUTO_MATCH_LOADING));
          const r = await api.matchSearch(meal.id, ids, ctx.flow.searchSource());
          const fresh = keep(r);
          showLimit(r);
          text = matchDoneText('search', fresh, 0, '');
          busy = plan.claude;
          paintRows();
          show(status, message(text));
        }
      }
      if (plan.claude) {
        const b = autoClaudeBatch(meal.items, props, full);
        let left = null;  // the monthly cap: automatic Claude steps stop there with one quiet note, nothing is sent
        if (b.send.length) { try { left = (await api.aiStatus()).remaining; } catch (e) { left = null; } }
        if (b.send.length && left != null && left <= 0) {
          text = [text, CLAUDE_CAP_NOTE].filter(Boolean).join(' ');
        } else if (b.send.length) {
          // Full Claude Use: the matching after an import never asks; otherwise the usual confirm
          if (!full && !(await confirmClaude(ctx.settings, { what: matchWhat(b.send.length), query: { match_rows: b.send.length } }))) {
            text = [text, AUTO_CLAUDE_CANCELLED].filter(Boolean).join(' ');
          } else {
            show(status, message('Claude is matching ' + b.send.length + (b.send.length === 1 ? ' ingredient...' : ' ingredients...')));
            try {
              const r = await api.matchIngredients(meal.id, b.send);
              keep({ ...r, proposals: claudeKeep(r.proposals, props) });
              text = matchDoneText('claude', Object.values(props), b.rest.length, r.cost != null ? 'This cost about ' + centsText(r.cost) + '.' : '');
            } catch (e) { text = [text, AUTO_CLAUDE_FAILED].filter(Boolean).join(' '); }
          }
        }
      }
      busy = false;  // before the repaint, so Match Selected is enabled again
      paintRows();
      show(status, text || plan.note ? message([text, plan.note].filter(Boolean).join(' ')) : null);
    } catch (e) {
      show(status, message(AUTO_MATCH_FAILED));
    } finally { busy = false; status.removeAttribute('aria-busy'); paintHead(); }
  }
  // how: the method for this run. The button uses the switch, Ask Claude on a row always uses Claude.
  async function runMatch(ids, how) {
    const m = how || method;
    const b = methodBatch(m, ids);
    if (!b.send.length) { show(status, message('Tick at least one ingredient first.', 'error')); return; }
    matchBtn.disabled = true;
    show(limitNote, null);
    try {
      let r;
      if (m === 'claude') {
        if (!(await confirmClaude(ctx.settings, { what: matchWhat(b.send.length), query: { match_rows: b.send.length } }))) return;
        show(status, message('Claude is matching ' + b.send.length + (b.send.length === 1 ? ' ingredient...' : ' ingredients...')));
        r = await api.matchIngredients(meal.id, b.send);
      } else {
        show(status, message('Searching for ' + b.send.length + (b.send.length === 1 ? ' ingredient...' : ' ingredients...')));
        r = await api.matchSearch(meal.id, b.send, ctx.flow.searchSource());
      }
      r.proposals.forEach((p) => { props[p.item_id] = p; });
      if (m === 'search') showLimit(r);
      selected = selected.filter((id) => b.send.indexOf(id) < 0);
      keepSel();
      paintRows();
      show(status, message(matchDoneText(m, r.proposals, b.rest.length, m === 'claude' && r.cost != null ? 'This cost about ' + centsText(r.cost) + '.' : '')));
    } catch (e) { fail(e); } finally { matchBtn.disabled = !selected.length; }
  }

  // Keep the highlighted row after rows were added or removed: current is an index, so find the same row again.
  function keepCurrent(fn) {
    const id = current >= 0 && meal.items[current] ? meal.items[current].id : null;
    fn();
    current = id == null ? -1 : meal.items.findIndex((i) => i.id === id);
  }
  async function removeRow(item, label) {
    try {
      const i = meal.items.findIndex((x) => x.id === item.id);
      const m = await api.deleteMealItem(meal.id, item.id);
      keepCurrent(() => setMeal(m));
      drop([item.id]);
      delete editing[item.id];
      paintAll(m.items.length ? m.items[Math.min(i, m.items.length - 1)].id : null);
      show(status, message('Removed ' + label + '. Back undoes it until you tap Save.'));
    } catch (e) { fail(e); }
  }
  // Add Ingredient: one typed line ("1 tbsp olive oil"), split like Import does, added as an unmatched row at the end.
  async function addRow(line, search) {
    const row = parseIngredientLine(line);
    if (!row) { show(status, message('Type the ingredient first.', 'error')); return false; }
    try {
      const { added, ...m } = await api.addMealItem(meal.id, { src: { text: row.text.slice(0, 300), amount: row.amount, unit: row.unit, name: row.name.slice(0, 200), note: row.note } });
      keepCurrent(() => setMeal(m));
      show(addBox, null);
      selected = [...selected, added];  // a new row is unmatched, so it is ticked like the others
      keepSel();
      paintAll(search ? null : added);
      const item = m.items.find((x) => x.id === added);
      if (search && item) ctx.flow.find(m, item, 'search');
      else show(status, message('Added ' + row.text + '. Match it to a food.'));
      return true;
    } catch (e) { fail(e); return false; }
  }
  const addBox = h('div', { class: 'match-add' });
  function addForm() {
    const line = field('Ingredient line', { autocomplete: 'off', maxlength: '300', placeholder: 'e.g. 1 tbsp olive oil' });
    show(addBox, h('form', { class: 'sheet', onsubmit: (e) => { e.preventDefault(); addRow(line.input.value, false); } },
      line,
      h('div', { class: 'row wrap' }, h('button', { class: 'btn primary', type: 'submit' }, 'Add'),
        h('button', { class: 'btn', type: 'button', onclick: () => addRow(line.input.value, true) }, 'Add and Search'),
        h('button', { class: 'btn ghost', type: 'button', onclick: () => { show(addBox, null); addBtn.focus(); } }, 'Cancel'))));
    line.input.focus();
  }
  const addBtn = h('button', { class: 'btn', type: 'button', onclick: addForm }, 'Add Ingredient');

  // Jump to Next Unmatched: scroll to the next unmatched (or Check Amount) row after the current one, and focus it.
  function jump() {
    const i = nextUnmatched(meal.items, current);
    if (i < 0) return;
    current = i;
    paintRows();
    const el = document.getElementById('ing-' + meal.items[i].id);
    if (el) { el.scrollIntoView({ block: 'center' }); el.focus({ preventScroll: true }); }
  }
  // Save always saves and leaves; every change was written already. Rows still not matched are asked about once, in the page.
  let choiceNote = null;  // where Save Without Them reports a problem, inside the open choice
  function finish() { ctx.flow.endVisit(visit); ctx.flow.exit(); }
  function save() {
    const c = saveChoice(meal);
    if (!c.ask) { finish(); return; }
    const without = h('button', { class: 'btn', type: 'button', onclick: saveWithout }, 'Save Without Them');
    const keep = h('button', { class: 'btn primary', type: 'button', onclick: finish }, 'Keep Them to Finish Later');
    const cancel = h('button', { class: 'btn ghost', type: 'button', onclick: () => { show(choiceBox, null); saveBtn.disabled = false; saveBtn.focus(); } }, 'Cancel');
    const note = h('div', { 'aria-live': 'polite' });
    choiceNote = note;
    saveBtn.disabled = true;
    show(choiceBox, h('div', { class: 'sheet save-choice', role: 'group', 'aria-labelledby': 'save-choice-title' },
      h('h2', { id: 'save-choice-title' }, 'Save Recipe'),
      h('p', null, notMatchedText(c.n)),
      h('p', { class: 'sub' }, 'Save Without Them removes them from the recipe. Keep Them to Finish Later saves them with no nutrition, so you can match them later.'),
      note,
      h('div', { class: 'row wrap' }, without, keep, cancel)));
    keep.focus();
  }
  async function saveWithout() {
    if (!canSaveWithout(meal)) { show(choiceNote, message(SAVE_WITHOUT_NONE, 'error')); return; }
    try { await api.deleteUncounted(meal.id); } catch (e) { show(choiceNote, message(e.message, 'error')); return; }
    finish();
  }
  // Back does not save: after Discard Changes? it writes the last saved state back, then leaves.
  async function leave() {
    const r = restoreBody(base(), meal);
    if (r.items.length || r.meal || r.remove.length || r.add.length) {
      if (!window.confirm('Discard Changes? Matches, amounts, skips, added or removed ingredients and serving size changes since you opened this page are undone.')) return;
      backBtn.disabled = true;
      try {
        for (const id of r.remove) await api.deleteMealItem(meal.id, id);  // rows added since, then rows removed since, back in place
        for (const body of r.add) await api.addMealItem(meal.id, body);
        if (r.items.length) await api.matchItems(meal.id, r.items);
        if (r.meal) await api.patchMeal(meal.id, r.meal);
      } catch (e) { backBtn.disabled = false; fail(e); return; }
    }
    ctx.flow.endVisit(visit);
    ctx.flow.exit();
  }

  function proposalBox(item, p) {
    const est = p.kind === 'estimate';
    const kcal = p.preview ? ' - ' + fmtNum(p.preview.kcal, 0) + ' kcal' : '';
    const bySearch = p.method === 'search';
    return h('div', { class: 'proposal', role: 'group', 'aria-label': bySearch ? 'Search suggestion' : 'Claude suggestion' },
      h('p', { class: 'proposal-head' }, proposalHead(p) + ' ', p.food ? sourceBadge(p.food.source, true) : null,
        p.kind === 'candidate' && !bySearch && !p.from_previous ? h('span', { class: 'src-est' }, ' Database Match') : null,
        p.from_previous ? h('span', { class: 'src-est previous-cue' }, ' ' + PREVIOUS_CUE) : null),
      h('p', null, proposalText(p) + (p.food ? kcal : ''), weightTag(p) ? [' ', weightTagNode(p, p.food.name, (g) => acceptGrams(item, p, g))]
        : p.estimated ? [' ', h('span', { class: 'src-est' }, 'Estimated Conversion')] : null),
      p.food && p.note && !p.from_previous ? h('p', { class: 'sub' }, sentence(p.note)) : null,
      est && !p.food.id ? h('p', { class: 'sub' }, 'No database food fitted, so this is an estimate. Accept saves it as a Claude food.') : null,
      p.warnings && p.warnings.length ? h('ul', { class: 'warnings' }, p.warnings.map((w) => h('li', null, sentence(w)))) : null,
      h('div', { class: 'row wrap' },
        p.food ? h('button', { class: 'btn', type: 'button', onclick: () => accept(item, p) }, 'Accept') : null,
        h('button', { class: 'btn', type: 'button', onclick: () => { delete props[item.id]; ctx.flow.find(meal, item, 'search'); } }, p.food ? 'Change' : 'Search'),
        p.food ? null : h('button', { class: 'btn', type: 'button', onclick: () => apply(item.id, { skipped: true }) }, 'Skip')));
  }

  // The food's units for the amount editor, fetched once per food.
  const unitCache = {};
  const unitsOf = (id) => unitCache[id] || (unitCache[id] = api.food(id).then((f) => f.units));
  const editing = {};  // item id -> true while Edit Amount is open on a matched row

  // Small inline amount and unit editor for one attached food: always open on a Check Amount row (Confirm Amount),
  // opened by Edit Amount on a matched row (Save Amount, Cancel). Saving is a plain match, which clears Check Amount.
  function amountEditor(item) {
    const name = item.food.name;
    const memo = amountMemo();
    const amt = field('Amount', { inputmode: 'decimal', autocomplete: 'off', value: memo.set(item.amount, item.unit),
      'aria-label': 'Amount of ' + name });
    const unitBox = h('label', { class: 'field unit-field' }, h('span', null, 'Unit'), h('span', { class: 'sub' }, 'Loading...'));
    const save = h('button', { class: 'btn small primary', type: 'button', disabled: true }, item.check ? 'Confirm Amount' : 'Save Amount');
    let unitSel = null;
    let hasGrams = false;
    let typedGrams = false;  // Enter Grams: the grams typed become your weight of one of the line's unit (remember)
    unitsOf(item.food_id).then((units) => {
      hasGrams = units.some((u) => u.unit === 'g');
      unitSel = unitControl(unitChoices(units).map((u) => ({ value: u.value, label: u.label + (u.estimated ? ' (estimated)' : '') })), item.unit, { 'aria-label': 'Unit of ' + name });
      unitBox.replaceChild(unitSel, unitBox.lastChild);
      save.disabled = false;
    }, fail);
    save.addEventListener('click', () => {
      const a = memo.value(amt.input.value);
      delete editing[item.id];
      if (!amt.input.value.trim()) { apply(item.id, { skipped: true }); return; }  // no amount: it stays a plain text line, counting nothing
      if (a == null || a <= 0) { editing[item.id] = true; show(status, message('Check the amount of ' + name + '.', 'error')); amt.input.focus(); return; }
      const remember = (typedGrams || item.check) && ['g', 'kg', 'oz', 'lb'].indexOf(unitSel.value) >= 0;
      apply(item.id, { food_id: item.food_id, amount: a, unit: unitSel.value, ...(remember ? { remember: true } : {}) });
    });
    const noAmount = item.check && item.src && item.src.amount == null;
    // Enter Grams: the quick way out of a missing weight, the unit goes to g and the amount box is cleared for typing.
    const grams = h('button', { class: 'btn small', type: 'button', onclick: () => {
      if (!unitSel || !hasGrams) { amt.input.focus(); return; }
      unitSel.value = 'g';
      typedGrams = true;
      amt.input.value = '';
      amt.input.focus();
    } }, 'Enter Grams');
    return h('div', { class: 'amount-check', role: 'group', 'aria-label': (item.check ? 'Check amount of ' : 'Amount of ') + name },
      item.check ? h('p', { class: 'sub' }, noAmount ? 'The recipe gives no amount here. Enter one, or leave it empty to keep plain text.'
        : 'The recipe amount could not be converted for this food. Enter the amount, or tap Enter Grams, then tap Confirm Amount.') : null,
      h('p', { class: 'sub' }, 'Leave the amount empty to keep the line as plain text.'),
      h('div', { class: 'amount-edit' }, amt, unitBox, save, item.check && !noAmount ? grams : null,
        item.check ? null : h('button', { class: 'btn small ghost', type: 'button', onclick: () => { delete editing[item.id]; paintRows(); } }, 'Cancel')));
  }

  function rowNode(item, i) {
    const state = matchState(item);
    const label = (item.src && item.src.text) || (item.food && item.food.name) || 'Ingredient';
    const box = !item.skipped ? h('input', { type: 'checkbox', checked: selected.indexOf(item.id) >= 0, 'aria-label': 'Select ' + label,
      onchange: () => { selected = toggleId(selected, item.id); keepSel(); paintHead(); } }) : null;
    const chip = (text) => h('span', { class: 'match-state match-' + state }, text);
    const onGrams = (g) => typedGrams({ ...item, food_name: item.food.name }, item.food_id, g);
    const stateNode = state === 'matched' ? foodLine(item, onGrams)
      : state === 'check' ? h('span', { class: 'match-text' }, h('span', { class: 'item-sub' }, chip('Check Amount')), reasonLine(item), foodLine(item))
        : h('span', { class: 'item-sub' }, chip(state === 'skipped' ? 'Skipped' : 'Unmatched'));
    const p = props[item.id];
    return h('li', { class: 'match-row' + (i === current ? ' current' : ''), id: 'ing-' + item.id, tabindex: '-1',
      'aria-current': i === current ? 'true' : null },
    h('div', { class: 'match-top' }, box, h('div', { class: 'match-text' }, h('span', { class: 'item-title' }, label), stateNode)),
    h('div', { class: 'row wrap match-actions' },
      h('button', { class: 'btn small', type: 'button', onclick: () => ctx.flow.find(meal, item, 'search') }, 'Search'),
      h('button', { class: 'btn small', type: 'button', onclick: () => ctx.flow.find(meal, item, 'scan') }, 'Scan Barcode'),
      aiOn ? h('button', { class: 'btn small', type: 'button', onclick: () => runMatch([item.id], 'claude') }, 'Ask Claude') : null,
      state === 'matched' && !editing[item.id] ? h('button', { class: 'btn small', type: 'button',
        onclick: () => { editing[item.id] = true; paintRows(); focusIn(item.id, 'input'); } }, 'Edit Amount') : null,
      h('button', { class: 'btn small', type: 'button', 'aria-pressed': item.skipped ? 'true' : 'false',
        onclick: () => apply(item.id, { skipped: !item.skipped }) }, item.skipped ? 'Unskip' : 'Skip'),
      meal.items.length > 1 ? h('button', { class: 'btn small', type: 'button', 'aria-label': 'Remove ' + label, onclick: () => removeRow(item, label) }, 'Remove') : null),
    state === 'check' || (state === 'matched' && editing[item.id]) ? amountEditor(item) : null,
    p && !item.skipped ? proposalBox(item, p) : null);
  }
  function focusIn(id, sel) {
    const el = document.querySelector('#ing-' + id + ' ' + sel);
    if (el) el.focus();
  }

  function paintHead() {
    count.textContent = matchCountText(meal);
    show(checks, checkBlock(meal));
    const open = meal.items.filter((i) => matchState(i) === 'unmatched').map((i) => i.id);
    allBox.checked = open.length > 0 && open.every((id) => selected.indexOf(id) >= 0);
    matchBtn.disabled = busy || !selected.length;
    matchHint.hidden = selected.length > 0;
    jumpBtn.hidden = nextUnmatched(meal.items, current) < 0;
    const pending = pendingProposals(meal.items, props);
    acceptRow.hidden = !pending.length;
    acceptBtn.textContent = acceptAllText(pending.length);
    const fromBefore = previousCountText(pending);
    previousNote.textContent = fromBefore;
    previousNote.hidden = !fromBefore;
  }
  function paintRows() {
    clear(list);
    meal.items.forEach((it, i) => list.appendChild(rowNode(it, i)));
    paintHead();
  }
  function paintTotals() {
    show(totals, h('div', null,
      h('h2', null, 'Per Serving'),
      h('p', { class: 'sub' }, meal.complete ? 'For 1 of ' + servingText(meal.servings) + ' servings.'
        : 'For 1 of ' + servingText(meal.servings) + ' servings, counting matched ingredients only.'
          + (meal.checks ? ' Rows marked Check Amount count once you confirm their amount.' : '')),
      totalsTable(meal)));
  }
  function paintAll(focusId) {
    paintRows();
    paintTotals();
    if (focusId != null) { const el = document.getElementById('ing-' + focusId); if (el) el.focus(); }
  }

  const noAi = h('p', { class: 'sub' }, (aiFeatureOff(st, 'recipe') ? 'Claude recipe import is turned off on this server' : 'Claude is not set up for you')
    + ', so Match Selected uses Search.');
  root.appendChild(h('section', { class: 'screen match' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: leave }, 'Back')),
    h('h1', null, 'Match Ingredients'),
    params.saved ? h('p', { class: 'saved-note', role: 'status' }, h('span', { class: 'saved-tag' }, 'Saved'), h('span', null, 'Step 2 of 2')) : null,
    h('p', { class: 'sub' }, params.edit
      ? 'Change any ingredient: search again, scan a barcode, edit the amount, skip it or remove it, or add a new one. Matching is optional. Tap Save when you are done. Back leaves without the changes made since you opened this page.'
      : 'The recipe is saved. Match the ingredients you want counted, or leave some for later. Tap Save when you are done. Back leaves without the changes made since you opened this page.'),
    h('h2', null, meal.name), count, checks,
    h('div', { class: 'match-jump' }, jumpBtn),
    acceptRow,
    h('div', { class: 'row wrap match-bulk' }, h('label', { class: 'check', for: 'match-all' }, allBox, ' Select All')),
    h('div', { class: 'row wrap match-run' }, methodSwitch, matchBtn, matchHint),
    aiOn ? null : noAi,
    status, limitNote, list,
    addBtn, addBox,
    h('h2', null, 'Serving Size'), size.el,
    totals, choiceBox,
    h('div', { class: 'row wrap match-foot' }, backBtn, saveBtn)));
  paintRows();
  paintTotals();
  if (params.saved && ctx.flow.takeAuto(meal.id)) autoRun();
  if (current >= 0) {
    const id = meal.items[current].id;
    root.addEventListener('mounted', () => { const el = document.getElementById('ing-' + id); if (el) { el.scrollIntoView({ block: 'center' }); el.focus({ preventScroll: true }); } });
  }
}
