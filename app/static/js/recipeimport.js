// Pure helpers for Import Recipe and Match Ingredients. No DOM access, safe to import from node.
import { parseAmount, fmtAmount, qtyText, servingText, matchedAmountText, sentence, stepsCheck, MEALS, MEAL_LABELS } from './util.js';

// Unit words found at the start of an ingredient line, mapped to the server's canonical units or a count word.
const UNIT_WORDS = {
  cup: 'cup', cups: 'cup', c: 'cup',
  tablespoon: 'tbsp', tablespoons: 'tbsp', tbsp: 'tbsp', tbs: 'tbsp', tbl: 'tbsp', T: 'tbsp',
  teaspoon: 'tsp', teaspoons: 'tsp', tsp: 'tsp', t: 'tsp',
  g: 'g', gram: 'g', grams: 'g', gr: 'g', kg: 'kg', kilogram: 'kg', kilograms: 'kg',
  oz: 'oz', ounce: 'oz', ounces: 'oz', lb: 'lb', lbs: 'lb', pound: 'lb', pounds: 'lb',
  ml: 'ml', milliliter: 'ml', milliliters: 'ml', millilitre: 'ml', millilitres: 'ml',
  l: 'l', liter: 'l', liters: 'l', litre: 'l', litres: 'l',
  clove: 'clove', cloves: 'clove', can: 'can', cans: 'can', slice: 'slice', slices: 'slice',
  pinch: 'pinch', pinches: 'pinch', dash: 'dash', dashes: 'dash', stick: 'stick', sticks: 'stick',
  piece: 'piece', pieces: 'piece', package: 'package', packages: 'package', pkg: 'package', bunch: 'bunch',
  sprig: 'sprig', sprigs: 'sprig', handful: 'handful', jar: 'jar', jars: 'jar', bottle: 'bottle',
};
const FLOZ = /^(?:fl\.?\s*oz\.?|fluid\s+ounces?)\b/i;
const AMOUNT = '(?:\\d+\\s+\\d+\\s*\\/\\s*\\d+|\\d+\\s*\\/\\s*\\d+|\\d*\\s*[\\u00bc-\\u00be\\u2150-\\u215e]|\\d+(?:[.,]\\d+)?)';
const LEAD = new RegExp('^(' + AMOUNT + ')(?:\\s*(?:-|\\u2013|to)\\s*(' + AMOUNT + '))?\\s*');

// A line that is a heading ("For the sauce:"), not an ingredient.
export function isHeading(line) { return /:\s*$/.test(line) || /^#+\s/.test(line); }

// Servings from a line like "Serves 4", "Servings: 6", "Makes 12" or "Yield: 8 servings", else null.
export function servingsFrom(line) {
  const m = /^(?:serves|servings?|makes|yield)\s*:?\s*(\d+(?:[.,]\d+)?)/i.exec(String(line || '').trim());
  if (!m) return null;
  const n = parseAmount(m[1]);
  return n > 0 && n <= 1000 ? n : null;
}

// One ingredient line split the way the server stores it: { text, amount, unit, name, note }, or null for a blank line.
// "1 1/2 cups flour, sifted" -> 1.5 cup flour (sifted). "2-3 cloves garlic" uses the average. "Salt to taste" has no amount.
export function parseIngredientLine(line) {
  const text = String(line == null ? '' : line).replace(/^\s*(?:[-*•▪]|\d+[.)](?=\s))\s*/, '').replace(/\s+/g, ' ').trim();
  if (!text) return null;
  let rest = text;
  let amount = null;
  const m = LEAD.exec(rest);
  if (m) {
    const a = parseAmount(m[1].replace(/\s+/g, ' ').trim());
    const b = m[2] ? parseAmount(m[2].replace(/\s+/g, ' ').trim()) : null;
    if (a != null) {
      amount = b != null && b > a ? (a + b) / 2 : a;
      rest = rest.slice(m[0].length);
    }
  }
  let unit = null;
  if (amount != null) {
    const fl = FLOZ.exec(rest);
    const w = /^([A-Za-z]+)\.?(?=\s|$)/.exec(rest);
    if (fl) { unit = 'floz'; rest = rest.slice(fl[0].length).trim(); }
    else if (w && UNIT_WORDS[UNIT_WORDS[w[1]] ? w[1] : w[1].toLowerCase()]) {  // "T" is a tablespoon, "t" a teaspoon
      unit = UNIT_WORDS[UNIT_WORDS[w[1]] ? w[1] : w[1].toLowerCase()];
      rest = rest.slice(w[0].length).trim();
      if (/^of\s/i.test(rest)) rest = rest.slice(3);
    }
  }
  const notes = [];
  rest = rest.replace(/\(([^)]*)\)/g, (_, inner) => { if (inner.trim()) notes.push(inner.trim()); return ' '; });
  const comma = rest.indexOf(',');
  if (comma >= 0) { notes.push(rest.slice(comma + 1).trim()); rest = rest.slice(0, comma); }
  const taste = /\s+(to taste|as needed|for serving|optional)$/i.exec(rest.trim());
  if (taste) { notes.unshift(taste[1].toLowerCase()); rest = rest.trim().slice(0, -taste[0].length); }
  const name = rest.replace(/\s+/g, ' ').trim() || text;
  const note = notes.filter(Boolean).join(', ') || null;
  return { text, amount, unit, name, note };
}

// Pasted text split locally (no Claude): headings and blank lines are dropped, "Serves 4" sets servings.
export function parseIngredientText(text) {
  let servings = null;
  const ingredients = [];
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const s = servingsFrom(line);
    if (s != null) { if (servings == null) servings = s; continue; }
    if (isHeading(line)) continue;
    const row = parseIngredientLine(line);
    if (row) ingredients.push(row);
  }
  return { name: '', servings, ingredients };
}

// ---------- review draft ----------

// A server or local recipe as the editable review draft. Amounts become text so the boxes keep what the person typed.
export function reviewDraft(recipe, extra) {
  const r = recipe || {};
  return {
    name: r.name || '', servings: r.servings == null ? '' : fmtAmount(r.servings), meals: [], warnings: [], cost: null,
    rows: (r.ingredients || []).map((i) => ({ amount: i.amount == null ? '' : qtyText(i.amount, i.unit), unit: i.unit || '', name: i.name || '', note: i.note || '', text: i.text || '' })),
    steps: (r.steps || []).filter((x) => typeof x === 'string'),
    ...(extra || {}),
  };
}

export const blankRow = () => ({ amount: '', unit: '', name: '', note: '', text: '' });

// The line as shown and stored. An edited row is rebuilt from its parts, so the stored text never disagrees with them.
export function rowText(row) {
  const a = parseAmount(row.amount);
  const head = [a == null ? '' : qtyText(a, row.unit), String(row.unit || '').trim(), String(row.name || '').trim()].filter(Boolean).join(' ');
  return head + (String(row.note || '').trim() ? ', ' + row.note.trim() : '');
}

// Validate the review draft and build the POST /api/meals/import body. Returns { error } or { body }.
export function reviewBody(draft) {
  const name = String(draft.name || '').trim();
  if (!name) return { error: 'Give the recipe a name.' };
  let servings = null;
  if (String(draft.servings || '').trim()) {
    servings = parseAmount(draft.servings);
    if (servings == null || servings <= 0 || servings > 1000) return { error: 'Servings must be a number above zero.' };
  }
  const rows = draft.rows.filter((r) => String(r.name || '').trim() || String(r.amount || '').trim() || String(r.unit || '').trim());
  if (!rows.length) return { error: 'Add at least one ingredient.' };
  const ingredients = [];
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const nm = String(r.name || '').trim();
    if (!nm) return { error: 'Ingredient ' + (i + 1) + ' needs a name.' };
    const raw = String(r.amount || '').trim();
    const amount = raw ? parseAmount(raw) : null;
    if (raw && amount == null) return { error: 'Check the amount of ' + nm + '.' };
    const unit = String(r.unit || '').trim() || null;
    const note = String(r.note || '').trim() || null;
    ingredients.push({ text: rowText(r).slice(0, 300), amount, unit, name: nm, note });
  }
  const st = stepsCheck(draft.steps);
  if (st.error) return st;
  return { body: { name, servings, meals: draft.meals || [], ingredients, steps: st.steps } };
}

// ---------- match state ----------

// check: a food is attached but its amount still needs confirming (Check Amount), so it counts for nothing yet.
export function matchState(item) { return item.skipped ? 'skipped' : item.check ? 'check' : item.food ? 'matched' : 'unmatched'; }

// "3 of 8 matched", plus skipped ones and amounts still to check when any.
export function matchCountText(meal) {
  let base = meal.matched + ' of ' + meal.needed + ' matched';
  if (meal.checks) base += ', ' + meal.checks + ' to check';
  return meal.skipped ? base + ', ' + meal.skipped + ' skipped' : base;
}

// What a recipe row on Add or Saved says under its name.
export function recipeSubText(meal, kcalText) {
  if (!meal.complete) return matchCountText(meal);
  const n = meal.needed != null ? meal.needed : meal.items.length;
  return n + (n === 1 ? ' item' : ' items') + ' - ' + kcalText + ' kcal';
}

// Index of the next unmatched (not skipped) or Check Amount row after `from`, wrapping round; -1 when every row is done.
export function nextUnmatched(items, from) {
  const n = items.length;
  for (let k = 1; k <= n; k++) {
    const i = (((from == null ? -1 : from) + k) % n + n) % n;
    const st = matchState(items[i]);
    if (st === 'unmatched' || st === 'check') return i;
  }
  return -1;
}

// Rows that can be ticked for Match Selected With Claude: everything not skipped.
export const selectableIds = (items) => items.filter((i) => !i.skipped).map((i) => i.id);

// Select All ticks the unmatched rows; when they are all ticked already it clears the ticks.
export function toggleAll(items, selected) {
  const open = items.filter((i) => matchState(i) === 'unmatched').map((i) => i.id);
  const all = open.length > 0 && open.every((id) => selected.indexOf(id) >= 0);
  return all ? [] : open;
}

export const toggleId = (selected, id) => (selected.indexOf(id) >= 0 ? selected.filter((x) => x !== id) : [...selected, id]);

// One Claude request takes at most `max` rows. The rest stay ticked for the next tap.
export function matchBatch(ids, max = 15) { return { send: ids.slice(0, max), rest: ids.slice(max) }; }

// Proposal lines: "Wheat flour, 1 1/2 cup, 188 g" with the kind as a word, so color is never the only cue. A proposal whose
// amount could not be worked out says so; Accept then attaches it as Check Amount.
export function proposalText(p) {
  if (!p || p.kind === 'none' || !p.food) return sentence(p && p.note ? p.note : 'Claude found no match. Search for it, or skip it');
  const name = p.food.brand ? p.food.name + ' (' + p.food.brand + ')' : p.food.name;
  return name + ', ' + matchedAmountText(p.amount, p.unit, p.grams) + (p.check ? ' (check the amount)' : '');
}

// What "ingredients" means in the Claude notice, for example "3 ingredients and their database matches".
export function matchWhat(n) { return n + (n === 1 ? ' ingredient' : ' ingredients') + ' with database candidates'; }
export function importWhat(kind, n) {
  return kind === 'photos' ? n + (n === 1 ? ' photo' : ' photos') + ' of a recipe' : 'your recipe text (' + n + ' characters)';
}

// ---------- Recipes tab ----------

// Meal tags as a short label: "Breakfast, Dinner", or "Untagged".
export function tagsText(meals) {
  const list = MEALS.filter((m) => (meals || []).indexOf(m) >= 0).map((m) => MEAL_LABELS[m]);
  return list.length ? list.join(', ') : 'Untagged';
}

// "Makes 4 servings" or "Makes 1 serving". A recipe without servings makes one.
export function servingsText(meal) {
  const n = meal && meal.servings > 0 ? meal.servings : 1;
  return 'Makes ' + servingText(n) + (n === 1 ? ' serving' : ' servings');
}

// The second line of a recipe on the Recipes tab: "3 of 8 matched" or "4 items - 520 kcal", then servings and tags.
export function recipeListSub(meal, kcalText) {
  return [recipeSubText(meal, kcalText), servingsText(meal), tagsText(meal.meals)].join(' · ');
}

// One line of per serving numbers: "520 kcal, 60 g carbs, 20 g protein, 18 g fat".
export function perServingText(meal, fmt) {
  const p = meal.per_serving || {};
  const v = (k) => fmt(p[k] == null ? 0 : p[k]);
  return v('kcal') + ' kcal, ' + v('carbs') + ' g carbs, ' + v('protein') + ' g protein, ' + v('fat') + ' g fat';
}

// The note on the log checklist: amounts for `want` servings of a recipe that makes `per`. '' for one serving of a one serving recipe.
export function logAmountText(want, per) {
  if (per > 1) return 'Amounts are for ' + servingText(want) + ' of ' + servingText(per) + ' servings.';
  return want !== 1 ? 'Amounts are for ' + servingText(want) + ' servings.' : '';
}

// ---------- Match Ingredients: last saved state, Back and Next ----------

// The part of a row that Match Ingredients can change.
const rowState = (it) => ({ id: it.id, food_id: it.food_id == null ? null : it.food_id, amount: it.food_id == null ? null : it.amount,
  unit: it.food_id == null ? null : it.unit, skipped: !!it.skipped, check: !!it.check });
const sameYield = (a, b) => (!a && !b) || (!!a && !!b && a.amount === b.amount && a.unit === b.unit);

// What the recipe looked like at the last save (opening the screen, or Next). Back writes this back.
export function matchSnapshot(meal) {
  return { items: (meal.items || []).map(rowState), servings: meal.servings, yield: meal.yield ? { ...meal.yield } : null };
}

const sameRow = (a, b) => a.food_id === b.food_id && a.amount === b.amount && a.unit === b.unit && a.skipped === b.skipped && a.check === b.check;

// What Back has to write to undo every change since the snapshot: { items: [bulk rows], meal: PATCH body or null }.
// Nothing to undo gives { items: [], meal: null }.
export function restoreBody(base, meal) {
  const now = {};
  (meal.items || []).forEach((it) => { now[it.id] = rowState(it); });
  const items = base.items.filter((b) => now[b.id] && !sameRow(b, now[b.id])).map((b) => (b.food_id == null
    ? { id: b.id, food_id: null, skipped: b.skipped }
    : { id: b.id, food_id: b.food_id, amount: b.amount, unit: b.unit, check: b.check, skipped: b.skipped }));
  const patch = {};
  if (base.servings !== meal.servings) patch.servings = base.servings;
  if (!sameYield(base.yield, meal.yield)) patch.yield = base.yield;
  return { items, meal: Object.keys(patch).length ? patch : null };
}

export function changedSince(base, meal) {
  const r = restoreBody(base, meal);
  return r.items.length > 0 || r.meal != null;
}

// Next moves to the next unmatched or Check Amount row. When no other row is left it becomes Done (save and leave).
export function nextStep(items, current) {
  const open = items.map((it, i) => [matchState(it), i]).filter(([s, i]) => (s === 'unmatched' || s === 'check') && i !== current);
  if (!open.length) return { done: true, index: -1 };
  return { done: false, index: nextUnmatched(items, current < 0 ? null : current) };
}

// Claude suggestions that Accept All would apply: a food was proposed and the row is not skipped.
export function pendingProposals(items, props) {
  return items.filter((it) => !it.skipped && props[it.id] && props[it.id].food).map((it) => ({ item: it, p: props[it.id] }));
}

export function acceptAllText(n) { return 'Accept ' + n + (n === 1 ? ' Suggested Match' : ' Suggested Matches'); }

// Rows Skip All marks skipped: the unmatched ones (Check Amount rows already have a food).
export function skipAllIds(items) { return items.filter((it) => matchState(it) === 'unmatched').map((it) => it.id); }

// ---------- serving size and logging part of a recipe ----------

// Units a total yield can use, in the server's spelling (core.YIELD_UNITS).
export const YIELD_UNITS = [['g', 'g'], ['kg', 'kg'], ['oz', 'oz'], ['lb', 'lb'], ['ml', 'ml'], ['l', 'l'], ['floz', 'fl oz'], ['cup', 'cup'], ['tbsp', 'tbsp'], ['tsp', 'tsp']];
const YIELD_LABEL = {};
YIELD_UNITS.forEach(([u, l]) => { YIELD_LABEL[u] = l; });

// "1200 g", "6 cup", "1 1/2 l" for a yield, or '' when none.
export function yieldText(y) { return y ? qtyText(y.amount, y.unit) + ' ' + (YIELD_LABEL[y.unit] || y.unit) : ''; }

// The serving size boxes as a PATCH body: { body: { servings, yield } } or { error }. A blank yield clears it.
export function servingSizeBody(servingsTextIn, amountText, unit) {
  const s = parseAmount(servingsTextIn);
  if (s == null || s <= 0 || s > 1000) return { error: 'Servings must be a number above zero.' };
  if (!String(amountText || '').trim()) return { body: { servings: s, yield: null } };
  const a = parseAmount(amountText);
  if (a == null || a <= 0 || a > 1000000) return { error: 'The total yield must be a number above zero, or blank.' };
  if (!YIELD_LABEL[unit]) return { error: 'Pick a unit for the total yield.' };
  return { body: { servings: s, yield: { amount: a, unit } } };
}

// The units a recipe is logged in (meal.portions from the server, or servings and percent for an older reply).
export function portionUnits(meal) {
  if (meal.portions && meal.portions.length) return meal.portions;
  return [{ unit: 'serving', label: 'servings', whole: meal.servings > 0 ? meal.servings : 1 }, { unit: 'pct', label: '% of recipe', whole: 100 }];
}

// Share of the whole recipe for amount (text or number) of unit: { fraction, amount } or { error }. Same rule as core.recipe_fraction.
export function portionFraction(meal, amount, unit) {
  const a = typeof amount === 'number' ? amount : parseAmount(amount);
  const p = portionUnits(meal).find((x) => x.unit === unit);
  if (a == null || !(a > 0) || !p) return { error: 'Enter an amount above zero.' };
  const fraction = a / p.whole;
  if (fraction > 100) return { error: 'That is more than 100 times the whole recipe.' };
  return { fraction, amount: a };
}

// Matched, not skipped rows scaled to a share of the whole recipe, for the log checklist.
export function portionItems(meal, fraction) {
  return (meal.items || []).filter((it) => it.food && !it.skipped && it.food_id != null)
    .map((it) => ({ ...it, amount: Math.round(it.amount * fraction * 10000) / 10000 }));
}

// The note on the log checklist: "Amounts are for 1 of 4 servings.", "Amounts are for 25% of the recipe.",
// "Amounts are for 250 g of 1200 g." '' for the whole of a one serving recipe.
export function portionNote(meal, amount, unit) {
  const p = portionUnits(meal).find((x) => x.unit === unit);
  if (!p) return '';
  if (unit === 'serving') return logAmountText(amount, p.whole);
  if (unit === 'pct') return amount === 100 ? 'Amounts are for the whole recipe.' : 'Amounts are for ' + fmtAmount(amount) + '% of the recipe.';
  const label = YIELD_LABEL[unit] || unit;
  return 'Amounts are for ' + qtyText(amount, unit) + ' ' + label + ' of ' + qtyText(p.whole, unit) + ' ' + label + '.';
}

// ---------- Import Recipe photos ----------

export const MAX_PHOTOS = 3;  // same as ai.MAX_IMAGES on the server
export const PHOTOS_TEXT = 'Choose up to 3 photos or screenshots of the ingredient list. Claude reads them and you check the result.';

// The photos to send: at most MAX_PHOTOS, with a clear warning when more were chosen. { files, warning }
export function photoPick(files, max = MAX_PHOTOS) {
  const all = files || [];
  if (all.length <= max) return { files: all.slice(), warning: '' };
  return { files: all.slice(0, max), warning: 'You chose ' + all.length + ' photos. Choose up to ' + max + '. Only the first ' + max + ' will be sent.' };
}

// The amount in `unit` for a share of the recipe, rounded for the box: 1 decimal for percent, grams and millilitres, else 3.
export function portionAmount(meal, fraction, unit) {
  const p = portionUnits(meal).find((x) => x.unit === unit);
  if (!p) return null;
  const f = ['pct', 'g', 'ml'].indexOf(unit) >= 0 ? 10 : 1000;
  return Math.round(fraction * p.whole * f) / f;
}
