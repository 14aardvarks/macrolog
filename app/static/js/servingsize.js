// Serving Size: how many servings a recipe makes and its optional total yield (amount and unit). Used by the recipe
// screen (Save Serving Size) and by the last step of Match Ingredients (saved as each box changes, undone by Back there).
import { api } from './api.js';
import { h, field, message, show, select } from './dom.js';
import { fmtAmount, fmtNum, qtyText } from './util.js';
import { YIELD_UNITS, servingSizeBody } from './recipeimport.js';

let seq = 0;

// meal: the recipe. opts: { live (save on change), onSaved(meal), status (an aria-live box) }.
// Returns { el, update(meal) }; update shows or hides Use Total of Ingredients without rebuilding the boxes.
export function servingSizeEditor(meal, opts) {
  const o = opts || {};
  const id = 'yield-' + (++seq);
  const status = o.status || h('div', { 'aria-live': 'polite' });
  const servings = field('Servings it makes', { value: fmtAmount(meal.servings), inputmode: 'decimal', autocomplete: 'off' });
  const amount = h('input', { type: 'text', id, inputmode: 'decimal', autocomplete: 'off', value: meal.yield ? qtyText(meal.yield.amount, meal.yield.unit) : '',
    'aria-describedby': id + '-help' });
  const unit = select(YIELD_UNITS.map(([value, label]) => ({ value, label })), meal.yield ? meal.yield.unit : 'g', { 'aria-label': 'Total yield unit' });
  const useTotal = h('button', { class: 'btn small', type: 'button' }, 'Use Total of Ingredients');
  const totalNote = h('span', { class: 'sub' });
  const save = o.live ? null : h('button', { class: 'btn primary', type: 'button' }, 'Save Serving Size');
  let current = meal;

  async function send(body) {
    if (save) save.disabled = true;
    try {
      current = await api.patchMeal(current.id, body);
      update(current);
      show(status, o.live ? null : message('Serving size saved.'));
      if (o.onSaved) o.onSaved(current);
    } catch (e) { show(status, message(e.message, 'error')); } finally { if (save) save.disabled = false; }
  }
  function commit() {
    const r = servingSizeBody(servings.input.value, amount.value, unit.value);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    send(r.body);
  }
  function update(m) {
    current = m;
    const g = !m.yield && m.ingredient_grams != null ? m.ingredient_grams : null;
    useTotal.hidden = g == null;
    totalNote.textContent = g == null ? '' : fmtNum(g, 1) + ' g from the matched ingredients';
  }
  useTotal.addEventListener('click', () => {
    if (current.ingredient_grams == null) return;
    amount.value = fmtAmount(current.ingredient_grams);
    unit.value = 'g';
    commit();  // one tap fills it in grams and saves
  });
  if (o.live) {
    servings.input.addEventListener('change', commit);
    amount.addEventListener('change', commit);
    unit.addEventListener('change', () => { if (amount.value.trim()) commit(); });
  } else {
    save.addEventListener('click', commit);
  }
  update(meal);
  const el = h('div', { class: 'serving-size' },
    servings,
    h('div', { class: 'field' }, h('label', { for: id }, 'Total yield (optional)'),
      h('div', { class: 'row yield-row' }, amount, unit)),
    h('p', { class: 'sub', id: id + '-help' }, 'What the whole recipe weighs or measures, like 1200 g or 6 cup. Then you can log it by weight or volume.'),
    h('div', { class: 'row wrap' }, useTotal, totalNote),
    o.status ? null : status,
    save);
  return { el, update };
}
