// Import Recipe: the source (text, photos or a web address), then a short review. Save Recipe saves it at once with every
// ingredient as an unmatched line (zero nutrition until matched) and opens the recipe screen, where the ingredients are matched
// in place (js/ingrows.js, v77 issue #49). Matching is optional and never blocks saving.
import { api } from './api.js';
import { h, clear, field, message, show, extLink, unitControl } from './dom.js';
import { toJpeg } from './ai.js';
import { importPhotoChoice, loadPhotoConfig } from './photo.js';
import { confirmClaude } from './notice.js';
import { stepsEditor } from './steps.js';
import { centsText, sentence, aiFeature, aiFeatureOff, CLAUDE_CAP_NOTE, recipeTextCostLine, unitPreviewText } from './util.js';
import {
  parseIngredientText, reviewDraft, reviewBody, blankRow, importUnitOptions, importWhat, photoPick, PHOTOS_TEXT, reviewFlag, pkgNote, estimateNote, tidyAmountBox,
  urlCheck, urlImportOn, importKinds, startKind, recipeUrlCostLine, sourceLink, URL_TEXT, URL_MAX,
  NOTE_MAX, noteCheck, NOTE_LABEL, NOTE_HINT, NOTE_EXAMPLES, RERUN_LABEL, RERUN_TEXT, canRerun, rerunInput, claudeRead,
} from './recipeimport.js';

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
  // Full Claude Use: Read With Claude (text or photos) runs without the extra confirm, and the matching offered by the banner on the recipe screen
  // uses Claude on its own. The cost is shown where the setting is turned on; the text line shows it again, and at the monthly
  // cap the buttons are off with one quiet note.
  const direct = aiOn && ctx.settings.full_claude === true;
  const capped = direct && !(st.remaining > 0);
  const status = h('div', { 'aria-live': 'polite' });
  const panel = h('div');
  const cancelRerun = rerun ? h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Cancel') : null;
  // Web Address shows only when the administrator allows URL import and Claude is usable for this user.
  const urlOn = urlImportOn(st);
  input.kind = startKind(input, urlOn);  // Web Address first and chosen by default when available (rerun keeps the source Claude read)
  const kinds = importKinds(urlOn);
  const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Recipe source' }, kinds.map(([k, label]) =>
    h('button', { type: 'button', role: 'tab', 'data-kind': k, onclick: () => { input.kind = k; input.picked = true; paint(); } }, label)));
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
    h('p', { class: 'sub' }, rerun ? RERUN_TEXT : sentence('Bring in the recipe, check it and save it. You match the ingredients on the recipe screen after')),
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
  const servings = field('Servings (optional)', { value: draft.servings, inputmode: 'decimal', autocomplete: 'off' });
  servings.input.addEventListener('input', () => { draft.servings = servings.input.value; });
  const list = h('ol', { class: 'review-lines' });
  const warns = (draft.warnings || []).map((w) => h('li', null, sentence(w)));

  // One compact row per ingredient: amount, unit (weights and volumes, no unit for "to taste"; a row's older unit stays as an extra
  // option), name and note,
  // then x. The fields write straight into the row, so untouched ones keep exactly what Claude filled (amountBoxValue keeps the exact
  // number until the amount text is edited). A package or fuzzy unit with no printed size shows its typical weight under it.
  function rowNode(r, i) {
    const n = i + 1;
    const input = (cls, label, attrs) => h('input', { type: 'text', class: 'review-in ' + cls, autocomplete: 'off', 'aria-label': label + ' of ingredient ' + n, ...attrs });
    const amount = input('review-amount', 'Amount', { value: r.amount == null ? '' : r.amount, inputmode: 'decimal', maxlength: '20' });
    const unit = unitControl(importUnitOptions(), String(r.unit == null ? '' : r.unit).trim(), { 'aria-label': 'Unit of ingredient ' + n });
    unit.classList.add('review-unit');
    const nm = input('review-name', 'Name', { value: r.name || '', placeholder: 'Ingredient', maxlength: '200' });
    const note = input('review-note', 'Note', { value: r.note || '', placeholder: 'Note', maxlength: '200' });
    const flag = h('p', { class: 'sub review-flag', id: 'flag-' + i });
    const paintFlag = () => {
      const t = reviewFlag(r);
      const p = t ? previews[previewKey(r)] : null;
      const weight = !t ? '' : p === undefined ? 'Looking up a typical weight' : p && p.grams && !p.reason ? unitPreviewText(p) : t;
      flag.textContent = [estimateNote(r), weight, pkgNote(r)].filter(Boolean).join('. ');
      flag.hidden = !flag.textContent;
    };
    flags[i] = paintFlag;
    const changed = () => { paintFlag(); lookupSoon(); };
    amount.addEventListener('input', () => { r.amount = amount.value; changed(); });
    amount.addEventListener('change', () => {  // words typed after the number: a measure becomes the unit, anything else the note
      if (!tidyAmountBox(r)) return;
      amount.value = r.amount;
      unit.value = r.unit;
      note.value = r.note;
      changed();
    });
    unit.addEventListener('change', () => { r.unit = unit.value; changed(); });
    nm.addEventListener('input', () => { r.name = nm.value; changed(); });
    note.addEventListener('input', () => { r.note = note.value; });
    paintFlag();
    return h('li', { class: 'review-row' },
      h('div', { class: 'review-fields' }, amount, unit, nm, note,
        h('button', { class: 'icon-btn review-remove', type: 'button', 'aria-label': 'Remove ingredient ' + n + (r.name ? ', ' + r.name : ''),
          onclick: () => { draft.rows.splice(i, 1); paintRows(); const b = list.querySelector('li:nth-child(' + Math.min(i + 1, draft.rows.length) + ') .review-amount'); if (b) b.focus(); } }, '×')),
      flag);
  }
  // Typical weights before saving, looked up once per unit and name and kept on the draft for the visit.
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
    flags.forEach((f) => f && f());
  }
  function paintRows(focusLast) {
    flags = [];
    clear(list);
    draft.rows.forEach((r, i) => list.appendChild(rowNode(r, i)));
    if (!draft.rows.length) list.appendChild(h('li', { class: 'sub' }, 'No ingredients yet.'));
    if (focusLast) { const last = list.querySelector('li:last-child .review-name'); if (last) last.focus(); }
    lookup();
  }
  const save = h('button', { class: 'btn primary review-save', type: 'button', onclick: async () => {
    const r = reviewBody(draft);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    save.disabled = true;
    show(status, message('Saving...'));
    let meal;
    try { meal = await api.importMeal(r.body); } catch (e) { save.disabled = false; show(status, message(e.message, 'error')); return; }
    if (draft.photoBlob) {  // the recipe exists now; a failed photo upload never blocks it (Add Photo on the recipe screen)
      try { await api.mealPhoto(meal.id, draft.photoBlob); } catch (e) { /* the recipe is saved; the photo can be added later */ }
    }
    ctx.flow.saved(meal);
  } }, 'Save Recipe');
  const nSteps = (draft.steps || []).filter((x) => String(x).trim()).length;
  const steps = h('details', { class: 'more review-steps' }, h('summary', null, nSteps ? 'Steps (' + nSteps + ')' : 'Steps'),
    h('p', { class: 'sub' }, 'The method, in order. Steps are notes only and never change the nutrition.'),
    stepsEditor(draft));

  root.appendChild(h('section', { class: 'screen import review' }, bar(ctx), h('h1', null, 'Check the Recipe'),
    h('p', { class: 'sub' }, sentence('Fix anything that looks wrong, then tap Save Recipe. You match the ingredients on the recipe screen')),
    costLine(draft.cost, 'This read'),
    sourceNode(draft.sourceUrl),
    warns.length ? h('ul', { class: 'warnings', role: 'alert' }, warns) : null,
    h('div', { class: 'grid2 review-head' }, name, servings),
    h('h2', null, 'Ingredients'), list,
    h('button', { class: 'btn', type: 'button', onclick: () => { draft.rows.push(blankRow()); paintRows(true); } }, 'Add Ingredient'),
    steps,
    importPhotoChoice(draft),
    status,
    h('div', { class: 'row wrap review-foot' }, save,
      canRerun(draft) ? h('button', { class: 'btn', type: 'button', onclick: () => { ctx.go('import', { rerun: true }); } }, RERUN_LABEL) : null,
      h('button', { class: 'btn ghost', type: 'button', onclick: ctx.flow.cancel }, 'Cancel'))));
  paintRows();
}
