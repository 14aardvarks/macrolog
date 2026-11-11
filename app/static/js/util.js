// Pure helpers. No DOM access, safe to import from node.

export const MEALS = ['breakfast', 'lunch', 'dinner', 'snack'];
export const MEAL_LABELS = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack', none: 'No meal' };

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

// Fraction text for common amounts: 0.5 -> "1/2", 1.5 -> "1 1/2", 2 -> "2". null when it is not a tidy fraction.
export function fractionText(n) {
  if (!Number.isFinite(n) || n < 0) return null;
  const whole = Math.floor(n + 1e-9);
  const rest = n - whole;
  if (rest < 1e-6 || 1 - rest < 1e-6) return String(Math.round(n));
  for (const d of [2, 3, 4, 8]) {
    const k = Math.round(rest * d);
    if (k > 0 && k < d && Math.abs(rest - k / d) < 0.0015) {
      return (whole ? whole + ' ' : '') + k + '/' + d;  // smaller denominators come first, so this is already reduced
    }
  }
  return null;
}

// How serving amounts are shown: 'fraction' (1/4, 1 1/2) or 'decimal' (0.25, 1.5). Set from the user's setting.
// Other units always show decimals. Typing accepts both whatever this is.
let amountFormat = 'fraction';
export function setAmountFormat(f) { amountFormat = f === 'decimal' ? 'decimal' : 'fraction'; }
export function getAmountFormat() { return amountFormat; }

// A serving count as text in the chosen format (or the one passed in).
export function servingText(n, format = amountFormat) {
  return format === 'decimal' ? fmtAmount(n) : (fractionText(n) || fmtAmount(n));
}

// Short unit name for lists: "pct" shows as "% of serving".
export function unitLabel(unit) { return unit === PCT ? '% of serving' : unit; }

// "1/2 serving", "1 serving", "1 1/2 servings", "25% of a serving", "30 g", "2 slice".
export function amountText(amount, unit, format) {
  const n = Number(amount);
  if (unit === PCT) return fmtAmount(n) + '% of a serving';
  if (unit === SERVING) {
    return servingText(n, format) + (n > 1 ? ' servings' : ' serving');
  }
  return fmtAmount(n) + ' ' + unit;
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

// Row text on the amount wheel. Servings read as fractions ("1/4") or decimals ("0.25"), everything else as a plain number.
export function amountLabel(unit, v, format) {
  if (unit === SERVING) return servingText(v, format);
  return fmtAmount(v);
}

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

// Text for a recipe row's amount box: servings follow the fraction/decimal setting, everything else is a plain number.
export const rowAmountText = (amount, unit) => (unit === SERVING ? servingText(amount) : fmtAmount(amount));

// Rows of the recipe screen are kept as drafts {checked, amount (text), unit} while the picker is open.
// Returns a copy with row i set to the picked amount and unit and ticked. Other rows are untouched.
export function applyRowPick(draft, i, amount, unit) {
  return draft.map((r, k) => (k === i ? { ...r, checked: true, amount: rowAmountText(amount, unit), unit } : { ...r }));
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

// The tag set after tapping a meal chip, in breakfast to snack order.
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

// Text for an empty list. kind is favorites, yesterday or recipes. hasAny says the unfiltered list had items.
export function emptyText(kind, meal, hasAny) {
  const w = mealWord(meal);
  if (kind === 'yesterday') return w ? 'Nothing for ' + w + ' yesterday.' : 'Nothing from yesterday.';
  if (kind === 'recent') return 'No past foods yet. Foods you log show up here.';
  const one = kind === 'recipes' ? 'recipe' : 'favorite';
  if (w && hasAny) return 'No ' + kind + ' tagged ' + w + '. Choose All to see every ' + one + '.';
  if (kind === 'recipes') return 'No saved recipes. On Today, tap "Save As Recipe" under a meal.';
  return 'No favorites yet. Tap the star on a food to add one.';
}

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

// Starting unit and amount. A usable preset (quick item, edit, last used) wins, else the label unit and amount.
export function initialPick(units, preset) {
  const own = units[0];
  const u = (preset && unitOf(units, preset.unit)) || own;
  const ok = preset && preset.unit === u.unit && Number(preset.amount) > 0;
  return { unit: u.unit, amount: ok ? Number(preset.amount) : u.default_amount };
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
export function noticeLines(st, what) {
  const blocked = st.remaining <= 0;
  if (blocked) return { blocked, lines: ['You have used all ' + st.cap + ' requests this month. Nothing can be sent.'], warn: '' };
  const lines = ['Sends ' + what + ' to Claude.'];
  lines.push('Uses 1 of your ' + st.cap + ' monthly requests (' + st.remaining + ' left).');
  lines.push(st.est_cost_label == null ? 'Cost not available.' : 'Estimated cost about ' + centsText(st.est_cost_label) + '.');
  const warn = st.remaining <= LOW_REQUESTS ? 'Only ' + st.remaining + ' left this month.' : '';
  return { blocked, lines, warn };
}

export function photosText(n) { return n + (n === 1 ? ' photo' : ' photos') + ' of a label'; }

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
export const DEFAULT_DISPLAY = { show_macros: true, show_micros: true, show_split: true, show_macro_bar: true,
  micros_open: false, micros_shown: MICROS.map((m) => m.key) };

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

// ---------- Create Recipe draft ----------

export const newRecipeDraft = (depth) => ({ name: '', meals: [], rows: [], depth, adding: false, picking: null });

// Draft rows are {food_id, name, brand, amount (number), unit}. These return new arrays.
export const recipeAddRow = (rows, food, amount, unit) => [...rows, { food_id: food.id, name: food.name, brand: food.brand || null, amount, unit }];
export const recipeSetRow = (rows, i, amount, unit) => rows.map((r, k) => (k === i ? { ...r, amount, unit } : r));
export const recipeRemoveRow = (rows, i) => rows.filter((_, k) => k !== i);

// The POST /api/meals body for a draft, or {error}.
export function recipeBody(draft) {
  const name = String(draft.name || '').trim();
  if (!name) return { error: 'Enter a recipe name.' };
  if (!draft.rows.length) return { error: 'Add at least one ingredient.' };
  return { body: { name, meals: MEALS.filter((m) => (draft.meals || []).includes(m)),
    items: draft.rows.map((r) => ({ food_id: r.food_id, amount: r.amount, unit: r.unit })) } };
}

// History steps from the current screen back to the recipe screen, at least one.
export const stepsBack = (depth, base) => Math.max(1, depth - base);
