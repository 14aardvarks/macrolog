import { api } from './api.js';
import { h, field, message, show, select, sourceLine } from './dom.js';
import { refreshControl } from './refresh.js';
import { sentence, canLookUp, parseDecimal, fmtAmount, MEALS, MEAL_LABELS, guessMeal, MICROS } from './util.js';

const NUM = [
  ['serving_amount', 'Serving amount', true, 'e.g. 2'],
  ['kcal', 'Calories per serving', true, ''],
  ['carbs', 'Carbs g', true, ''],
  ['protein', 'Protein g', true, ''],
  ['fat', 'Fat g', true, ''],
  ['fiber', 'Fiber g (optional)', false, ''],
  ['serving_g', 'Serving weight in g (optional)', false, ''],
  ['serving_ml', 'Serving volume in ml (optional)', false, ''],
  // Optional micronutrients in the collapsed More Nutrients section. Empty means unknown, never 0.
  ...MICROS.filter((m) => m.key !== 'fiber').map((m) => [m.key, m.label + ' ' + m.unit, false, '']),
];
const MORE = MICROS.filter((m) => m.key !== 'fiber').map((m) => m.key);

// Editable food form for manual entry and for Claude drafts.
// opts: { draft?, warnings?, barcode? }  ctx: { go, back }
export function renderFoodForm(root, opts, ctx) {
  const edit = opts.edit || null;  // an existing custom food from Saved
  const draft = edit || opts.draft || {};
  const locked = !!(edit && edit.in_use);  // used in a log or recipe: only the name and brand may change
  const fromAi = !edit && draft.source === 'ai';
  const described = fromAi && !!opts.described;  // a Claude estimate from a text description, not a label photo
  const f = {};
  const val = (k) => (draft[k] == null ? '' : typeof draft[k] === 'number' ? fmtAmount(draft[k]) : String(draft[k]));
  f.name = field('Name', { value: val('name'), autocomplete: 'off' });
  f.brand = field('Brand (optional)', { value: val('brand'), autocomplete: 'off' });
  f.serving_unit = field('Serving unit (g, ml, tbsp, cup, slice...)', { value: val('serving_unit'), autocapitalize: 'none', autocomplete: 'off' });
  f.label_text = field('Label serving text (optional)', { value: val('label_text'), autocomplete: 'off' });
  f.barcode = field('Barcode (optional)', { value: opts.barcode || draft.barcode || '', inputmode: 'numeric' });
  NUM.forEach(([k, label, , ph]) => { f[k] = field(label, { value: val(k), inputmode: 'decimal', placeholder: ph, autocomplete: 'off', disabled: locked }); });
  if (locked) f.serving_unit.input.disabled = true;

  const mealOpts = [{ value: 'none', label: MEAL_LABELS.none }, ...MEALS.map((m) => ({ value: m, label: MEAL_LABELS[m] }))];
  const mealSel = select(mealOpts, (ctx.settings && ctx.settings.default_meal) || guessMeal(new Date().getHours()), { 'aria-label': 'Meal' });
  const status = h('div', { 'aria-live': 'polite' });
  const confirm = h('input', { type: 'checkbox' });
  const saveBtn = h('button', { class: 'btn primary', type: 'submit' }, edit ? 'Save Changes' : fromAi ? 'Save and Continue' : 'Save Food');
  const warns = (opts.warnings || []).map((w) => h('li', null, sentence(w)));

  const form = h('form', { class: 'screen', novalidate: '', onsubmit: submit },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, edit ? 'Edit Food' : described ? 'Check What Claude Estimated' : fromAi ? 'Check What Claude Read' : 'Enter Food Manually'),
    edit || fromAi ? sourceLine(draft.source) : null,
    h('p', { class: 'sub' }, locked ? 'This food is in your log or a recipe, so only the name, brand and label text can change.' : described ? 'Fix anything that looks wrong and fill any empty boxes. Values are for one serving as described.'
      : fromAi ? 'Fix anything that looks wrong and fill any empty boxes. Values are per label serving.'
      : 'Values are per label serving, as printed.'),
    warns.length ? h('ul', { class: 'warnings', role: 'alert' }, warns) : null,
    f.name, f.brand,
    h('div', { class: 'grid2' }, f.serving_amount, f.serving_unit),
    f.label_text,
    f.kcal,
    h('div', { class: 'grid3' }, f.carbs, f.protein, f.fat),
    f.fiber,
    h('div', { class: 'grid2' }, f.serving_g, f.serving_ml),
    h('details', { class: 'more', open: MORE.some((k) => draft[k] != null) },
      h('summary', null, 'More Nutrients'),
      h('p', { class: 'sub' }, 'Optional. Leave a box empty when the label does not show it.'),
      h('div', { class: 'grid2' }, MORE.map((k) => f[k]))),
    f.barcode,
    edit ? (canLookUp(edit) ? refreshControl(edit, fillBlanks).el
      : h('p', { class: 'sub' }, 'Nothing to look up. Add a barcode to fill blank nutrients from Open Food Facts or USDA.')) : null,
    edit ? null : h('label', { class: 'field' }, h('span', null, 'Meal when you log it'), mealSel),
    fromAi ? h('label', { class: 'check' }, confirm, described ? ' I checked these values' : ' I checked these values against the label') : null,
    status, saveBtn);
  root.appendChild(form);
  markEmpty();

  function markEmpty() {
    for (const k of ['name', 'serving_unit', ...NUM.filter((n) => n[2]).map((n) => n[0])]) {
      f[k].input.setAttribute('aria-invalid', f[k].input.value.trim() === '' ? 'true' : 'false');
    }
  }
  // After Refresh Nutrients: put the new values into boxes that are still empty and open More Nutrients.
  function fillBlanks() {
    for (const k of ['fiber', ...MORE]) {
      if (edit[k] != null && f[k].input.value.trim() === '') f[k].input.value = fmtAmount(edit[k]);
    }
    if (MORE.some((k) => edit[k] != null)) form.querySelector('details.more').open = true;
  }
  function num(k) { const t = f[k].input.value.trim(); return t === '' ? null : parseDecimal(t); }

  async function submit(e) {
    e.preventDefault();
    markEmpty();
    const out = { source: fromAi ? 'ai' : 'custom', name: f.name.input.value.trim(), brand: f.brand.input.value.trim() || null,
      serving_unit: f.serving_unit.input.value.trim(), label_text: f.label_text.input.value.trim(),
      barcode: f.barcode.input.value.replace(/\D/g, '') || null };
    const bad = [];
    if (!out.name) bad.push('name');
    if (!out.serving_unit) bad.push('serving unit');
    for (const [k, label, required] of NUM) {
      out[k] = num(k);
      const raw = f[k].input.value.trim();
      if ((required && out[k] == null) || (raw !== '' && (out[k] == null || out[k] < 0))) bad.push(label.replace(' (optional)', ''));
    }
    if (out.serving_amount != null && out.serving_amount <= 0) bad.push('Serving amount');
    if (bad.length) { show(status, message('Check: ' + bad.join(', ') + '.', 'error')); return; }
    if (fromAi && !confirm.checked) { show(status, message(described ? 'Tick the box to confirm you checked the values.' : 'Tick the box to confirm the values match the label.', 'error')); return; }
    saveBtn.disabled = true;
    try {
      if (edit) {
        await api.patchFood(edit.id, locked ? { name: out.name, brand: out.brand, barcode: out.barcode, label_text: out.label_text } : out);
        ctx.back();
        return;
      }
      const food = await api.createFood(out);
      ctx.go('picker', { foodId: food.id, meal: mealSel.value === 'none' ? null : mealSel.value });
    } catch (err) {
      saveBtn.disabled = false;
      show(status, message(err.message, 'error'));
    }
  }
}
