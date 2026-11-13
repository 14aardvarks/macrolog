// Pure helpers for Import Recipe and Match Ingredients. No DOM access, safe to import from node.
import { cleanUnitText, plural, parseAmount, amountBoxValue, fmtAmount, qtyText, servingText, amountText, roundTo, matchedAmountText, sentence, stepsCheck, MEALS, MEAL_LABELS, MICROS, autoMatch } from './util.js';

// Unit words found at the start of an ingredient line, mapped to the server's canonical units or a count word.
const UNIT_WORDS = {
  cup: 'cup', cups: 'cup', c: 'cup',
  tablespoon: 'tbsp', tablespoons: 'tbsp', tbsp: 'tbsp', tbs: 'tbsp', tbl: 'tbsp', T: 'tbsp',
  teaspoon: 'tsp', teaspoons: 'tsp', tsp: 'tsp', t: 'tsp',
  g: 'g', gram: 'g', grams: 'g', gr: 'g', kg: 'kg', kilogram: 'kg', kilograms: 'kg',
  oz: 'oz', ounce: 'oz', ounces: 'oz', lb: 'lb', lbs: 'lb', pound: 'lb', pounds: 'lb',
  ml: 'ml', milliliter: 'ml', milliliters: 'ml', millilitre: 'ml', millilitres: 'ml',
  l: 'l', liter: 'l', liters: 'l', litre: 'l', litres: 'l',
  count: 'count', counts: 'count', clove: 'clove', cloves: 'clove', can: 'can', cans: 'can', slice: 'slice', slices: 'slice',
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
    name: r.name || '', servings: r.servings == null ? '' : fmtAmount(r.servings), servingsExact: r.servings == null ? null : r.servings, servingsShown: r.servings == null ? '' : fmtAmount(r.servings), meals: [], warnings: [], cost: null,
    rows: (r.ingredients || []).map((i) => {
      const amount = i.amount == null ? '' : qtyText(i.amount, i.unit);
      return { amount, shown: amount, exact: i.amount == null ? null : i.amount, unit: i.unit || '', name: i.name || '', note: i.note || '', text: i.text || '' };
    }),
    steps: (r.steps || []).filter((x) => typeof x === 'string'),
    ...(extra || {}),
  };
}

// The unit choices of a review row: count first, then the measures, then Custom (made by dom.js unitControl) for any word of the
// recipe's own (clove, pinch) or the user's. Blank is Custom left empty, so nothing is guessed or lost.
export const IMPORT_UNITS = [['count', 'count'], ['g', 'g'], ['kg', 'kg'], ['oz', 'oz'], ['lb', 'lb'], ['ml', 'ml'], ['l', 'l'],
  ['floz', 'fl oz'], ['cup', 'cup'], ['tbsp', 'tbsp'], ['tsp', 'tsp']];
export function importUnitOptions() {
  return IMPORT_UNITS.map(([value, label]) => ({ value, label }));
}

export const blankRow = () => ({ amount: '', unit: '', name: '', note: '', text: '' });

// A row's amount: the exact number it was filled from while the box text is untouched (shown is the text the box was built with),
// else what was typed.
function rowAmount(row) { return amountBoxValue(row.amount, row.shown, row.exact); }

// The line as shown and stored. An edited row is rebuilt from its parts, so the stored text never disagrees with them.
export function rowText(row) {
  const a = rowAmount(row);
  const unit = cleanUnitText(row.unit);
  const head = [a == null ? '' : qtyText(a, row.unit), unit === 'floz' ? 'fl oz' : unit, String(row.name || '').trim()].filter(Boolean).join(' ');
  return head + (String(row.note || '').trim() ? ', ' + row.note.trim() : '');
}

// Validate the review draft and build the POST /api/meals/import body. Returns { error } or { body }.
export function reviewBody(draft) {
  const name = String(draft.name || '').trim();
  if (!name) return { error: 'Give the recipe a name.' };
  let servings = null;
  if (String(draft.servings || '').trim()) {
    servings = amountBoxValue(draft.servings, draft.servingsShown, draft.servingsExact);
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
    const amount = raw ? rowAmount(r) : null;
    if (raw && amount == null) return { error: 'Check the amount of ' + nm + '.' };
    const unit = cleanUnitText(r.unit) || null;
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

// What a recipe row on Add, Saved or the Recipes tab says under its name. A partial recipe keeps its "3 of 8 matched" badge.
export function recipeSubText(meal, kcalText) {
  if (!meal.complete) return matchCountText(meal);
  const n = meal.needed != null ? meal.needed : meal.items.length;
  return plural(n, 'item') + ' - ' + kcalText + ' kcal';
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

// Match Selected works by Search (the default: no Claude, no credit) or by Claude. Rows per request, as the server allows.
export const MATCH_METHODS = [['search', 'Search'], ['claude', 'Claude']];
export const MATCH_MAX = { search: 40, claude: 15 };  // same as recipe_ai.SEARCH_MAX_ROWS and ai.RECIPE_MATCH_MAX

// The method to use: Claude only when it is on for this user, else Search.
export const matchMethod = (want, aiOn) => (want === 'claude' && aiOn ? 'claude' : 'search');

export const matchRunText = (method) => 'Match Selected With ' + (method === 'claude' ? 'Claude' : 'Search');

// The rows to send now and the ones left ticked for the next tap.
export const methodBatch = (method, ids) => matchBatch(ids, MATCH_MAX[method === 'claude' ? 'claude' : 'search']);

// The note after a run: how many rows are still ticked, and how many Search found nothing for.
export function matchDoneText(method, proposals, restCount, costText) {
  const none = (proposals || []).filter((p) => !p.food).length;
  const found = (proposals || []).length - none;
  const lead = method === 'search' && !found ? 'No suggestions were found.' : 'Check the suggestions, then accept them all or one by one.';
  return lead + (method === 'search' && found && none ? ' ' + none + (none === 1 ? ' ingredient had' : ' ingredients had') + ' no match.' : '')
    + (costText ? ' ' + costText : '')
    + (restCount ? ' ' + restCount + ' more are still ticked. Tap ' + matchRunText(method) + ' again for them.' : '');
}

// The heading of a waiting proposal: Search suggestions say so, so nobody mistakes them for a Claude answer.
export const proposalHead = (p) => (p && p.method === 'search' ? (p.food ? 'Suggested Match' : 'Search Result') : 'Claude Suggests');

// ---------- Auto-Match After Import ----------
// Right after Save and Continue the page runs the free Search once on the unmatched rows (never Claude), so proposals are waiting.

export const AUTO_MATCH_LOADING = 'Finding Matches...';
export const AUTO_MATCH_FAILED = sentence('Suggestions could not be found just now. Match Selected With Search tries again');
export const RATE_LIMIT_NOTE = sentence('USDA lookup limit reached. Rows below were not searched');

export const AUTO_CLAUDE_OFF = sentence('Claude is not available, so Search ran instead');
export const AUTO_CLAUDE_FAILED = sentence('Claude could not match the rest just now. Match Selected With Claude tries again');
export const AUTO_CLAUDE_CANCELLED = sentence('Claude was not asked. Match Selected With Claude runs it later');

// Auto-Match runs for every setting except Off.
export const autoMatchOn = (display) => autoMatch(display && display.auto_match) !== 'off';

// What the setting does right now. aiOn: Claude is set up for this user and the recipe switch is on. A Claude setting without Claude
// falls back to Search with a short note. { search: run Search, claude: then ask Claude for the rows without a proposal, note }.
export function autoMatchPlan(setting, aiOn) {
  const s = autoMatch(setting);
  if (s === 'off') return { search: false, claude: false, note: '' };
  const wantsClaude = s !== 'search';
  const claude = wantsClaude && !!aiOn;
  return { search: s !== 'claude' || !claude, claude, note: wantsClaude && !claude ? AUTO_CLAUDE_OFF : '' };
}

// The rows to search: every unmatched row, up to the Search cap (rows beyond it stay ticked for a manual Match Selected).
export const autoMatchIds = (items) => methodBatch('search', unmatchedIds(items)).send;

// The rows to ask Claude about: unmatched rows with no proposal (nothing waiting, or a Search Result with no food), up to the Claude
// cap. send: ask now, rest: stay ticked for a manual Match Selected With Claude.
export const autoClaudeBatch = (items, proposals) =>
  methodBatch('claude', unmatchedIds(items).filter((id) => !(proposals && proposals[id] && proposals[id].food)));

// What to do with the answer. Rows that were matched or skipped while it ran are left alone. found: rows that got a food (these
// are un-ticked); the rest stay ticked. fresh: the proposals to keep waiting.
export function autoMatchResult(items, proposals) {
  const open = new Set(unmatchedIds(items));
  const fresh = (proposals || []).filter((p) => open.has(p.item_id));
  return { fresh, found: fresh.filter((p) => p.food).map((p) => p.item_id) };
}

// The quiet note when the shared USDA rate limit skipped rows, else ''.
export const rateLimitNote = (r) => (r && (r.rate_limited || (r.proposals || []).some((p) => p.skipped)) ? RATE_LIMIT_NOTE : '');

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

// The part of a row that Match Ingredients can change, with its imported line so a removed row can be put back.
const rowState = (it) => ({ id: it.id, food_id: it.food_id == null ? null : it.food_id, amount: it.food_id == null ? null : it.amount,
  unit: it.food_id == null ? null : it.unit, skipped: !!it.skipped, check: !!it.check, src: it.src ? { ...it.src } : null });
const sameYield = (a, b) => (!a && !b) || (!!a && !!b && a.amount === b.amount && a.unit === b.unit);

// What the recipe looked like at the last save (opening the screen, or Next). Back writes this back.
export function matchSnapshot(meal) {
  return { items: (meal.items || []).map(rowState), servings: meal.servings, yield: meal.yield ? { ...meal.yield } : null };
}

const sameRow = (a, b) => a.food_id === b.food_id && a.amount === b.amount && a.unit === b.unit && a.skipped === b.skipped && a.check === b.check;

// The POST /api/meals/{id}/items body that puts a removed row back at its place.
const addBody = (b, position) => {
  const out = { position };
  if (b.src) out.src = { ...b.src };
  if (b.food_id != null) { out.food_id = b.food_id; out.amount = b.amount; out.unit = b.unit; if (b.check) out.check = true; }
  if (b.skipped) out.skipped = true;
  return out;
};

// What Back has to write to undo every change since the snapshot: { remove: [row ids added since], add: [bodies of rows
// removed since, in list order, each with its place], items: [bulk rows], meal: PATCH body or null }. Remove first, then add,
// then items. Nothing to undo gives empty lists and a null meal.
export function restoreBody(base, meal) {
  const now = {};
  (meal.items || []).forEach((it) => { now[it.id] = rowState(it); });
  const had = {};
  base.items.forEach((b) => { had[b.id] = true; });
  const remove = (meal.items || []).filter((it) => !had[it.id]).map((it) => it.id);
  const add = [];
  base.items.forEach((b, i) => { if (!now[b.id]) add.push(addBody(b, i)); });
  const items = base.items.filter((b) => now[b.id] && !sameRow(b, now[b.id])).map((b) => (b.food_id == null
    ? { id: b.id, food_id: null, skipped: b.skipped }
    : { id: b.id, food_id: b.food_id, amount: b.amount, unit: b.unit, check: b.check, skipped: b.skipped }));
  const patch = {};
  if (base.servings !== meal.servings) patch.servings = base.servings;
  if (!sameYield(base.yield, meal.yield)) patch.yield = base.yield;
  return { remove, add, items, meal: Object.keys(patch).length ? patch : null };
}

export function changedSince(base, meal) {
  const r = restoreBody(base, meal);
  return r.items.length > 0 || r.meal != null || r.remove.length > 0 || r.add.length > 0;
}

// Rows that do not count: unmatched, skipped and Check Amount rows (the server counts them for nothing).
export const notCounted = (meal) => Math.max(0, (meal.items || []).length - (meal.matched || 0));

// "5 ingredients are not matched." for the Save Recipe choice, "5 ingredients are not counted." as the quiet note when logging.
const ingredientsText = (n, what) => n + (n === 1 ? ' ingredient is not ' : ' ingredients are not ') + what;
export const notMatchedText = (n) => sentence(ingredientsText(n, 'matched.'));
export const notCountedText = (n) => sentence(ingredientsText(n, 'counted.'));

// Save on Match Ingredients: what has to be asked. { ask: false } when every row is matched, else { ask: true, n }.
export function saveChoice(meal) {
  const n = notCounted(meal);
  return n > 0 ? { ask: true, n } : { ask: false, n: 0 };
}

// Save Without Them needs at least one matched row to leave a recipe.
export const canSaveWithout = (meal) => (meal.matched || 0) > 0;
export const SAVE_WITHOUT_NONE = 'A recipe needs at least one ingredient. Match one, or keep the others to finish later.';

// Pre-ticked rows when the page opens: every unmatched row.
export const unmatchedIds = (items) => items.filter((i) => matchState(i) === 'unmatched').map((i) => i.id);

// Claude suggestions that Accept All would apply: a food was proposed and the row is not skipped.
export function pendingProposals(items, props) {
  return items.filter((it) => !it.skipped && props[it.id] && props[it.id].food).map((it) => ({ item: it, p: props[it.id] }));
}

export function acceptAllText(n) { return 'Accept ' + n + (n === 1 ? ' Suggested Match' : ' Suggested Matches'); }

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
  return (meal.items || []).filter((it) => it.food && !it.skipped && !it.check && it.food_id != null)
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

// ---------- a logged recipe on Today (one recipe log) ----------

// A recipe log is one item of /api/day with kind recipe: the recipe's name, the portion logged, the summed nutrients and its
// ingredient rows as parts. Plain entries have kind food (older replies have no kind).
export const isRecipeLog = (e) => !!e && e.kind === 'recipe';

// How much of a recipe was logged: "1 serving", "1/2 serving", "2 servings", "25% of the recipe", "250 g", "1 cup".
export function recipeAmountText(amount, unit) {
  const n = Number(amount);
  if (unit === 'serving') return servingText(n) + (n > 1 ? ' servings' : ' serving');
  if (unit === 'pct') return fmtAmount(n) + '% of the recipe';
  return qtyText(n, unit) + ' ' + (YIELD_LABEL[unit] || unit);
}

// The amount column of a Today row, for a plain entry or a recipe log.
export const entryAmountText = (e) => (isRecipeLog(e) ? recipeAmountText(e.amount, e.unit) : amountText(e.amount, e.unit));

// Save As Recipe from Today: one checklist row per Today row, { ids, name, text }. A recipe log stands for its ingredient
// rows, so the new recipe holds ingredients and never a recipe inside a recipe. Rows whose food is gone are left out.
export function saveRecipeRows(entries) {
  const out = [];
  for (const e of entries || []) {
    if (isRecipeLog(e)) {
      const ids = (e.parts || []).filter((p) => p.food_id != null).map((p) => p.id);
      if (ids.length) out.push({ ids, name: e.name, text: recipeAmountText(e.amount, e.unit), recipe: true });
    } else if (e.food_id != null) out.push({ ids: [e.id], name: e.name, text: amountText(e.amount, e.unit), recipe: false });
  }
  return out;
}

// Entry ids of the ticked rows of saveRecipeRows, in order.
export const tickedIds = (rows, ticked) => rows.reduce((ids, r, i) => (ticked[i] ? ids.concat(r.ids) : ids), []);

// A recipe log at another share of the recipe, for the live numbers before Save: every nutrient scaled like its rows.
// The server works each row out again on Save, so this is a preview only.
export function scaledLog(log, fraction) {
  const k = log.fraction > 0 ? fraction / log.fraction : 1;
  const out = { ...log };
  ['kcal', 'carbs', 'protein', 'fat', ...MICROS.map((m) => m.key)].forEach((key) => {
    if (log[key] != null) out[key] = roundTo(Number(log[key]) * k, 2);
  });
  return out;
}

export const REMOVE_RECIPE_CONFIRM = 'Remove This Recipe From Today? ' + sentence('All of its ingredients are removed from your log');
export const partsText = (n) => plural(n, 'ingredient');

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
