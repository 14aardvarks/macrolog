// Pure helpers. No DOM access, safe to import from node.

export const MEALS = ['breakfast', 'lunch', 'dinner', 'snack', 'dessert'];
export const MEAL_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack', dessert: 'Dessert', none: 'No meal' };

// Parse "1,5" or "1.5" or " 2 " into a number. Returns null for anything that is not a plain decimal.
export function parseDecimal(text) {
  if (typeof text === 'number') return Number.isFinite(text) ? text : null;
  const s = String(text == null ? '' : text).trim().replace(/\s+/g, '').replace(',', '.');
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

const UNICODE_FRACTIONS = {
  '\u00bd': [1, 2], '\u00bc': [1, 4], '\u00be': [3, 4], '\u2153': [1, 3], '\u2154': [2, 3],
  '\u2155': [1, 5], '\u2156': [2, 5], '\u2157': [3, 5], '\u2158': [4, 5], '\u2159': [1, 6], '\u215a': [5, 6],
  '\u215b': [1, 8], '\u215c': [3, 8], '\u215d': [5, 8], '\u215e': [7, 8],
};

// Amount typed by a person: "1.5", "1,5", "1/2", "1 1/2", "1\u00bd", "\u00be". Returns a number, or null when it is not an amount.
// Zero is allowed here (callers decide); negatives, empty text, "1/0" and words give null.
export function parseAmount(text) {
  if (typeof text === 'number') return Number.isFinite(text) && text >= 0 ? text : null;
  let s = String(text == null ? '' : text).trim().replace(/\s+/g, ' ');
  if (!s) return null;
  const plain = /\d \d/.test(s) ? null : parseDecimal(s);  // "1 2" is not twelve
  if (plain != null) return plain >= 0 ? plain : null;
  const frac = (num, den) => (den > 0 ? num / den : null);
  let m = /^(?:(\d+)\s*)?([\u00bc-\u00be\u2150-\u215e])$/.exec(s);  // "3", "1\u00bd", "1 \u00bd", "\u00bd"
  if (m && UNICODE_FRACTIONS[m[2]]) {
    const [n, d] = UNICODE_FRACTIONS[m[2]];
    return (m[1] ? Number(m[1]) : 0) + n / d;
  }
  m = /^(\d+)\s*\/\s*(\d+)$/.exec(s);  // "1/2"
  if (m) return frac(Number(m[1]), Number(m[2]));
  m = /^(\d+) (\d+)\s*\/\s*(\d+)$/.exec(s);  // "1 1/2"
  if (m) {
    const f = frac(Number(m[2]), Number(m[3]));
    return f == null ? null : Number(m[1]) + f;
  }
  return null;
}

export function roundTo(n, decimals) {
  const f = Math.pow(10, decimals);
  return Math.round((n + Number.EPSILON * Math.sign(n)) * f) / f;
}

// "12.5", "12", "0.125". Trims trailing zeros. null and NaN give an empty string.
export function fmtNum(n, maxDecimals = 1) {
  if (n == null || !Number.isFinite(n)) return '';
  const s = roundTo(n, maxDecimals).toFixed(maxDecimals);
  return s.indexOf('.') < 0 ? s : s.replace(/0+$/, '').replace(/\.$/, '');
}

// Amount for display and typing. Up to 3 decimals so 0.125 cup stays exact.
export function fmtAmount(n) { return fmtNum(n, 3); }

// ---------- serving and percent display ----------

export const SERVING = 'serving';
export const PCT = 'pct';
const SERVING_UNIT = SERVING;
const PCT_UNIT = PCT;

// Friendly cooking fractions, as numerators over denominators. Thirds, quarters and eighths only: no fifths or sixths.
const BASE_FRACTIONS = [[0, 1], [1, 8], [1, 4], [1, 3], [1, 2], [2, 3], [3, 4], [1, 1]];
const MEASURE_FRACTIONS = [[0, 1], [1, 8], [1, 4], [3, 8], [1, 3], [1, 2], [5, 8], [2, 3], [3, 4], [7, 8], [1, 1]];

// Nearest cooking fraction for any amount: 0.3125 -> "1/3", 1.34 -> "1 1/3", 2.5 -> "2 1/2", 0.05 -> "1/8" (never 0 for a positive
// amount). measure adds 3/8, 5/8 and 7/8 for cup, tbsp, tsp and fl oz. null only for negatives and non-numbers.
export function fractionText(n, measure = false) {
  if (!Number.isFinite(n) || n < 0) return null;
  if (n === 0) return '0';
  const set = measure ? MEASURE_FRACTIONS : BASE_FRACTIONS;
  let whole = Math.floor(n + 1e-9);
  const rest = Math.max(0, n - whole);
  let best = set[0];
  for (const f of set) if (Math.abs(rest - f[0] / f[1]) < Math.abs(rest - best[0] / best[1]) - 1e-12) best = f;
  if (best[0] === best[1]) { whole += 1; best = set[0]; }
  if (best[0] === 0) return whole ? String(whole) : '1/8';
  return (whole ? whole + ' ' : '') + best[0] + '/' + best[1];
}

// Useful decimal for a cooking amount: at most 2 places, 1 when that is close enough (0.313 -> "0.3", 0.25 -> "0.25", 0.33 -> "0.33",
// 1.5 -> "1.5"), 1 place from 10 up, never "0" for a positive amount (0.001 -> "0.01").
export function decimalText(n) {
  if (!Number.isFinite(n)) return '';
  if (n === 0) return '0';
  if (n < 0) return fmtNum(n, 2);
  if (n >= 10) return fmtNum(n, 1);
  const one = roundTo(n, 1);
  if (one > 0 && Math.abs(n - one) <= 0.015) return fmtNum(one, 1);
  return fmtNum(Math.max(roundTo(n, 2), 0.01), 2);
}

// How amounts are shown: 'fraction' (1/4, 1 1/2) or 'decimal' (0.25, 1.5). Set from the user's setting.
// Fractions apply to servings, cooking measures and counts (fractionUnit); metric, weights and percent always show decimals.
// Typing accepts both whatever this is.
let amountFormat = 'fraction';
export function setAmountFormat(f) { amountFormat = f === 'decimal' ? 'decimal' : 'fraction'; }
export function getAmountFormat() { return amountFormat; }

// Free text unit to the server's canonical name: "Cups" -> cup, "tablespoons" -> tbsp, "fl oz" -> floz, "grams" -> g,
// "%" -> pct. Count words come back lowercase and singular ("cloves" -> clove). Empty gives ''.
const UNIT_ALIASES = {
  g: 'g', gm: 'g', gr: 'g', gram: 'g', gramme: 'g', kg: 'kg', kilo: 'kg', kilogram: 'kg', mg: 'mg', milligram: 'mg', mcg: 'mcg',
  oz: 'oz', ounce: 'oz', lb: 'lb', lbs: 'lb', pound: 'lb', ml: 'ml', milliliter: 'ml', millilitre: 'ml', l: 'l', liter: 'l', litre: 'l',
  floz: 'floz', 'fl oz': 'floz', 'fluid ounce': 'floz', 'fluid oz': 'floz', cup: 'cup', c: 'cup',
  tbsp: 'tbsp', tbs: 'tbsp', tbl: 'tbsp', tablespoon: 'tbsp', tsp: 'tsp', teaspoon: 'tsp',
  serving: SERVING_UNIT, svg: SERVING_UNIT, '%': PCT_UNIT, pct: PCT_UNIT, percent: PCT_UNIT, '% of serving': PCT_UNIT,
};
export function canonUnit(unit) {
  const raw = String(unit == null ? '' : unit).trim();
  if (raw === 'T') return 'tbsp';
  if (raw === 't') return 'tsp';
  const t = raw.toLowerCase().replace(/[.,()]/g, ' ').replace(/\s+/g, ' ').trim();
  if (!t) return raw.indexOf('%') === 0 ? PCT_UNIT : '';
  if (UNIT_ALIASES[t]) return UNIT_ALIASES[t];
  const one = t.split(' ').map((w) => (/(ss|sh|ch|x|z)es$/.test(w) ? w.slice(0, -2) : /[^s]s$/.test(w) && w.length > 2 ? w.slice(0, -1) : w)).join(' ');
  return UNIT_ALIASES[one] || UNIT_ALIASES[t.replace(/ /g, '')] || one;
}

// ---------- custom units ----------
// A unit control offers the known units and Custom, which reveals a text box for the user's own word (pinch, can, clove, to taste).
// Empty stays blank. Typed units are kept as typed.
export const CUSTOM_UNIT = '__custom__';
export const CUSTOM_UNIT_LABEL = 'Custom';
export const CUSTOM_UNIT_MAX = 30;
export const CUSTOM_UNIT_HINT = 'pinch, can, clove';
// A typed unit as it is saved: control characters dropped, spaces tidied, at most CUSTOM_UNIT_MAX characters.
export function cleanUnitText(text) {
  return String(text == null ? '' : text).replace(/[\u0000-\u001f\u007f-\u009f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, CUSTOM_UNIT_MAX).trim();
}
// "Cups" -> cup, "Count" -> count and a typed word as typed ("Pinch" stays Pinch). Blank, "-" and "none" give ''.
export function unitToSave(text) {
  const t = cleanUnitText(text);
  if (!t || t === '-' || t.toLowerCase() === 'none') return '';
  const c = canonUnit(t);
  return KNOWN_UNITS.indexOf(c) >= 0 ? c : t;
}
const KNOWN_UNITS = ['g', 'kg', 'oz', 'lb', 'ml', 'l', 'floz', 'cup', 'tbsp', 'tsp', SERVING_UNIT, PCT_UNIT, 'count'];
// The choices of a unit select from food.units: the blank unit is left out (Custom replaces it) and count shows lowercase.
export function unitChoices(units) {
  return (units || []).filter((u) => u.unit !== '').map((u) => ({ value: u.unit, label: u.unit === 'count' ? 'count' : u.label, estimated: !!u.estimated }));
}
// True for a typed unit (not blank, not one of the choices).
export function isCustomUnit(unit, choices) {
  return !!unit && !(choices || []).some((c) => c.value === unit);
}

// Units that always show decimals: metric, weights (oz is a weight) and percent. Everything else, servings, cups, spoons,
// fl oz and counts (slice, clove, no unit at all) reads as a tidy fraction in fraction mode.
export const DECIMAL_UNITS = ['g', 'kg', 'mg', 'mcg', 'ml', 'l', 'oz', 'lb', PCT_UNIT];
const MEASURE_UNITS = ['cup', 'tbsp', 'tsp', 'floz'];
export function fractionUnit(unit) { return DECIMAL_UNITS.indexOf(canonUnit(unit)) < 0; }

// The one place an amount becomes text: "1 1/2" or "1.5" for a cup, "30" for grams. In fraction mode a cooking amount always
// rounds to the nearest friendly fraction (0.313 cup shows 1/3); in decimal mode to a short decimal (0.3); weights and metric keep
// their existing rounding.
// Calories and nutrients never come here; they use fmtNum.
export function qtyText(n, unit, format = amountFormat) {
  const x = Number(n);
  if (n == null || !Number.isFinite(x)) return '';
  if (!fractionUnit(unit)) return fmtAmount(x);
  if (format === 'decimal') return decimalText(x);
  return fractionText(x, MEASURE_UNITS.indexOf(canonUnit(unit)) >= 0) || fmtAmount(x);
}

// A serving count as text in the chosen format (or the one passed in).
export function servingText(n, format = amountFormat) { return qtyText(n, SERVING_UNIT, format); }

// Short unit name for lists: "pct" shows as "% of serving".
export function unitLabel(unit) { return unit === PCT ? '% of serving' : unit === 'count' ? 'count' : unit == null ? '' : unit; }

// "1/2 serving", "1 serving", "1 1/2 servings", "25% of a serving", "30 g", "1 1/2 cup", "2 slice".
export function amountText(amount, unit, format) {
  const n = Number(amount);
  if (unit === PCT) return fmtAmount(n) + '% of a serving';
  if (unit === SERVING) {
    return servingText(n, format) + (n > 1 ? ' servings' : ' serving');
  }
  return (qtyText(n, unit, format) + ' ' + (unit || '')).trim();  // a blank unit shows the bare amount
}

// ---------- picker math ----------

export function stepDecimals(step) {
  let d = 0;
  while (d < 6 && Math.abs(roundTo(step, d) - step) > 1e-9) d++;
  return d;
}

export function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

// Nearest multiple of step, never below one step, free of float noise.
export function snapToStep(v, step) {
  if (!(step > 0)) return v;
  const n = Math.max(1, Math.round(v / step));
  return roundTo(n * step, stepDecimals(step));
}

export const MAX_WHEEL_ITEMS = 600;

// Upper bound for the wheel: room for the current value to double, at least 200 steps, capped.
export function wheelMax(step, value) {
  const wanted = Math.max(200, Math.ceil((value * 2) / step));
  return Math.min(MAX_WHEEL_ITEMS, wanted) * step;
}

// Values step, 2*step ... up to max (inclusive), as clean numbers.
export function valueList(step, max) {
  const d = stepDecimals(step);
  const count = Math.max(1, Math.min(MAX_WHEEL_ITEMS, Math.floor(max / step + 1e-9)));
  const out = [];
  for (let i = 1; i <= count; i++) out.push(roundTo(i * step, d));
  return out;
}

// Index in a valueList of the entry closest to v (clamped).
export function nearestIndex(list, v) {
  let best = 0;
  for (let i = 1; i < list.length; i++) if (Math.abs(list[i] - v) < Math.abs(list[best] - v)) best = i;
  return best;
}

export const SERVING_MAX = 10;
export const PCT_MAX = 500;

// Row text on the amount wheel: the same rule as everywhere else (qtyText).
export function amountLabel(unit, v, format) { return qtyText(v, unit, format); }

// Values for the amount wheel of one unit: its step up to a sensible top (10 servings, 500 percent, else wheelMax).
export function amountValues(unit, step, value) {
  if (unit === SERVING) return valueList(step, SERVING_MAX);
  if (unit === PCT) return valueList(step, PCT_MAX);
  return valueList(step, wheelMax(step, Number(value) > 0 ? Number(value) : 0));
}

// Make sure v is a row: returns { values, index }. A value that is not on the list is inserted in order, so it stays selected.
export function withValue(values, v) {
  const i = values.findIndex((x) => Math.abs(x - v) < 1e-9);
  if (i >= 0) return { values: values.slice(), index: i };
  const at = values.findIndex((x) => x > v);
  const index = at < 0 ? values.length : at;
  const out = values.slice();
  out.splice(index, 0, v);
  return { values: out, index };
}

// Which row a scroll offset lands on.
export function indexFromScroll(scrollTop, rowHeight, length) {
  return clamp(Math.round(scrollTop / rowHeight), 0, Math.max(0, length - 1));
}

// ---------- day view ----------

// Group entries by meal in a fixed order. Empty groups are dropped. Entries without a meal go last.
export function groupByMeal(entries, otherLabel = 'No meal') {
  const groups = MEALS.map((m) => ({ meal: m, label: MEAL_LABELS[m], entries: [], kcal: 0 }));
  const other = { meal: null, label: otherLabel, entries: [], kcal: 0 };
  for (const e of entries || []) {
    const g = groups.find((x) => x.meal === e.meal) || other;
    g.entries.push(e);
    g.kcal += Number(e.kcal) || 0;
  }
  return [...groups, other].filter((g) => g.entries.length).map((g) => ({ ...g, kcal: roundTo(g.kcal, 1) }));
}

// Like groupByMeal, but every meal is listed, empty ones too (Today shows a quick add row under each). No meal only when it has entries.
export function mealGroupsAll(entries, otherLabel = 'No meal') {
  const have = groupByMeal(entries, otherLabel);
  return [...MEALS.map((m) => have.find((g) => g.meal === m) || { meal: m, label: MEAL_LABELS[m], entries: [], kcal: 0 }), ...have.filter((g) => !MEALS.includes(g.meal))];
}

// Accessible names for Today's quick add buttons, for example "Add to Lunch".
export const QUICK_ACTIONS = ['add', 'scan', 'search'];
export function quickLabel(kind, meal) {
  const w = MEAL_LABELS[meal] || '';
  return (kind === 'add' ? 'Add to ' : kind === 'scan' ? 'Scan for ' : 'Search for ') + w;
}

// Rows of a checklist: {checked, amount (typed text), food_id, unit, name}. Only checked rows count.
// Returns {items} or {error}.
export function checkedItems(rows) {
  const items = [];
  for (const r of rows) {
    if (!r.checked) continue;
    const a = parseAmount(r.amount);
    if (a == null || a <= 0) return { error: 'Check the amount for ' + r.name + '.' };
    items.push({ food_id: r.food_id, amount: a, unit: r.unit });
  }
  return items.length ? { items } : { error: 'Tick at least one item.' };
}

// Text for an amount box: follows the fraction/decimal setting for the unit (qtyText). Typing accepts both.
export const rowAmountText = (amount, unit) => qtyText(amount, unit);

// An amount box shows rounded text (0.4 cup reads 3/8), so the stored number must survive reopening and saving. amountBoxValue gives
// the exact number the box was filled from while its text is still what was shown, and otherwise parses what was typed (fractions
// like 1 1/2, 1/3 and decimals). A blank or unreadable box gives null.
export function amountBoxValue(text, shownText, exact) {
  const n = Number(exact);
  if (exact != null && exact !== '' && Number.isFinite(n) && String(text == null ? '' : text).trim() === String(shownText == null ? '' : shownText).trim()) return n;
  return parseAmount(text);
}

// The same rule for one live box: set() records the exact number and the text shown for it (returns the text to put in the box),
// value(boxText) reads it back. read(boxText) gives the exact number while the text is unchanged, else the raw text for parseAmount.
export function amountMemo(n, unit, format) {
  let exact = null;
  let shown = '';
  const memo = {
    keep(num, text) { exact = num == null || !Number.isFinite(Number(num)) ? null : Number(num); shown = String(text == null ? '' : text); return shown; },
    set(num, u, f) { return memo.keep(num, qtyText(num, u, f)); },
    shown: () => shown,
    exact: () => exact,
    value: (text) => amountBoxValue(text, shown, exact),
    read: (text) => { const v = amountBoxValue(text, shown, exact); return v !== null && v === exact ? exact : text; },
  };
  if (n !== undefined) memo.set(n, unit, format);
  return memo;
}

// Rows of the recipe screen are kept as drafts {checked, amount (text), unit} while the picker is open.
// Returns a copy with row i set to the picked amount and unit and ticked. Other rows are untouched.
export function applyRowPick(draft, i, amount, unit) {
  return draft.map((r, k) => (k === i ? { ...r, checked: true, amount: rowAmountText(amount, unit), exact: amount, shown: rowAmountText(amount, unit), unit } : { ...r }));
}

// A draft is only restored when it was saved for this recipe, from this point in the history, and has one row per item.
export const draftFits = (draft, mealId, depth, count) =>
  !!draft && draft.mealId === mealId && draft.depth === depth && Array.isArray(draft.rows) && draft.rows.length === count;

// Save as recipe is allowed with at least one ticked row and a non-empty name.
export const canSaveRecipe = (ticked, name) => ticked > 0 && String(name || '').trim() !== '';

// ---------- meal filter on the Add screen ----------

export const MEAL_FILTERS = ['all', ...MEALS];
export const MEAL_FILTER_LABELS = { all: 'All', ...MEAL_LABELS };

// Items for the chosen meal. 'all' (or anything unknown) keeps everything. Items with no meal show only under 'all'.
// An item matches through item.meal (a string) or item.meals (an array, used by recipes).
export function filterByMeal(items, meal) {
  const list = items || [];
  if (!MEALS.includes(meal)) return list.slice();
  return list.filter((it) => (Array.isArray(it.meals) ? it.meals.includes(meal) : it.meal === meal));
}

// Saved favorites and recipes carry meals (their tags) and counts ({meal: times logged}). Untagged items show under every meal.
// For a chosen meal the items logged most often as that meal come first, the rest keep their order.
export function filterSaved(items, meal) {
  const list = items || [];
  if (!MEALS.includes(meal)) return list.slice();
  const count = (it) => (it.counts && it.counts[meal]) || 0;
  return list.filter((it) => !(it.meals && it.meals.length) || it.meals.includes(meal))
    .map((it, i) => ({ it, i })).sort((x, y) => count(y.it) - count(x.it) || x.i - y.i).map((x) => x.it);
}

// Paging for long lists: the first `shown` items and how many are left.
export const PAGE_SIZE = 20;
export function pageOf(items, shown) {
  const list = items || [];
  return { items: list.slice(0, shown), more: Math.max(0, list.length - shown) };
}

// Refresh Nutrients. A food can be looked up again with a source id (Open Food Facts or USDA) or a barcode.
export const REFRESH_CAP = 10;
export function missingMicros(food) {
  return MICROS.filter((m) => !food || food[m.key] == null).map((m) => m.key);
}
export function canLookUp(food) {
  if (!food) return false;
  const sid = String(food.source_id == null ? '' : food.source_id).trim();
  if ((food.source === 'off' && sid) || (food.source === 'fdc' && /^\d+$/.test(sid))) return true;
  return String(food.barcode == null ? '' : food.barcode).replace(/\D/g, '').length >= 8;
}
// Shows the button only when the food can be looked up and has a blank nutrient.
export function canRefresh(food) { return canLookUp(food) && missingMicros(food).length > 0; }
// The first `cap` foods worth refreshing, and how many more were left for another click.
export function refreshTargets(foods, cap = REFRESH_CAP) {
  const all = (foods || []).filter(canRefresh);
  return { todo: all.slice(0, cap), left: Math.max(0, all.length - cap) };
}
// Logged foods from GET /api/foods/missing-nutrients. ids already checked in this visit (done) are skipped, so tapping again
// continues instead of asking the same foods twice. total is every food still to check, todo the next batch, left the rest.
export function pendingPlan(ids, done, cap = REFRESH_CAP) {
  const all = (ids || []).filter((id) => !done || !done.has(id));
  return { todo: all.slice(0, cap), left: Math.max(0, all.length - cap), total: all.length };
}
// The line shown above the button: how many foods the next tap checks.
export function planText(plan, cap = REFRESH_CAP) {
  const word = (n) => n + (n === 1 ? ' food' : ' foods');
  if (!plan.total) return 'No logged foods need a refresh';
  return plan.total > cap ? cap + ' of ' + word(plan.total) + ' will be checked now' : word(plan.total) + ' will be checked';
}
// Summary after a Refresh All Missing run. checked foods asked, filled values added, failed errors, stopped says a rate limit ended the run early.
export function bulkSummary({ checked, filled, failed, left, stopped, byClaude, note }) {
  const word = (n, one, many) => n + ' ' + (n === 1 ? one : many);
  const parts = ['Checked ' + word(checked, 'food', 'foods') + ' and filled ' + word(filled, 'value', 'values')
    + (byClaude ? ' (' + byClaude + ' estimated by Claude)' : '')];
  if (note) parts.push(note);
  if (failed) parts.push(word(failed, 'food', 'foods') + ' could not be refreshed');
  if (stopped) parts.push('Stopped at the rate limit, try again later');
  else if (left) parts.push(word(left, 'food', 'foods') + ' left, tap again to continue');
  return parts.join('. ');
}

// The tag set after tapping a meal chip, in breakfast to dessert order.
export function toggleMeal(meals, meal) {
  const set = new Set(meals || []);
  if (set.has(meal)) set.delete(meal); else set.add(meal);
  return MEALS.filter((m) => set.has(m));
}

// "lunch" for a meal, '' for All.
export function mealWord(meal) { return MEALS.includes(meal) ? MEAL_LABELS[meal].toLowerCase() : ''; }

// Ends a sentence with a period when it has no closing mark yet. Short fragments (under 4 words) are left alone.
// Used for text the server sends.
export function sentence(text) {
  const t = String(text == null ? '' : text).trim();
  return t && t.split(/\s+/).length >= 4 && !/[.?!\u2026]$/.test(t) ? t + '.' : t;
}

// "1 item", "2 items". Counts of things shown in lists use this, so a single one never reads "1 items".
export function plural(n, one, many = one + 's') { return n + ' ' + (n === 1 ? one : many); }

// Confirm text for deleting a food, the same everywhere (Saved, the edit form). Deleting only hides it: the log and recipes keep it.
export const DELETE_FOOD_CONFIRM = 'Delete This Food? ' + sentence('It will be removed from your lists') + ' ' + sentence('Past log entries and recipes keep it');

// Where a food came from. The stored values are off, fdc, custom and ai (a barcode is only how a food was found, not a source).
const SOURCE_LABELS = { off: 'Open Food Facts', fdc: 'USDA', custom: 'Custom', ai: 'Claude' };
export function sourceLabel(source) { return Object.prototype.hasOwnProperty.call(SOURCE_LABELS, source) ? SOURCE_LABELS[source] : ''; }
// Claude values are estimates read from a photo, so only they carry a note. Regular search results never do.
export function isEstimate(source) { return source === 'ai'; }
export function sourceNote(source) { return isEstimate(source) ? sentence('Values are estimates from Claude. Check them against the label') : ''; }

// Text for an empty list. kind is favorites, yesterday or recipes. hasAny says the unfiltered list had items.
export function emptyText(kind, meal, hasAny) {
  const w = mealWord(meal);
  if (kind === 'yesterday') return w ? 'Nothing for ' + w + ' yesterday.' : 'Nothing from yesterday.';
  if (kind === 'recent') return w ? 'No past foods logged as ' + w + '. Choose All to see every past food.' : 'No past foods yet. Foods you log show up here.';
  const one = kind === 'recipes' ? 'recipe' : 'favorite';
  if (w && hasAny) return 'No ' + kind + ' tagged ' + w + '. Choose All to see every ' + one + '.';
  if (kind === 'recipes') return 'No saved recipes. Make one on the Recipes tab, or tap "Save As Recipe" under a meal on Today.';
  return 'No favorites yet. Tap the star on a food to add one.';
}

// Dessert is never guessed: it is only ever chosen by hand.
export function guessMeal(hour) {
  if (hour < 10) return 'breakfast';
  if (hour < 14) return 'lunch';
  if (hour < 17) return 'snack';
  return 'dinner';
}

// ---------- dates ----------

function pad(n) { return String(n).padStart(2, '0'); }

// The client's own calendar date, YYYY-MM-DD.
export function localDate(d = new Date()) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

export function addDays(ymd, n) {
  const [y, m, d] = ymd.split('-').map(Number);
  return localDate(new Date(y, m - 1, d + n, 12));
}

export function dayLabel(ymd, today) {
  if (ymd === today) return 'Today';
  if (ymd === addDays(today, -1)) return 'Yesterday';
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(y, m - 1, d, 12).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

// ---------- targets ----------

// "1200 / 3000 (40%)"
export function progressText(value, target, percent, unit = '') {
  return fmtNum(value, 0) + ' / ' + fmtNum(target, 0) + unit + ' (' + (percent == null ? 0 : percent) + '%)';
}

// "1800 left" or "200 over"
export function remainingText(remaining, unit = '') {
  if (remaining == null) return '';
  return remaining >= 0 ? fmtNum(remaining, 0) + unit + ' left' : fmtNum(-remaining, 0) + unit + ' over';
}

// Bar fill width, 0..100
export function barWidth(percent) { return clamp(Number(percent) || 0, 0, 100); }

// Bar color level by percent of goal: ok up to and including 75, near above 75, over above 100.
export const NEAR_PERCENT = 75;
export const OVER_PERCENT = 100;
export function barLevel(pct) {
  const p = Number(pct);
  if (!Number.isFinite(p)) return 'ok';
  return p > OVER_PERCENT ? 'over' : p > NEAR_PERCENT ? 'near' : 'ok';
}

// { level, cue } for a bar. No goal (no target, or an unknown total) gives ok and no cue. The percent comes from the exact
// total and target, so rounding for display never moves a bar across a line.
export function barState(total, target) {
  const t = Number(target);
  if (total == null || !(t > 0)) return { level: 'ok', cue: '' };
  const level = barLevel(Number(total) / t * 100);
  return { level, cue: level === 'over' ? 'Over' : level === 'near' ? 'Near Limit' : '' };
}

export function pctTotal(a, b, c) { return roundTo((a || 0) + (b || 0) + (c || 0), 2); }

// ---------- misc ----------

export function debounce(fn, ms) {
  let t = null;
  const wrapped = (...args) => {
    clearTimeout(t);
    t = setTimeout(() => { t = null; fn(...args); }, ms);
  };
  wrapped.cancel = () => { clearTimeout(t); t = null; };
  return wrapped;
}

// Keep only digits (for typed or scanned barcodes).
export function digitsOnly(s) { return String(s || '').replace(/\D/g, ''); }

// Scale a size so its longest side is at most max. Never enlarges.
export function fitSize(w, h, max) {
  const k = Math.min(1, max / Math.max(w, h));
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) };
}

// ---------- units on the picker ----------

// units: food.units, [{unit, step, default_amount, ...}]. default_amount is one label serving in that unit.
function unitOf(units, name) { return (units || []).find((u) => u.unit === name) || null; }

// Starting unit and amount. A usable preset (quick item, edit, last used) wins, else the package's own serving: def is
// food.default from GET /api/foods/{id} ({amount, unit}, for example 30 g, 1 cup or 2 slice), else the label unit and amount.
// It is never "1 serving" unless the package gives nothing else. serving stays in the unit list.
// A typed unit (pinch, can) that no choice has comes back as unit '' (the Custom choice) with the word.
export function initialPick(units, preset, def) {
  const own = units[0];
  const u = (preset && unitOf(units, preset.unit)) || own;
  const ok = preset && preset.unit === u.unit && Number(preset.amount) > 0;
  if (ok) return { unit: u.unit, amount: Number(preset.amount) };
  const word = preset && preset.unit ? cleanUnitText(preset.unit) : '';
  const custom = word && Number(preset.amount) > 0 && unitOf(units, '');
  if (custom) return { unit: '', amount: Number(preset.amount), word };
  const d = def && unitOf(units, def.unit);
  if (d && Number(def.amount) > 0) return { unit: d.unit, amount: Number(def.amount) };
  return { unit: u.unit, amount: u.default_amount };
}

// Which amount and unit a picker starts from. An edit always keeps its own. For a new log, "use last" off means
// the label serving (null), otherwise the amount a quick item carries, else the food's last entry.
export function startPreset(edit, params, food, useLast) {
  if (edit) return params;
  if (useLast === false) return null;
  return params && params.unit ? params : food && food.last;
}

function niceRound(n) { return roundTo(n, Math.abs(n) >= 10 ? 1 : 3); }

// Same quantity in another unit. Falls back to the new unit's default amount when it cannot be worked out.
export function convertAmount(units, amount, from, to) {
  const a = unitOf(units, from);
  const b = unitOf(units, to);
  if (!b) return null;
  if (!a || !(a.default_amount > 0) || !(Number(amount) > 0)) return b.default_amount;
  return niceRound((Number(amount) / a.default_amount) * b.default_amount) || b.default_amount;
}

// The amount in grams, or null when the food has no gram unit.
export function gramsFor(units, amount, unit) {
  const g = unitOf(units, 'g');
  if (!g || unit === 'g') return null;
  const n = convertAmount(units, amount, unit, 'g');
  return n > 0 ? n : null;
}

// ---------- Match Ingredients: amount from the recipe line ----------

const MASS_UNITS = ['g', 'kg', 'oz', 'lb'];
const VOLUME_UNITS = ['ml', 'l', 'floz', 'cup', 'tbsp', 'tsp'];
// Line units that only say "this many of the thing", like a count without a unit ("2 eggs").
const PLAIN_COUNTS = ['count', 'piece', 'each', 'whole', 'unit', 'item', 'large', 'medium', 'small'];

// Amount and unit for a recipe line matched to a food without the picker. Mirrors units.match_amount on the server.
// units: food.units from GET /api/foods/{id} (first entry is the label unit, estimated marks a 1 g per ml guess).
// Returns { amount, unit, check } (plus estimated: true when only the 1 g per ml guess reaches the unit) or null when the line
// has no amount (salt to taste).
// - The line's own unit when the food reaches it at all, as the picker offers it (an estimated one is flagged estimated): same unit, weight to weight (g, oz, lb, kg),
//   volume to volume (ml, l, tsp, tbsp, cup, fl oz), and between the two through the food's own density or the 1 g per ml guess.
// - A plain count (no unit, piece, each) uses the label's count word when it has one ("2 eggs" -> 2 egg), else servings.
// - A typed unit that is not a known measure (can, clove, pinch) keeps its word, counts like count, and needs no check.
// - A known measure the food cannot reach: one label serving with check true, so the row asks the user to confirm.
export function matchAmount(units, amount, unit) {
  const a = typeof amount === 'number' ? amount : parseAmount(amount);
  if (a == null || !(a > 0) || !units || !units.length) return null;
  const label = units[0];
  const typed = cleanUnitText(unit);
  const u = canonUnit(typed);
  // A typed unit no measure knows (can, clove, pinch) keeps its word and counts like count: no conversion, no Check Amount.
  if (u && PLAIN_COUNTS.indexOf(u) < 0 && KNOWN_UNITS.indexOf(u) < 0 && label.unit !== u) return { amount: a, unit: typed, check: false };
  if (u && PLAIN_COUNTS.indexOf(u) < 0) {
    const hit = units.find((x) => x.unit === u);
    return hit ? { amount: a, unit: u, check: false, ...(hit.estimated ? { estimated: true } : {}) } : { amount: label.default_amount, unit: label.unit, check: true };
  }
  const count = MASS_UNITS.indexOf(label.unit) < 0 && VOLUME_UNITS.indexOf(label.unit) < 0 && label.unit !== SERVING && label.unit !== PCT;
  return { amount: a, unit: count ? label.unit : SERVING, check: false };
}

// "1 cup, 125 g": the matched amount, plus grams when the server knows them and the unit is not grams already.
export function matchedAmountText(amount, unit, grams) {
  const g = Number(grams);
  return amountText(amount, unit) + (grams != null && g > 0 && unit !== 'g' ? ', ' + fmtNum(g, g >= 10 ? 0 : 1) + ' g' : '');
}

// ---------- calorie split chart ----------

export const KCAL_PER_G = { carbs: 4, protein: 4, fat: 9 };
export const MACRO_KEYS = ['carbs', 'protein', 'fat'];

// Share of calories from each macro, as fractions that add to 1. null when there is nothing.
export function macroShares(g) {
  const kc = MACRO_KEYS.map((k) => Math.max(0, Number(g && g[k]) || 0) * KCAL_PER_G[k]);
  const sum = kc[0] + kc[1] + kc[2];
  if (!(sum > 0)) return null;
  return { carbs: kc[0] / sum, protein: kc[1] / sum, fat: kc[2] / sum };
}

// Whole percents that add to exactly 100 (largest remainder).
export function percentParts(shares) {
  if (!shares) return { carbs: 0, protein: 0, fat: 0 };
  const raw = MACRO_KEYS.map((k) => shares[k] * 100);
  const out = raw.map(Math.floor);
  let left = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw.map((v, i) => [v - out[i], i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]);
  for (let i = 0; left > 0 && i < order.length; i++, left--) out[order[i][1]]++;
  return { carbs: out[0], protein: out[1], fat: out[2] };
}

// Whole percents of calories from carbs, protein and fat (sum 100), or null when all three are zero.
export function macroBarParts(g) {
  const shares = macroShares(g);
  return shares ? percentParts(shares) : null;
}

export function macroBarLabel(parts) {
  return 'Carbs ' + parts.carbs + '%, Protein ' + parts.protein + '%, Fat ' + parts.fat + '%';
}

export function polar(cx, cy, r, angle) {
  return { x: roundTo(cx + r * Math.cos(angle), 3), y: roundTo(cy + r * Math.sin(angle), 3) };
}

// SVG path for a ring segment between two angles (radians, clockwise from the +x axis).
export function arcPath(cx, cy, rOuter, rInner, a0, a1) {
  const sweep = clamp(a1 - a0, 0, 2 * Math.PI - 1e-4);
  const end = a0 + sweep;
  const large = sweep > Math.PI ? 1 : 0;
  const o0 = polar(cx, cy, rOuter, a0);
  const o1 = polar(cx, cy, rOuter, end);
  const i1 = polar(cx, cy, rInner, end);
  const i0 = polar(cx, cy, rInner, a0);
  return 'M' + o0.x + ' ' + o0.y + 'A' + rOuter + ' ' + rOuter + ' 0 ' + large + ' 1 ' + o1.x + ' ' + o1.y +
    'L' + i1.x + ' ' + i1.y + 'A' + rInner + ' ' + rInner + ' 0 ' + large + ' 0 ' + i0.x + ' ' + i0.y + 'Z';
}

// Segments starting at the top, going clockwise. Zero shares are dropped.
export function donutSegments(shares) {
  if (!shares) return [];
  let a = -Math.PI / 2;
  const out = [];
  for (const key of MACRO_KEYS) {
    const span = shares[key] * 2 * Math.PI;
    if (span > 0) out.push({ key, start: a, end: a + span });
    a += span;
  }
  return out;
}

// ---------- screens ----------

// Counter for async screens. Only the most recent ticket may touch the page.
export function latestGuard() {
  let n = 0;
  return { next: () => ++n, isLatest: (t) => t === n };
}

// ---------- Claude cost notice ----------

// "0.45 cents", "1 cent", "12 cents", "$1.20". For one request.
export function centsText(usd) {
  if (!Number.isFinite(usd) || usd < 0) return '';
  const cents = usd * 100;
  if (cents >= 100) return '$' + roundTo(usd, 2).toFixed(2);
  const n = cents >= 10 ? roundTo(cents, 0) : roundTo(cents, cents >= 1 ? 1 : 2);
  return fmtNum(n, 2) + (n === 1 ? ' cent' : ' cents');
}

// "$0.12", or "under $0.01" for a tiny positive total. For a month.
export function dollarText(usd) {
  if (!Number.isFinite(usd) || usd < 0) return '';
  if (usd > 0 && usd < 0.005) return 'under $0.01';
  return '$' + roundTo(usd, 2).toFixed(2);
}

export const LOW_REQUESTS = 5;

// Lines for the notice shown before a Claude request. st is the /api/ai/status reply. what is e.g. "1 photo of a label".
// blocked: nothing can be sent. Cost reads "Cost not available" when the server has no price.
// requests: how many requests the action may use (Refresh Nutrients with Full Claude Use sends one per food), 1 by default.
export function noticeLines(st, what, requests) {
  const blocked = st.remaining <= 0;
  if (blocked) return { blocked, lines: ['You have used all ' + st.cap + ' requests this month. Nothing can be sent.'], warn: '' };
  const lines = ['Sends ' + what + ' to Claude.'];
  const n = requests > 1 ? requests : 1;
  lines.push((n > 1 ? 'Uses up to ' + n : 'Uses 1') + ' of your ' + st.cap + ' monthly requests (' + st.remaining + ' left).');
  lines.push(st.est_cost_label == null ? 'Cost not available.' : 'Estimated cost about ' + centsText(st.est_cost_label) + '.');
  const warn = st.remaining <= LOW_REQUESTS ? 'Only ' + st.remaining + ' left this month.' : '';
  return { blocked, lines, warn };
}

export function photosText(n) { return n + (n === 1 ? ' photo' : ' photos') + ' of a label'; }

// ---------- search source on Add ----------

// The Source choice above the Add search. all = Open Food Facts and USDA (never Claude), ai = one Claude estimate on Search.
export const SEARCH_SOURCES = [
  { value: 'all', label: 'All Sources' }, { value: 'off', label: 'Open Food Facts' },
  { value: 'fdc', label: 'USDA' }, { value: 'ai', label: 'Claude' },
];
export function searchSource(v) { return SEARCH_SOURCES.some((s) => s.value === v) ? v : 'all'; }

// Settings, Display, Auto-Match After Import: what happens on Match Ingredients right after an import. Search (default) is the free
// name search. Claude matches the unmatched rows with Claude. Search Then Claude searches first, then asks Claude only about the rows
// Search left without a proposal. Off does nothing. Same values as core.AUTO_MATCHES.
export const AUTO_MATCHES = [{ value: 'search', label: 'Search' }, { value: 'claude', label: 'Claude' },
  { value: 'search_claude', label: 'Search Then Claude' }, { value: 'off', label: 'Off' }];
export const autoMatch = (v) => (AUTO_MATCHES.some((o) => o.value === v) ? v : 'search');
export const MAX_AI_TEXT = 200;  // same as ai.MAX_TEXT on the server

// What one search does. remote is true for Enter or the Search button, false while typing.
// Returns { kind } where kind is tabs (empty box), barcode (typed digits), search (database search, with source),
// wait (Claude waits for Search), off (Claude is not set up), long (too long for Claude) or claude.
export function searchAction(source, text, remote, aiEnabled) {
  const t = String(text == null ? '' : text).trim();
  if (!t) return { kind: 'tabs' };
  if (/^\d{8,14}$/.test(digitsOnly(t)) && /^[\d\s-]+$/.test(t)) return { kind: 'barcode', code: digitsOnly(t) };
  const src = searchSource(source);
  if (src !== 'ai') return { kind: 'search', source: src, remote: !!remote };
  if (aiEnabled === false) return { kind: 'off' };
  if (!remote) return { kind: 'wait' };
  if (t.length > MAX_AI_TEXT) return { kind: 'long' };
  return { kind: 'claude', text: t };
}

// Message for a search source with nothing (yet) to show.
export function searchHint(source, kind) {
  const src = searchSource(source);
  if (kind === 'wait') return 'Press Search to ask Claude for an estimate. Each search uses 1 Claude request.';
  if (kind === 'off') return 'Claude is not set up for you. Add your own Claude key in Settings, or ask the administrator.';
  if (kind === 'long') return 'Keep the description to ' + MAX_AI_TEXT + ' characters or fewer.';
  if (kind === 'none') return 'No results.';
  const where = src === 'all' ? 'Open Food Facts and USDA' : sourceLabel(src);
  return 'Press Search to check ' + where + '.';
}

export const DESCRIPTION_TEXT = 'your food description';

// Whether a Claude feature can be used: a key is in use and the administrator allows it. st: /api/ai/status, name: label, lookup or recipe.
export function aiFeature(st, name) {
  return !!(st && st.enabled && !(st.features && st.features[name] === false));
}
// Whether the administrator turned a Claude feature off (as opposed to Claude not being set up).
export function aiFeatureOff(st, name) { return !!(st && st.features && st.features[name] === false); }

// The Source choices on Add. Claude is left out when the administrator turned typed search off.
export function searchSources(st) { return aiFeatureOff(st, 'lookup') ? SEARCH_SOURCES.filter((s) => s.value !== 'ai') : SEARCH_SOURCES; }

// The Source Add starts with: the choice made this visit, else the Default Search Source setting, else All Sources.
// Claude falls back to All Sources when typed search is turned off.
export function startSource(session, preferred, st) {
  const v = searchSource(session != null ? session : preferred);
  return v === 'ai' && aiFeatureOff(st, 'lookup') ? 'all' : v;
}

// ---------- micronutrients and display settings ----------

// Same order and units as the server. kind: 'goal' (aim to reach) or 'limit' (stay under).
export const MICROS = [
  { key: 'fiber', label: 'Fiber', unit: 'g', kind: 'goal' },
  { key: 'sugars', label: 'Sugars', unit: 'g', kind: 'limit' },
  { key: 'saturated_fat', label: 'Saturated Fat', unit: 'g', kind: 'limit' },
  { key: 'sodium', label: 'Sodium', unit: 'mg', kind: 'limit' },
  { key: 'cholesterol', label: 'Cholesterol', unit: 'mg', kind: 'limit' },
  { key: 'potassium', label: 'Potassium', unit: 'mg', kind: 'goal' },
  { key: 'calcium', label: 'Calcium', unit: 'mg', kind: 'goal' },
  { key: 'iron', label: 'Iron', unit: 'mg', kind: 'goal' },
  { key: 'vitamin_d', label: 'Vitamin D', unit: 'mcg', kind: 'goal' },
];

// What the screens show before /api/settings/display answers. Matches the server defaults.
export const DEFAULT_DISPLAY = { show_macros: true, show_micros: true, show_split: true, show_macro_bar: true, show_table: true, group_recipes: true,
  micros_open: false, micros_shown: MICROS.map((m) => m.key), today_view: 'list', auto_match: 'search', recipe_owner: 'mine' };

// The nutrients to list, in order. Empty when the section is switched off.
export function shownMicros(display) {
  const d = display || DEFAULT_DISPLAY;
  if (d.show_micros === false) return [];
  const keep = Array.isArray(d.micros_shown) ? d.micros_shown : DEFAULT_DISPLAY.micros_shown;
  return MICROS.filter((m) => keep.includes(m.key));
}

// A nutrient amount: mg as whole numbers, g and mcg with one decimal. Unknown (null) is a dash, never 0.
export function microValue(v, unit) {
  if (v == null || !Number.isFinite(Number(v))) return '-';
  return fmtNum(Number(v), unit === 'mg' ? 0 : 1);
}

// "12.5 / 28 g" on Today. A day with entries but no data for this nutrient reads "- / 28 g".
export function microText(m, unit) {
  const total = m.total == null && !m.count ? 0 : m.total;
  return microValue(total, unit) + ' / ' + fmtNum(Number(m.target), unit === 'mg' ? 0 : 1) + ' ' + unit;
}

// "2 of 3 foods" when some logged foods have no data for the nutrient, else ''.
export function microNote(m) {
  return m.count > 0 && m.known < m.count ? m.known + ' of ' + m.count + (m.count === 1 ? ' food' : ' foods') : '';
}

// A limit that is passed gets the warning color. Reaching a goal never does.
export function microOver(m) { return m.kind === 'limit' && m.total != null && Number(m.total) > Number(m.target); }

// Toggle one nutrient in the shown list, keeping the fixed order.
export function toggleMicro(shown, key) {
  const set = new Set(shown || []);
  if (set.has(key)) set.delete(key); else set.add(key);
  return MICROS.map((m) => m.key).filter((k) => set.has(k));
}

// ---------- Saved screen search and meal filter ----------

export const SAVED_FILTERS = [...MEAL_FILTERS, 'untagged'];
export const SAVED_FILTER_LABELS = { ...MEAL_FILTER_LABELS, untagged: 'Untagged' };

// True when every word of the query appears in the text, ignoring case. An empty query matches everything.
export function matchesQuery(text, query) {
  const hay = String(text == null ? '' : text).toLowerCase();
  return String(query == null ? '' : query).toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
}

// Saved items (favorites or recipes carry meals, the tag list) by name and meal tag. text(item) gives the searchable text.
// meal: all keeps everything, a meal keeps items tagged with it, untagged keeps items with no tag. Strict: unlike Add,
// an untagged item does not match a meal here, because this screen is where tags are managed.
export function filterSavedItems(items, query, meal, text) {
  return (items || []).filter((it) => {
    if (!matchesQuery(text(it), query)) return false;
    const tags = it.meals || [];
    if (meal === 'untagged') return tags.length === 0;
    return !MEALS.includes(meal) || tags.includes(meal);
  });
}

// ---------- Recipes tab owner filter (shared recipes) ----------

// Mine (the default) is my own recipes, Shared With Me is recipes other users share, All is both. Saved as the Display
// setting recipe_owner. A recipe from the server carries mine (bool), shared (bool) and owner {id, name}.
export const RECIPE_OWNERS = ['mine', 'shared', 'all'];
export const RECIPE_OWNER_LABELS = { mine: 'Mine', shared: 'Shared With Me', all: 'All' };
export const recipeOwner = (v) => (RECIPE_OWNERS.includes(v) ? v : 'mine');
const isMine = (rec) => !rec || rec.mine !== false;

export function filterRecipeOwner(items, owner) {
  const o = recipeOwner(owner);
  return (items || []).filter((rec) => o === 'all' || (o === 'mine') === isMine(rec));
}

// The owner line of a recipe: "Shared by Ann" for someone else's, "Shared" for my own shared one, '' for my private one.
export function ownerText(rec) {
  if (!isMine(rec)) return 'Shared by ' + ((rec.owner && String(rec.owner.name || '').trim()) || 'another user');
  return rec && rec.shared ? 'Shared' : '';
}

// The empty list text for an owner filter with no recipes at all (before search and meal filters).
export function ownerEmptyText(owner) {
  return recipeOwner(owner) === 'shared' ? sentence('No one has shared a recipe with you yet')
    : sentence('No recipes yet. Tap New Recipe or Import Recipe, or tap Save As Recipe under a meal on Today');
}

// ---------- Recipes tab sort ----------

export const RECIPE_SORTS = ['name', 'newest', 'used'];
export const RECIPE_SORT_LABELS = { name: 'Name (A to Z)', newest: 'Newest', used: 'Most Used' };

// How many times a recipe was logged, from its per meal counts.
export const recipeUses = (rec) => Object.values((rec && rec.counts) || {}).reduce((a, n) => a + (Number(n) || 0), 0);

// A sorted copy. name is A to Z ignoring case, newest is the highest id first (ids only grow), used is the most logged first.
// Ties fall back to name, then id, so the order is stable.
export function sortRecipes(items, sort) {
  const byName = (a, b) => String(a.name).localeCompare(String(b.name), undefined, { sensitivity: 'base' }) || a.id - b.id;
  const by = { newest: (a, b) => b.id - a.id || byName(a, b), used: (a, b) => recipeUses(b) - recipeUses(a) || byName(a, b) };
  return (items || []).slice().sort(by[sort] || byName);
}

// ---------- Recipes tab grouping by meal ----------

// Recipes under a heading per meal tag, in the usual meal order, with Untagged last. A recipe with several tags is in each
// of its groups. The order inside a group is the order given (sort first). meal limits the groups to that meal or to
// untagged; all keeps every group. Empty groups are left out. Returns [{meal, label, items}] (meal null is Untagged).
export function groupRecipesByMeal(recipes, meal = 'all') {
  const rows = [];
  for (const r of recipes || []) {
    const tags = MEALS.filter((m) => (r.meals || []).includes(m));
    if (tags.length) tags.forEach((m) => rows.push({ meal: m, rec: r })); else rows.push({ meal: null, rec: r });
  }
  return groupByMeal(rows, 'Untagged')
    .filter((g) => meal === 'untagged' ? g.meal === null : !MEALS.includes(meal) || g.meal === meal)
    .map((g) => ({ meal: g.meal, label: g.label, items: g.entries.map((e) => e.rec) }));
}

// The first `shown` recipes across the groups (a recipe in two groups counts twice). Returns {groups, more} with more the rows left.
export function pageGroups(groups, shown) {
  let left = shown;
  const out = [];
  let total = 0;
  for (const g of groups) {
    total += g.items.length;
    if (left > 0) { out.push({ ...g, items: g.items.slice(0, left) }); left -= Math.min(left, g.items.length); }
  }
  return { groups: out, more: Math.max(0, total - shown) };
}

// ---------- Create Recipe draft ----------

export const newRecipeDraft = (depth) => ({ name: '', meals: [], rows: [], steps: [], depth, adding: false, picking: null });

// Draft rows are {food_id, name, brand, amount (number), unit}. These return new arrays.
export const recipeAddRow = (rows, food, amount, unit) => [...rows, { food_id: food.id, name: food.name, brand: food.brand || null, amount, unit }];
export const recipeSetRow = (rows, i, amount, unit) => rows.map((r, k) => (k === i ? { ...r, amount, unit } : r));
export const recipeRemoveRow = (rows, i) => rows.filter((_, k) => k !== i);

// The POST /api/meals body for a draft, or {error}.
export function recipeBody(draft) {
  const name = String(draft.name || '').trim();
  if (!name) return { error: 'Enter a recipe name.' };
  if (!draft.rows.length) return { error: 'Add at least one ingredient.' };
  const st = stepsCheck(draft.steps);
  if (st.error) return st;
  return { body: { name, meals: MEALS.filter((m) => (draft.meals || []).includes(m)),
    items: draft.rows.map((r) => ({ food_id: r.food_id, amount: r.amount, unit: r.unit })), steps: st.steps } };
}

// ---------- recipe steps (the method) ----------

export const MAX_STEPS = 60;  // same as core.MAX_STEPS
export const MAX_STEP_LEN = 1000;  // same as core.MAX_STEP_LEN

// A copy of list with item i moved by dir (-1 up, +1 down). Out of range moves change nothing.
export function moveItem(list, i, dir) {
  const out = (list || []).slice();
  const j = i + dir;
  if (i < 0 || i >= out.length || j < 0 || j >= out.length) return out;
  const t = out[i];
  out[i] = out[j];
  out[j] = t;
  return out;
}

// Steps as the server stores them: whitespace folded, blank steps dropped. Returns { steps } or { error }.
export function stepsCheck(list) {
  const steps = (list || []).map((x) => String(x == null ? '' : x).replace(/\s+/g, ' ').trim()).filter(Boolean);
  if (steps.length > MAX_STEPS) return { error: 'A recipe can have at most ' + MAX_STEPS + ' steps.' };
  const long = steps.findIndex((x) => x.length > MAX_STEP_LEN);
  if (long >= 0) return { error: 'Step ' + (long + 1) + ' is too long. Keep each step to ' + MAX_STEP_LEN + ' characters.' };
  return { steps };
}

// History steps from the current screen back to the recipe screen, at least one.
export const stepsBack = (depth, base) => Math.max(1, depth - base);

// ---------- Today keeps its place ----------
// Removing an entry, changing a portion or coming back from a row's screen repaints Today. The repaint keeps the scroll position and
// puts focus on something sensible instead of the top of the page.

// A stable key for one Today row: a logged recipe is one row (its group), any other entry is itself.
export const entryKey = (e) => (e && e.kind === 'recipe' ? 'g' + e.group_id : 'e' + (e && e.id));

// What to remember before leaving or repainting Today. y: window scroll, key: the row acted on, index: where that row sits among
// the rows (in screen order), day: the date shown, so a hold never carries over to another day.
export const todayHold = (y, key, index, day) => ({ y: Math.max(0, Math.round(Number(y) || 0)), key: key == null ? null : String(key),
  index: Math.max(0, Math.floor(Number(index) || 0)), day: day || null });

// A hold applies once, to the same day only.
export const holdFresh = (hold, day) => !!hold && hold.day === day;

// Where focus goes after the repaint. keys: the row keys now on screen in order. The same row when it is still there (a portion
// change, a return from the row's screen), else the row that took its place (the next one, or the last when the removed row was
// the last), else the heading when no rows are left. page: no row was involved, focus stays on the page.
export function holdTarget(hold, keys) {
  const list = Array.isArray(keys) ? keys : [];
  if (hold && hold.key == null) return { kind: 'page', index: -1 };  // a repaint that acted on no row (Refresh Nutrients)
  if (!hold || !list.length) return { kind: 'heading', index: -1 };
  const same = list.indexOf(hold.key);
  return { kind: 'row', index: same >= 0 ? same : Math.min(hold.index, list.length - 1) };
}

// ---------- Cooking View (pure helpers) ----------

// Servings the recipe makes; a recipe without servings makes one.
export const cookBase = (meal) => (meal && meal.servings > 0 ? meal.servings : 1);

// The serving count moves in halves for small recipes and whole servings for larger ones, never below one step or above 1000.
export const cookStep = (base) => (base >= 4 ? 1 : 0.5);
export function cookServingsNext(shown, base, dir) {
  const step = cookStep(base);
  const next = Math.round((Number(shown) + dir * step) / step) * step;
  return Math.min(1000, Math.max(step, next));
}

// One ingredient as the recipe says it, scaled by factor: "3 cup flour, sifted". The imported wording wins over the matched
// food. A line with no amount keeps its text (it cannot scale). Rows made in the app use the food name and matched amount.
// Every row shows, matched or not, because it is still part of the dish. Returns { text, scaled }.
export function cookIngredient(it, factor = 1) {
  const src = it && it.src;
  const join = (amount, unit, name, note) => [qtyText(amount, unit), unit, name].filter((x) => x !== '' && x != null).join(' ') + (note ? ', ' + note : '');
  if (src && src.amount != null && Number(src.amount) > 0 && src.name) {
    return { text: join(Number(src.amount) * factor, src.unit || '', src.name, src.note), scaled: true };
  }
  if (src && (src.text || src.name)) return { text: src.text || src.name, scaled: false };
  const food = it && it.food;
  if (food && it.amount != null) return { text: join(Number(it.amount) * factor, it.unit === SERVING ? '' : it.unit, food.name, ''), scaled: true };
  return { text: (food && food.name) || 'Ingredient', scaled: false };
}

export function cookIngredients(meal, shown) {
  const factor = cookBase(meal) > 0 ? Number(shown) / cookBase(meal) : 1;
  return ((meal && meal.items) || []).map((it, i) => ({ key: 'i' + i, ...cookIngredient(it, factor) }));
}

// The steps to show, in order.
export const cookSteps = (meal) => ((meal && meal.steps) || []).map((text, i) => ({ key: 's' + i, text }));

// A new set with key ticked or unticked. The set passed in is never changed.
export function cookToggle(checked, key) {
  const next = new Set(checked);
  if (next.has(key)) next.delete(key); else next.add(key);
  return next;
}

// ---------- Full Claude Use (issue #26) ----------
// A per user setting (settings.full_claude, off by default). When on, Claude runs on its own where it helps, each step only
// when the administrator's switch and a usable key allow it, inside the monthly cap and its cost reservation.

export const CLAUDE_CAP_NOTE = sentence('Monthly Claude limit reached, so Claude was not used');

// Auto-Match After Import with Full Claude Use: Search (the default) becomes Search Then Claude. An explicit Claude, Search Then
// Claude or Off is never changed. forced: Full Claude Use made the change, so a missing Claude falls back to Search silently.
export function effectiveAutoMatch(setting, full) {
  const s = autoMatch(setting);
  return full && s === 'search' ? { value: 'search_claude', forced: true } : { value: s, forced: false };
}

// Whether an automatic Claude step runs. st: /api/ai/status, feature: label, lookup or recipe.
// off: Full Claude Use is off, the switch is off or there is no key (silent). cap: no requests left (one quiet note).
// confirm: ask first with the cost (Confirm before using Claude is on). run: go ahead quietly.
export function autoClaudePlan(settings, st, feature) {
  if (!settings || settings.full_claude !== true || !aiFeature(st, feature)) return 'off';
  if (!(st.remaining > 0)) return 'cap';
  return settings.confirm_ai === false ? 'run' : 'confirm';
}

// The Full Claude Use description: approximate cost per action and for a heavy month, from /api/ai/status action_costs
// (computed on the server from the real token sizes, with your prices, else the Haiku 5.5 sample prices).
export const FULL_CLAUDE_ACTIONS = [
  ['lookup', 'Claude lookup when a search finds nothing'], ['micros', 'Missing nutrients for one food'],
  ['label', 'Label photo'], ['recipe_text', 'Recipe import from text'], ['match', 'Claude match of 15 ingredients'],
];
export function fullClaudeRows(costs) {
  if (!costs) return [];
  const rows = FULL_CLAUDE_ACTIONS.filter(([k]) => Number.isFinite(costs[k])).map(([k, label]) => ({ label, text: 'about ' + centsText(costs[k]) }));
  if (Number.isFinite(costs.heavy_month)) {
    rows.push({ label: 'Heavy month (' + costs.heavy_requests + ' requests)', text: 'about ' + (costs.heavy_month < 0.01 ? centsText(costs.heavy_month) : dollarText(costs.heavy_month)) });
  }
  return rows;
}
export function fullClaudePriceNote(costs) {
  if (!costs) return sentence('Cost estimates are not available');
  return costs.sample
    ? sentence('Estimates at the Haiku 5.5 sample prices of 0.10 USD input and 0.50 USD output per million tokens, because no price is set')
    : sentence('Estimates at your model prices');
}

// The warning next to the Full Claude Use checkbox. st: /api/ai/status (cap = monthly request limit).
export function fullClaudeWarning(st) {
  const cap = st && Number.isFinite(st.cap) ? ' ' + sentence('Your monthly limit is ' + st.cap + ' Claude requests, and it still applies') : '';
  return sentence('Claude will be used on its own, and recipe imports and their matching run without asking, so costs add up') + cap;
}

// "Claude estimated sodium and iron." for a food whose blank micronutrients Claude filled, else ''.
export function aiMicrosText(food) {
  const keys = (food && Array.isArray(food.ai_micros) ? food.ai_micros : []);
  const names = MICROS.filter((m) => keys.includes(m.key)).map((m) => m.label.toLowerCase());
  if (!names.length) return '';
  const list = names.length === 1 ? names[0] : names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1];
  return 'Claude estimated ' + list + '. These are estimates.';
}

// What the Refresh Nutrients notice says is sent: the food facts, never anything else.
export function microsWhat(n) { return 'the name, serving and macros of ' + (n === 1 ? '1 food' : 'up to ' + n + ' foods') + ' to estimate missing nutrients'; }

// Import Recipe with Full Claude Use: the line under Read With Claude, since the tap sends at once. st: /api/ai/status.
export function recipeTextCostLine(st) {
  const c = st && st.action_costs;
  const cost = c && Number.isFinite(c.recipe_text) ? 'Up to about ' + centsText(c.recipe_text) + ' per import' + (c.sample ? ' at sample prices' : '') + '. ' : '';
  const left = st && Number.isFinite(st.remaining) ? st.remaining + ' of ' + st.cap + ' Claude requests left this month.' : '';
  return ('Full Claude Use is on, so Read With Claude sends the text at once. ' + cost + left).trim();
}

// Full Claude Use on Add: a database search found nothing, so Claude estimated the typed text.
export const FALLBACK_TEXT = sentence('Nothing was found in the databases, so this is a Claude Estimate. Tap it to check the values and save it');
export const FALLBACK_FAILED = sentence('Claude could not estimate it just now');
