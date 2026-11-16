// Pure helpers for matching ingredients on the recipe screen (v77, issue #49). No DOM access, safe to import from node.
// The recipe is saved first with every ingredient unmatched; each row is then matched in place, one compact line per ingredient.
import { qtyText, unitWord, fmtNum, sentence, matchedAmountText } from './util.js';
import { unmatchedIds, MATCH_MAX } from './recipeimport.js';

// ---------- row state machine ----------
// unmatched: no food and no suggestion waiting. suggested: a suggestion with a food waits for Accept or Change. accepted: a food is
// attached and counts. check: a food is attached but its amount still needs a look (Check Amount, counts for nothing yet).
// skipped: left out on purpose. The state is always worked out from the saved row and the waiting suggestion, never stored.
export const ROW_STATES = ['unmatched', 'suggested', 'accepted', 'check', 'skipped'];

export function rowState(item, proposal) {
  if (!item) return 'unmatched';
  if (item.skipped) return 'skipped';
  if (item.food) return item.check ? 'check' : 'accepted';
  return proposal && proposal.food ? 'suggested' : 'unmatched';
}

// What each state offers: the buttons on the row (primary) and the entries of its three dot menu. aiOn: Claude is usable for this
// user. canRemove: more than one row is left (a recipe keeps at least one). Issue #56: an unmatched or suggested row offers Search Again
// (inline search), Scan Barcode and Use Claude, each a single tap; the primary action stays on the row, the rest sit in the menu.
//   unmatched: + (finds the best pick, one free request) and, with Claude, the Claude sparkle.  suggested: Accept.  check: Edit Amount.
//   accepted and skipped: nothing on the row, everything in the menu.
export function rowActions(state, opts) {
  const o = opts || {};
  const menu = (keys) => keys.filter((k) => k !== 'remove' || o.canRemove !== false);
  const claude = o.aiOn ? ['claude'] : [];
  switch (state) {
    case 'suggested': return { primary: ['accept'], menu: menu(['search', 'scan', ...claude, 'find', 'skip', 'remove']) };
    case 'accepted': return { primary: [], menu: menu(['change', 'scan', 'find', 'amount', 'grams', 'skip', 'remove']) };
    case 'check': return { primary: ['amount'], menu: menu(['grams', 'change', 'scan', 'find', 'skip', 'remove']) };
    case 'skipped': return { primary: [], menu: menu(['unskip', 'remove']) };
    default: return { primary: ['match', ...claude], menu: menu(['search', 'scan', 'find', 'skip', 'remove']) };
  }
}

export const ACTION_LABELS = {
  match: 'Find Match', claude: 'Use Claude', accept: 'Accept', search: 'Search Again', scan: 'Scan Barcode', change: 'Change',
  find: 'More Options', amount: 'Edit Amount', grams: 'Enter Grams', skip: 'Skip', unskip: 'Unskip', remove: 'Remove',
};

// The status chip of a row, in words so color is never the only cue.
export function rowChip(state, proposal) {
  if (state === 'accepted') return 'Matched';
  if (state === 'check') return 'Check Amount';
  if (state === 'skipped') return 'Skipped';
  if (state === 'suggested') return proposal && proposal.method === 'search' ? 'Suggested' : 'Claude Suggests';
  return 'Not Matched';
}

// The line as the recipe says it: { head: "1 1/2 cup flour", note: "sifted" }. A row built in the app has no imported line and
// uses its food name and amount.
export function rowLine(item) {
  const src = (item && item.src) || null;
  const join = (amount, unit, name) => [amount == null ? '' : qtyText(Number(amount), unit || ''), unit === 'count' || !unit ? '' : unitWord(unit, Number(amount)), name]
    .filter((x) => x !== '' && x != null).join(' ');
  if (src && (src.name || src.text)) {
    if (src.name) return { head: join(src.amount, src.unit, src.name), note: src.note || '' };
    return { head: src.text, note: '' };
  }
  const food = item && item.food;
  if (food) return { head: join(item.amount, item.unit === 'serving' ? '' : item.unit, food.name), note: '' };
  return { head: 'Ingredient', note: '' };
}

// The food line under a matched or suggested row: "Butter, salted (Acme), 1 tbsp, 14 g, 102 kcal".
export function foodText(food, amount, unit, grams, kcal) {
  if (!food) return '';
  const name = food.brand ? food.name + ' (' + food.brand + ')' : food.name;
  return name + ', ' + matchedAmountText(amount, unit, grams) + (kcal == null ? '' : ', ' + fmtNum(kcal, 0) + ' kcal');
}

// ---------- Match and Match With Claude (issue #56) ----------
// One block at the top of the Ingredients: the count line, a choice of Match (default, walks the rows one at a time) or Match With
// Claude (only when Claude is usable; asks nothing, accepts what is confident), Start, and Continue Without Matching. Choosing and
// tapping Start is the confirmation: no dialog and no cost text.

export const MATCH_MODES = [['walk', 'Match'], ['claude', 'Match With Claude']];
export const matchModes = (aiOn) => MATCH_MODES.filter(([k]) => k === 'walk' || aiOn);
export const matchMode = (mode, aiOn) => (mode === 'claude' && aiOn ? 'claude' : 'walk');

// Rows still open: unmatched or with a suggestion waiting.
export const openCount = (items, props) => (items || []).filter((it) => {
  const s = rowState(it, props && props[it.id]);
  return s === 'unmatched' || s === 'suggested';
}).length;

// What the block shows. edit: the viewer can change the recipe. expanded: the Match link was tapped after Continue Without Matching.
// { choice: the mode choice and Start, dismiss: Continue Without Matching, link: the small Match link of a dismissed recipe }.
export function matchBlock(meal, props, opts) {
  const o = opts || {};
  const open = o.edit ? openCount(meal && meal.items, props) : 0;
  const dismissed = !!(meal && meal.match_prompt_dismissed);
  const choice = open > 0 && (!dismissed || !!o.expanded);
  return { choice, dismiss: choice && !dismissed, link: open > 0 && dismissed && !o.expanded };
}

// The rows the free search looks up: unmatched rows with no food suggested yet (a row that found nothing before is searched again).
export const searchIds = (items, props) => unmatchedIds(items).filter((id) => !(props && props[id] && props[id].food));

// A suggestion Match With Claude accepts on its own: the server marked it confident (Search: the same name or an earlier recipe's
// food; Claude: a chosen candidate at medium or high confidence).
export const isConfident = (p) => !!(p && p.food && p.confident === true);

// The rows to ask Claude about after the search: every unmatched row without a confident suggestion. full (Full Claude Use): also the
// confident ones, except a food from a previous recipe.
export const claudeIds = (items, props, full) => unmatchedIds(items).filter((id) => {
  const p = props && props[id];
  return !isConfident(p) || (!!full && !p.from_previous);
});

// The suggestions to accept on their own: open rows whose waiting suggestion is confident.
export const confidentIds = (items, props) => unmatchedIds(items).filter((id) => isConfident(props && props[id]));

// Splits ids into requests of at most n (40 for the search, 15 for Claude, as the server allows).
export function chunks(ids, n) {
  const out = [];
  for (let i = 0; i < (ids || []).length; i += n) out.push(ids.slice(i, i + n));
  return out;
}

export const countWord = (n, one, many) => n + ' ' + (n === 1 ? one : many);

// The note after Match With Claude: "Matched 8 ingredients. 3 suggestions are waiting for a look. 1 ingredient had no match."
export function claudeDoneText(accepted, waiting, none, cost) {
  const parts = [];
  parts.push(accepted ? 'Matched ' + countWord(accepted, 'ingredient', 'ingredients') + '.' : 'Nothing was sure enough to match on its own.');
  if (waiting) parts.push(countWord(waiting, 'suggestion is', 'suggestions are') + ' waiting for a look. Tap Accept on a row or start Match to go through them.');
  if (none) parts.push(countWord(none, 'ingredient', 'ingredients') + ' had no match.');
  if (cost) parts.push(cost);
  return parts.join(' ');
}

// The note when Match ends: "Matched 5 ingredients. 2 are still open."
export function walkDoneText(matched, left) {
  const a = matched ? 'Matched ' + countWord(matched, 'ingredient', 'ingredients') + '.' : 'Nothing was matched.';
  return left ? a + ' ' + countWord(left, 'ingredient is', 'ingredients are') + ' still open.' : a;
}

export { MATCH_MAX };

// ---------- Match: one at a time ----------
// Walks the rows that still need a food (unmatched or suggested), in list order, one at a time with Accept, Search Again, Scan Barcode
// and Use Claude, plus Skip (leave it for later) and Finish.

export const reviewOrder = (items, props) => (items || []).filter((it) => {
  const s = rowState(it, props && props[it.id]);
  return s === 'unmatched' || s === 'suggested';
}).map((it) => it.id);

// The next place in order after `from` whose row still needs a food (it may have been matched meanwhile), or -1 at the end.
export function reviewNext(order, items, props, from) {
  for (let i = (from == null ? -1 : from) + 1; i < order.length; i++) {
    const it = (items || []).find((x) => x.id === order[i]);
    const s = it ? rowState(it, props && props[it.id]) : null;
    if (s === 'unmatched' || s === 'suggested') return i;
  }
  return -1;
}

// "Ingredient 2 of 5" for the walker's heading.
export const reviewPos = (i, n) => 'Ingredient ' + (i + 1) + ' of ' + n;

// ---------- picking a food in the inline search ----------

// What the line says, for working out the amount once a food is picked (util.js matchAmount): amount, unit, printed size and name.
export function lineOf(item) {
  const src = (item && item.src) || null;
  if (!src) return { amount: item ? item.amount : null, unit: item ? item.unit : null, pkg: null, name: '' };
  return { amount: src.amount, unit: src.unit, pkg: src.pkg_amount ? { amount: src.pkg_amount, unit: src.pkg_unit } : null, name: src.name || '',
    was: src.estimated && src.was_amount ? { amount: src.was_amount, unit: src.was_unit } : null };
}

// The text the inline search starts with: the ingredient name, else the line.
export const searchStart = (item) => (item && item.src && (item.src.name || item.src.text)) || (item && item.food && item.food.name) || '';

export const SEARCH_RESULTS = 5;  // results shown in the inline search, each a single tap

// The inline search results: at most 5, foods without an id left out (they cannot be attached).
export const topResults = (results) => (results || []).filter((f) => f && f.id != null).slice(0, SEARCH_RESULTS);

// The ingredient count line: "3 of 8 matched", plus "2 suggested" when suggestions wait.
export function matchedLine(meal, props) {
  const items = (meal && meal.items) || [];
  const waiting = items.filter((it) => rowState(it, props && props[it.id]) === 'suggested').length;
  let t = (meal.matched || 0) + ' of ' + (meal.needed != null ? meal.needed : items.length) + ' matched';
  if (meal.checks) t += ', ' + meal.checks + ' to check';
  if (waiting) t += ', ' + waiting + ' suggested';
  return meal.skipped ? t + ', ' + meal.skipped + ' skipped' : t;
}

// The body that puts a removed row back at its place (POST /api/meals/{id}/items), for Undo after Remove.
export function restoreRowBody(item, position) {
  const out = { position };
  if (item.src) out.src = { ...item.src };
  if (item.food_id != null) { out.food_id = item.food_id; out.amount = item.amount; out.unit = item.unit; if (item.check) out.check = true; }
  if (item.skipped) out.skipped = true;
  return out;
}
