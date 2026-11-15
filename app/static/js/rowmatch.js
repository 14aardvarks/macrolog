// Pure helpers for matching ingredients on the recipe screen (v77, issue #49). No DOM access, safe to import from node.
// The recipe is saved first with every ingredient unmatched; each row is then matched in place, one compact line per ingredient.
import { qtyText, unitWord, fmtNum, sentence, matchedAmountText } from './util.js';
import { unmatchedIds, methodBatch, autoClaudeBatch, autoMatchPlan, MATCH_MAX } from './recipeimport.js';

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
// user. canRemove: more than one row is left (a recipe keeps at least one).
//   unmatched: + (Search, one request) and, with Claude, the Claude +.  suggested: Accept and Change.  check: Edit Amount.
//   accepted and skipped: nothing on the row, everything in the menu.
export function rowActions(state, opts) {
  const o = opts || {};
  const menu = (keys) => keys.filter((k) => k !== 'remove' || o.canRemove !== false);
  switch (state) {
    case 'suggested': return { primary: ['accept', 'change'], menu: menu([...(o.aiOn ? ['claude'] : []), 'find', 'skip', 'remove']) };
    case 'accepted': return { primary: [], menu: menu(['change', 'find', 'amount', 'grams', 'skip', 'remove']) };
    case 'check': return { primary: ['amount'], menu: menu(['grams', 'change', 'find', 'skip', 'remove']) };
    case 'skipped': return { primary: [], menu: menu(['unskip', 'remove']) };
    default: return { primary: ['match', ...(o.aiOn ? ['claude'] : [])], menu: menu(['change', 'find', 'skip', 'remove']) };
  }
}

export const ACTION_LABELS = {
  match: 'Match Ingredient', claude: 'Match With Claude', accept: 'Accept', change: 'Change', find: 'Search Another', amount: 'Edit Amount',
  grams: 'Enter Grams', skip: 'Skip', unskip: 'Unskip', remove: 'Remove',
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

// ---------- Match All ----------
// Match All (Search, Claude or Search Then Claude) matches every unmatched row, then Accept N Suggested Matches appears once.

export const MATCH_ALL_MODES = [['search', 'Match All With Search'], ['claude', 'Match All With Claude'], ['search_claude', 'Search Then Claude']];

// The rows Search should look up: unmatched rows with no suggestion waiting (a suggested row already has one), up to 40.
export const searchIds = (items, props) => methodBatch('search', unmatchedIds(items).filter((id) => !(props && props[id] && props[id].food)));

// The plan of one Match All run. mode: search, claude or search_claude. aiOn: Claude is usable. full: Full Claude Use (Claude then asks
// about every row Search did not take from a previous recipe). { search: run Search first, claude: then ask Claude, all: the Claude
// step also asks rows Search suggested, note: Claude was wanted but is not available }.
export function matchAllPlan(mode, aiOn, full) {
  const p = autoMatchPlan(mode, aiOn);
  return { ...p, all: p.claude && (mode === 'claude' || !!full) };
}

// The rows to ask Claude about after Search ran (or at once for Claude only): { send (at most 15), rest }.
export const claudeIds = (items, props, all) => autoClaudeBatch(items, props, all);

// "4 more are still unmatched. Tap Match All again for them." when a run left rows past the cap, else ''.
export function moreText(rest) {
  if (!rest) return '';
  return sentence(rest + (rest === 1 ? ' more is' : ' more are') + ' still unmatched. Tap Match All again for them');
}

export { MATCH_MAX };

// ---------- Review One By One ----------
// Walks the rows that still need a food (unmatched or suggested), in list order, one at a time with Accept, Change and Skip.

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
  return { amount: src.amount, unit: src.unit, pkg: src.pkg_amount ? { amount: src.pkg_amount, unit: src.pkg_unit } : null, name: src.name || '' };
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
