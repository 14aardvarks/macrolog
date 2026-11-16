// The Ingredients section of the recipe screen (v77, issue #49): one compact line per ingredient, matched in place. An unmatched
// row has one + (Match Ingredient: Search for that row, one request, the top suggestion shows on the row with Accept and Change)
// and, when Claude is usable, a small Claude + (Match With Claude, the usual confirm, cost and cap). Everything else sits in the
// row's three dot menu. Match All matches every unmatched row (Search, Claude or Search Then Claude), Review One By One walks them.
// Every change is written at once and the recipe's totals follow live through opts.onMeal.
import { api } from './api.js';
import { h, svg, clear, field, message, show, sourceBadge, unitControl, kcalCue, checkBlock, weightTagNode } from './dom.js';
import { confirmClaude } from './notice.js';
import { unitChoices, fmtNum, sentence, amountMemo, matchAmount, linePick, isMeasureUnit, weightReasonLine, centsText, checkReasonLine, effectiveAutoMatch, CLAUDE_CAP_NOTE, ESTIMATE_SOURCES, weightTag, qtyText, unitWord } from './util.js';
import {
  parseIngredientLine, matchWhat, matchDoneText, pendingProposals, acceptAllText, previousCountText, PREVIOUS_CUE, AUTO_MATCH_LOADING,
  AUTO_MATCH_FAILED, autoMatchResult, claudeKeep, claudeOffNote, AUTO_CLAUDE_FAILED, AUTO_CLAUDE_CANCELLED, rateLimitNote, unmatchedIds,
} from './recipeimport.js';
import {
  rowState, rowActions, ACTION_LABELS, rowChip, rowLine, foodText, MATCH_ALL_MODES, searchIds, matchAllPlan, claudeIds, reviewOrder,
  reviewNext, reviewPos, lineOf, searchStart, topResults, matchedLine, restoreRowBody, matchPromptCount, matchPromptShows, matchPromptText,
} from './rowmatch.js';
import { menuButton } from './menu.js';

// The Claude + face: a small sparkle with a plus, drawn (no emoji, no markup strings).
function sparkle() {
  return svg('svg', { viewBox: '0 0 24 24', width: '22', height: '22', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8',
    'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'aria-hidden': 'true', focusable: 'false', class: 'icon' },
  svg('path', { d: 'M10 3l1.6 4.4L16 9l-4.4 1.6L10 15l-1.6-4.4L4 9l4.4-1.6z', fill: 'currentColor' }),
  svg('path', { d: 'M18 14v6M15 17h6' }));
}

// meal: the recipe (GET /api/meals/{id}). ctx: app ctx (flow.proposals, flow.find, flow.searchSource, settings, display).
// opts: { st: /api/ai/status, edit: can change it, onMeal(meal): the recipe changed, status: an aria-live box for notes }.
// Returns { el, focus(id) }. Nothing matches on its own: the banner at the top offers Match Ingredients (the Auto-Match After Import setting)
// while rows are unmatched, and Continue Without Matching hides it for good (saved on the recipe).
export function ingredientSection(meal, ctx, opts) {
  const o = opts || {};
  const st = o.st || { enabled: false };
  const edit = o.edit !== false;
  const aiOn = edit && !!(st && st.enabled && !(st.features && st.features.recipe === false));
  const props = ctx.flow.proposals(meal.id);  // suggestions waiting for Accept, kept for the session (the finder and back keep them)
  const busy = {};  // item id -> 'search' | 'claude' while that row's request runs
  let running = false;  // Match All or Match Ingredients is running
  let acted = false;  // a Match All, Match Ingredients or Review One By One started in this visit: the banner stays hidden
  let panel = null;  // { id, kind: 'search' | 'amount' | 'grams' } the one open editor on a row
  const status = h('div', { class: 'ing-status-box', 'aria-live': 'polite' });
  const limitNote = h('div', { 'aria-live': 'polite' });
  const count = h('p', { class: 'match-count ing-count' });
  const checks = h('div');
  const list = h('ul', { class: 'ing-list' });
  const reviewBox = h('div');
  const acceptBtn = h('button', { class: 'btn primary', type: 'button', onclick: acceptAll }, '');
  const previousNote = h('span', { class: 'sub match-previous' });
  const acceptRow = h('div', { class: 'row wrap match-bulk' }, acceptBtn, previousNote);
  const fail = (e) => show(status, message(e.message, 'error'));
  const say = (t) => show(status, t ? message(t) : null);
  const itemOf = (id) => meal.items.find((x) => x.id === id);

  function setMeal(m) {
    meal = m;
    if (o.onMeal) o.onMeal(m);
  }
  const drop = (ids) => ids.forEach((id) => { delete props[id]; });

  // ---------- writes ----------
  async function apply(item, body, focusKey) {
    try {
      setMeal(await api.matchItem(meal.id, item.id, body));
      drop([item.id]);
      panel = null;
      paint(item.id, focusKey);
      return true;
    } catch (e) { fail(e); return false; }
  }
  // A Claude estimate becomes a food only on Accept, kept on the proposal so trying again never saves it twice.
  async function foodOf(p) {
    if (!p.food.id) p.food = await api.createFood(p.food);
    return p.food;
  }
  async function accept(item, p) {
    try {
      const food = await foodOf(p);
      return await apply(item, { food_id: food.id, amount: p.amount, unit: p.unit, ...(p.check ? { check: true } : {}) });
    } catch (e) { fail(e); return false; }
  }
  // Grams typed in an Estimated Weight tag: a match in g with remember, so they become your weight of one of the line's unit.
  async function typedGrams(item, foodId, foodName, grams) {
    setMeal(await api.matchItem(meal.id, item.id, { food_id: foodId, amount: grams, unit: 'g', remember: true }));
    drop([item.id]);
    paint(item.id);
    say('Saved ' + fmtNum(grams, 1) + ' g for ' + foodName + '. The weight is remembered for this food.');
  }
  // A food picked in the inline search: the amount comes from the recipe line (util.js matchAmount), else one label serving with
  // Check Amount, the same rule as the food finder.
  async function pickFood(item, f) {
    try {
      const food = await api.food(f.id);
      const line = lineOf(item);
      const label = food.units[0];
      const pick = linePick(food.units, line) || { amount: label.default_amount, unit: label.unit, check: true };
      const ok = await apply(item, { food_id: food.id, amount: pick.amount, unit: pick.unit, ...(pick.check ? { check: true } : {}) });
      if (ok) say(sentence('Matched ' + rowLine(item).head + ' to ' + food.name));
      return ok;
    } catch (e) { fail(e); return false; }
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
      paint();
      say(rows.length + (rows.length === 1 ? ' suggestion accepted.' : ' suggestions accepted.'));
    } catch (e) { fail(e); } finally { acceptBtn.disabled = false; }
  }
  async function removeRow(item) {
    const at = meal.items.findIndex((x) => x.id === item.id);
    const head = rowLine(item).head;
    try {
      setMeal(await api.deleteMealItem(meal.id, item.id));
      drop([item.id]);
      if (panel && panel.id === item.id) panel = null;
      const next = meal.items[Math.min(at, meal.items.length - 1)];
      paint(next && next.id);
      const undo = h('button', { class: 'link-btn', type: 'button', onclick: async () => {
        undo.disabled = true;
        try { const { added, ...m } = await api.addMealItem(meal.id, restoreRowBody(item, at)); setMeal(m); paint(added); say(sentence('Put back ' + head)); } catch (e) { fail(e); }
      } }, 'Undo');
      show(status, h('p', { class: 'msg' }, sentence('Removed ' + head) + ' ', undo));
    } catch (e) { fail(e); }
  }

  // ---------- one row: + (Search) and Claude + ----------
  const showLimit = (r) => { const t = rateLimitNote(r); show(limitNote, t ? h('p', { class: 'sub match-limit', role: 'status' }, t) : null); };
  async function searchRow(item) {
    busy[item.id] = 'search';
    paintRow(item.id, 'busy');
    try {
      const r = await api.matchSearch(meal.id, [item.id], ctx.flow.searchSource());
      showLimit(r);
      const { fresh } = autoMatchResult(meal.items, r.proposals);
      fresh.forEach((p) => { props[p.item_id] = p; });
      say(null);
    } catch (e) { fail(e); } finally { delete busy[item.id]; paint(item.id, props[item.id] && props[item.id].food ? 'accept' : 'change'); }
  }
  async function claudeRow(item) {
    if (!(await confirmClaude(ctx.settings, { what: matchWhat(1), query: { match_rows: 1 } }))) return;
    busy[item.id] = 'claude';
    paintRow(item.id, 'busy');
    try {
      const r = await api.matchIngredients(meal.id, [item.id]);
      claudeKeep(r.proposals, props).forEach((p) => { props[p.item_id] = p; });
      say(r.cost != null ? 'This cost about ' + centsText(r.cost) + '.' : null);
    } catch (e) { fail(e); } finally { delete busy[item.id]; paint(item.id, props[item.id] && props[item.id].food ? 'accept' : 'change'); }
  }

  // ---------- Match All ----------
  // mode: search, claude or search_claude. auto: Auto-Match After Import (Full Claude Use sends without asking, the cap gives a
  // quiet note); otherwise the usual confirm for the Claude step. Never blocks the page; a failure only leaves rows unmatched.
  async function runAll(mode, auto) {
    if (running) return;
    const full = ctx.settings.full_claude === true;
    const base = matchAllPlan(mode, aiOn, full);
    const plan = base.note ? { ...base, note: claudeOffNote(st) } : base;
    if (!plan.search && !plan.claude) return;
    acted = true;
    running = true;
    status.setAttribute('aria-busy', 'true');
    show(limitNote, null);
    paintHead();
    const keep = (r) => {
      const { fresh } = autoMatchResult(meal.items, r.proposals);
      fresh.forEach((p) => { props[p.item_id] = p; });
      return fresh;
    };
    let text = '';
    try {
      if (plan.search) {
        const b = searchIds(meal.items, props);
        if (b.send.length) {
          b.send.forEach((id) => { busy[id] = 'search'; });
          paintRows();
          say(auto ? AUTO_MATCH_LOADING : 'Searching for ' + b.send.length + (b.send.length === 1 ? ' ingredient...' : ' ingredients...'));
          let r;
          try { r = await api.matchSearch(meal.id, b.send, ctx.flow.searchSource()); } finally { b.send.forEach((id) => { delete busy[id]; }); }
          const fresh = keep(r);
          showLimit(r);
          text = matchDoneText('search', fresh, b.rest.length, '');
          paintRows();
          say(text);
        }
      }
      if (plan.claude) {
        const b = claudeIds(meal.items, props, plan.all);
        if (b.send.length) {
          let go = true;
          if (auto) {
            let left = null;  // the monthly cap: automatic Claude steps stop there with one quiet note, nothing is sent
            try { left = (await api.aiStatus()).remaining; } catch (e) { left = null; }
            if (left != null && left <= 0) { go = false; text = [text, CLAUDE_CAP_NOTE].filter(Boolean).join(' '); }
            else if (!full) go = await confirmClaude(ctx.settings, { what: matchWhat(b.send.length), query: { match_rows: b.send.length } });
            if (!go && !(left != null && left <= 0)) text = [text, AUTO_CLAUDE_CANCELLED].filter(Boolean).join(' ');
          } else {
            go = await confirmClaude(ctx.settings, { what: matchWhat(b.send.length), query: { match_rows: b.send.length } });
            if (!go) text = [text, AUTO_CLAUDE_CANCELLED].filter(Boolean).join(' ');
          }
          if (go) {
            b.send.forEach((id) => { busy[id] = 'claude'; });
            paintRows();
            say('Claude is matching ' + b.send.length + (b.send.length === 1 ? ' ingredient...' : ' ingredients...'));
            try {
              const r = await api.matchIngredients(meal.id, b.send);
              keep({ ...r, proposals: claudeKeep(r.proposals, props) });
              text = matchDoneText('claude', b.send.map((id) => props[id]).filter(Boolean), b.rest.length, r.cost != null ? 'This cost about ' + centsText(r.cost) + '.' : '');
            } catch (e) { text = [text, AUTO_CLAUDE_FAILED].filter(Boolean).join(' '); } finally { b.send.forEach((id) => { delete busy[id]; }); }
          }
        }
      }
      if (!text && !plan.note && !searchIds(meal.items, props).send.length) text = 'Every ingredient has a match or a suggestion.';
      running = false;
      paint();
      say([text, plan.note].filter(Boolean).join(' '));
    } catch (e) {
      Object.keys(busy).forEach((k) => { delete busy[k]; });
      running = false;
      paint();
      if (auto) say(AUTO_MATCH_FAILED); else fail(e);
    } finally { running = false; status.removeAttribute('aria-busy'); paintHead(); }
  }
  // Match Ingredients (the banner): the Auto-Match After Import setting (Full Claude Use turns the default Search into Search Then Claude).
  // Off opens the choice menu instead of running anything.
  function matchPrompted() {
    const eff = effectiveAutoMatch(ctx.display.auto_match, ctx.settings.full_claude === true);
    if (eff.value === 'off') { const m = promptWrap.querySelector('.split-more'); if (m) m.click(); return; }
    runAll(eff.value, true);
  }
  async function dismissPrompt() {
    dismissBtn.disabled = true;
    try {
      const m = await api.patchMeal(meal.id, { match_prompt_dismissed: true });
      meal.match_prompt_dismissed = m.match_prompt_dismissed;
    } catch (e) { fail(e); } finally { dismissBtn.disabled = false; }
    paintHead();
  }

  // Match All: a split button. The main part runs Search (free); the small menu offers Claude, Search Then Claude and Review One By One.
  const allBtn = h('button', { class: 'btn split-main', type: 'button', 'aria-label': 'Match All With Search', onclick: () => runAll('search', false) },
    h('span', { class: 'plus', 'aria-hidden': 'true' }, '+'), ' Match All');
  const allWrap = h('div', { class: 'split-btn' });
  const modes = MATCH_ALL_MODES.filter(([k]) => k === 'search' || aiOn).map(([key, label]) => ({ key, label }));
  const modeItems = [...modes, { key: 'review', label: 'Review One By One' }];
  const pickMode = (k) => (k === 'review' ? startReview() : runAll(k, false));
  const moreFace = () => ({ btnClass: 'btn split-more', wrapClass: 'card-menu-wrap split-menu', title: 'More Ways to Match', face: h('span', { class: 'caret', 'aria-hidden': 'true' }) });
  allWrap.append(allBtn, menuButton(allWrap, modeItems, 'More Ways to Match', (k) => (k === 'review' ? startReview() : runAll(k, false)), moreFace()));
  const tools = h('div', { class: 'row wrap ing-tools' }, allWrap);

  // The banner: Match Ingredients with a small menu of the other ways, and Continue Without Matching.
  const promptText = h('p', { class: 'match-prompt-text' });
  const promptWrap = h('div', { class: 'split-btn' });
  promptWrap.append(h('button', { class: 'btn split-main', type: 'button', onclick: matchPrompted }, 'Match Ingredients'),
    menuButton(promptWrap, modeItems, 'More Ways to Match Ingredients', pickMode, moreFace()));
  const dismissBtn = h('button', { class: 'btn ghost', type: 'button', onclick: dismissPrompt }, 'Continue Without Matching');
  const prompt = h('div', { class: 'sheet match-prompt', role: 'group', 'aria-label': 'Match Ingredients', hidden: true },
    promptText, h('div', { class: 'row wrap' }, promptWrap, dismissBtn));

  // ---------- Review One By One ----------
  let review = null;  // { order, i, searching }
  function startReview() {
    const order = reviewOrder(meal.items, props);
    acted = true;
    if (!order.length) { say('Every ingredient has a food.'); return; }
    review = { order, i: reviewNext(order, meal.items, props, null), search: false, tried: {} };
    paintReview(true);
  }
  function stepReview() {
    if (!review) return;
    review.i = reviewNext(review.order, meal.items, props, review.i);
    review.search = false;
    if (review.i < 0) { review = null; show(reviewBox, null); say('Review done.'); focusTools(); return; }
    paintReview(true);
  }
  function endReview() { review = null; show(reviewBox, null); paintHead(); focusTools(); }
  function focusTools() { const b = tools.querySelector('.split-main'); if (b && !b.closest('[hidden]')) b.focus(); }
  async function paintReview(focus) {
    if (!review) return;
    const item = itemOf(review.order[review.i]);
    if (!item) { stepReview(); return; }
    const p = props[item.id];
    const line = rowLine(item);
    const head = h('h3', { id: 'review-title', tabindex: '-1' }, reviewPos(review.i, review.order.length));
    const body = [];
    if (busy[item.id]) body.push(h('p', { class: 'sub' }, busy[item.id] === 'claude' ? 'Claude is matching...' : 'Searching...'));
    else if (p && p.food) body.push(suggestionNode(item, p));
    else if (p) body.push(h('p', { class: 'sub' }, sentence(p.note || 'No match found')));
    const btns = h('div', { class: 'row wrap' },
      p && p.food && !busy[item.id] ? h('button', { class: 'btn primary', type: 'button', onclick: async () => { if (await accept(item, p)) stepReview(); } }, 'Accept') : null,
      h('button', { class: 'btn', type: 'button', onclick: () => { review.search = !review.search; paintReview(false); } }, 'Change'),
      h('button', { class: 'btn', type: 'button', onclick: async () => { if (await apply(item, { skipped: true })) stepReview(); } }, 'Skip'),
      h('button', { class: 'btn', type: 'button', onclick: stepReview }, 'Next'),
      h('button', { class: 'btn ghost', type: 'button', onclick: endReview }, 'Done'));
    show(reviewBox, h('div', { class: 'sheet review-one', role: 'group', 'aria-labelledby': 'review-title' },
      head, h('p', { class: 'review-line' }, line.head, line.note ? h('span', { class: 'ing-note' }, ', ' + line.note) : null),
      body, btns,
      review.search ? searchBox(item, async (f) => { if (await pickFood(item, f)) stepReview(); }, () => { review.search = false; paintReview(false); }) : null));
    if (focus) head.focus();
    if (!p && !busy[item.id] && !review.tried[item.id]) {  // no suggestion yet: one Search for this row, once
      review.tried[item.id] = true;
      busy[item.id] = 'search';
      paintReview(false);
      try {
        const r = await api.matchSearch(meal.id, [item.id], ctx.flow.searchSource());
        autoMatchResult(meal.items, r.proposals).fresh.forEach((x) => { props[x.item_id] = x; });
      } catch (e) { fail(e); } finally { delete busy[item.id]; }
      paintRows();
      paintReview(false);
    }
  }

  // ---------- inline search (Change) ----------
  // A search box filled with the ingredient name that searches at once, up to 5 results, each a single tap. Escape closes.
  function searchBox(item, onPick, onClose) {
    const q = h('input', { type: 'search', class: 'ing-q', value: searchStart(item), autocomplete: 'off', enterkeyhint: 'search',
      'aria-label': 'Search foods for ' + rowLine(item).head, maxlength: '200' });
    const results = h('ul', { class: 'ing-results', 'aria-live': 'polite' });
    let seq = 0;
    async function run() {
      const text = q.value.trim();
      if (!text) { show(results, h('li', { class: 'sub' }, 'Type a food to search for.')); return; }
      const n = ++seq;
      show(results, h('li', { class: 'sub' }, 'Searching...'));
      let found;
      try { found = topResults((await api.search(text, true, ctx.flow.searchSource())).results); } catch (e) { if (n === seq) show(results, h('li', { class: 'sub' }, e.message)); return; }
      if (n !== seq) return;
      clear(results);
      if (!found.length) { results.appendChild(h('li', { class: 'sub' }, sentence('Nothing found. Try other words, or Search Another for scan and manual entry'))); return; }
      found.forEach((f) => results.appendChild(h('li', null, h('button', { class: 'ing-result', type: 'button', onclick: (e) => { e.currentTarget.disabled = true; onPick(f); } },
        h('span', { class: 'ing-result-name' }, f.brand ? f.name + ' (' + f.brand + ')' : f.name), ' ', sourceBadge(f.source, true),
        h('span', { class: 'sub ing-result-sub' }, fmtNum(f.kcal, 0) + ' kcal per ' + qtyText(f.serving_amount, f.serving_unit) + ' ' + unitWord(f.serving_unit, f.serving_amount))))));
    }
    q.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); run(); } else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    });
    const box = h('div', { class: 'ing-search', role: 'search' },
      h('div', { class: 'row ing-search-row' }, q, h('button', { class: 'btn small', type: 'button', onclick: run }, 'Search'),
        h('button', { class: 'btn small ghost', type: 'button', onclick: onClose }, 'Cancel')),
      results);
    setTimeout(() => { q.focus(); run(); }, 0);
    return box;
  }

  // ---------- Edit Amount and Enter Grams ----------
  const unitCache = {};
  const unitsOf = (id) => unitCache[id] || (unitCache[id] = api.food(id).then((f) => f.units));
  function amountEditor(item, grams) {
    const name = item.food.name;
    const memo = amountMemo();
    const amt = field('Amount', { inputmode: 'decimal', autocomplete: 'off', value: grams ? '' : memo.set(item.amount, item.unit), 'aria-label': 'Amount of ' + name });
    const unitBox = h('label', { class: 'field unit-field' }, h('span', null, 'Unit'), h('span', { class: 'sub' }, 'Loading...'));
    const save = h('button', { class: 'btn small primary', type: 'button', disabled: true }, item.check ? 'Confirm Amount' : 'Save Amount');
    const close = () => { panel = null; paint(item.id, 'menu'); };
    let unitSel = null;
    unitsOf(item.food_id).then((us) => {
      // weights and volumes only (issue #55); the row's own count, package or label word stays as an extra option
      const measures = unitChoices(us).filter((u) => isMeasureUnit(u.value));
      unitSel = unitControl(measures.map((u) => ({ value: u.value, label: u.label + (u.estimated ? ' (estimated)' : '') })), grams ? 'g' : item.unit,
        { 'aria-label': 'Unit of ' + name }, { blank: false });
      if (grams && !us.some((u) => u.unit === 'g')) unitSel.value = item.unit;
      unitBox.replaceChild(unitSel, unitBox.lastChild);
      save.disabled = false;
    }, fail);
    save.addEventListener('click', () => {
      const a = memo.value(amt.input.value);
      if (!amt.input.value.trim()) { apply(item, { skipped: true }); return; }  // no amount: it stays a plain text line, counting nothing
      if (a == null || a <= 0) { show(status, message('Check the amount of ' + name + '.', 'error')); amt.input.focus(); return; }
      const remember = (grams || item.check) && ['g', 'kg', 'oz', 'lb'].indexOf(unitSel.value) >= 0;
      apply(item, { food_id: item.food_id, amount: a, unit: unitSel.value, ...(remember ? { remember: true } : {}) });
    });
    amt.input.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); close(); } else if (e.key === 'Enter') { e.preventDefault(); save.click(); } });
    return h('div', { class: 'amount-check ing-panel', role: 'group', 'aria-label': (grams ? 'Grams of ' : 'Amount of ') + name },
      item.check && !grams ? h('p', { class: 'sub' }, sentence('Enter the amount, or leave it empty to keep the line as plain text')) : null,
      grams ? h('p', { class: 'sub' }, sentence('The grams you type are remembered as your weight for this food')) : null,
      h('div', { class: 'amount-edit' }, amt, unitBox, save, h('button', { class: 'btn small ghost', type: 'button', onclick: close }, 'Cancel')));
  }

  // ---------- painting ----------
  function suggestionNode(item, p) {
    const est = p.kind === 'estimate' && !p.food.id;
    const tag = weightTag(p) ? weightTagNode(p, p.food.name, edit ? (g) => foodOf(p).then((f) => typedGrams(item, f.id, f.name, g)) : null) : null;
    return h('span', { class: 'ing-detail' },
      h('span', { class: 'ing-food' }, foodText(p.food, p.amount, p.unit, p.grams, p.preview ? p.preview.kcal : null), p.check ? ' (check the amount)' : ''),
      ' ', sourceBadge(p.food.source, true),
      p.from_previous ? h('span', { class: 'src-est previous-cue' }, ' ' + PREVIOUS_CUE) : null,
      est ? h('span', { class: 'src-est' }, ' Claude Estimate, saved as a food on Accept') : null,
      tag ? [' ', tag] : p.estimated ? h('span', { class: 'src-est' }, ' Estimated Conversion') : null);
  }
  function statusNode(item, state, p) {
    const chip = h('span', { class: 'match-state ing-chip chip-' + state }, rowChip(state, p));
    if (busy[item.id]) return h('span', { class: 'ing-state' }, chip, ' ', h('span', { class: 'sub ing-busy' }, busy[item.id] === 'claude' ? 'Claude is matching...' : 'Searching...'));
    if (state === 'suggested') return h('span', { class: 'ing-state' }, chip, ' ', suggestionNode(item, p));
    if (state === 'accepted' || state === 'check') {
      const f = item.food;
      const tag = state === 'check' ? null : weightTagNode(item, f.name, edit ? (g) => typedGrams(item, item.food_id, f.name, g) : null);
      return h('span', { class: 'ing-state' }, chip, ' ',
        h('span', { class: 'ing-detail' }, h('span', { class: 'ing-food' }, foodText(f, item.amount, item.unit, item.grams, state === 'check' ? null : item.kcal)),
          ' ', sourceBadge(f.source, true), state === 'check' ? null : kcalCue(item),
          tag ? [' ', tag] : item.estimated && state !== 'check' ? h('span', { class: 'src-est', title: 'From ' + (ESTIMATE_SOURCES[item.estimate_source] || ESTIMATE_SOURCES.guess) }, ' Estimated Conversion') : null),
        state === 'check' ? h('span', { class: 'check-reason' }, checkReasonLine(item.check_reason, (item.src && item.src.unit) || item.unit)) : null);
    }
    const reason = item.src ? weightReasonLine(item.src.weight_reason, item.src.unit) : '';  // a count no typical weight knows (issue #55)
    return h('span', { class: 'ing-state' }, chip, p && !p.food ? h('span', { class: 'sub' }, ' ' + sentence(p.note || 'No match found')) : null,
      item.src && item.src.estimated && !p ? h('span', { class: 'src-est' }, ' Estimated') : null,
      reason ? h('span', { class: 'check-reason' }, reason) : null);
  }
  function rowNode(item) {
    const p = props[item.id];
    const state = rowState(item, p);
    const line = rowLine(item);
    const lineId = 'ing-line-' + item.id;
    const acts = rowActions(state, { aiOn, canRemove: meal.items.length > 1 });
    const isBusy = !!busy[item.id] || running;
    const btn = (key, cls, kids, onclick) => h('button', { class: cls, type: 'button', 'data-act': key, 'aria-label': ACTION_LABELS[key], 'aria-describedby': lineId,
      disabled: isBusy, 'aria-busy': busy[item.id] && (key === 'match' || key === 'claude') ? 'true' : null, onclick }, kids);
    const side = h('div', { class: 'ing-btns' });
    const below = h('div', { class: 'row wrap ing-acts' });
    if (edit) {
      for (const k of acts.primary) {
        if (k === 'match') side.appendChild(btn('match', 'ing-plus', h('span', { 'aria-hidden': 'true' }, '+'), () => searchRow(item)));
        else if (k === 'claude') side.appendChild(btn('claude', 'ing-claude', sparkle(), () => claudeRow(item)));
        else if (k === 'accept') below.appendChild(h('button', { class: 'btn small primary', type: 'button', 'data-act': 'accept', disabled: isBusy, 'aria-describedby': lineId, onclick: () => accept(item, p) }, 'Accept'));
        else if (k === 'change') below.appendChild(h('button', { class: 'btn small', type: 'button', 'data-act': 'change', disabled: isBusy, 'aria-describedby': lineId, onclick: () => openPanel(item, 'search') }, 'Change'));
        else if (k === 'amount') below.appendChild(h('button', { class: 'btn small', type: 'button', 'data-act': 'amount', disabled: isBusy, 'aria-describedby': lineId, onclick: () => openPanel(item, 'amount') }, 'Edit Amount'));
      }
      const li = h('li');
      side.appendChild(menuButton(li, acts.menu.map((k) => ({ key: k, label: ACTION_LABELS[k], danger: k === 'remove' })), 'More Actions for ' + line.head,
        (k) => menuAct(item, k), { btnClass: 'ing-menu-btn', wrapClass: 'card-menu-wrap ing-menu' }));
      return fillRow(li, item, state, p, line, lineId, side, below);
    }
    return fillRow(h('li'), item, state, p, line, lineId, null, below);
  }
  function fillRow(li, item, state, p, line, lineId, side, below) {
    li.className = 'ing-row state-' + state;
    li.id = 'ing-' + item.id;
    li.setAttribute('tabindex', '-1');
    const kids = [h('div', { class: 'ing-main' },
      h('div', { class: 'ing-text' },
        h('span', { class: 'ing-line', id: lineId }, line.head, line.note ? h('span', { class: 'ing-note' }, ', ' + line.note) : null),
        statusNode(item, state, p)),
      side),
    below.childNodes.length ? below : null,
    panel && panel.id === item.id ? panelNode(item) : null];
    kids.forEach((k) => { if (k) li.appendChild(k); });  // append() would write null as text
    return li;
  }
  function panelNode(item) {
    if (panel.kind === 'search') return h('div', { class: 'ing-panel' }, searchBox(item, (f) => pickFood(item, f), () => { panel = null; paint(item.id, 'menu'); }));
    if (!item.food) { panel = null; return null; }
    return amountEditor(item, panel.kind === 'grams');
  }
  function openPanel(item, kind) {
    panel = panel && panel.id === item.id && panel.kind === kind ? null : { id: item.id, kind };
    paint(item.id);
    if (panel && kind !== 'search') { const el = document.querySelector('#ing-' + item.id + ' .ing-panel input'); if (el) el.focus(); }
  }
  function menuAct(item, key) {
    if (key === 'claude') claudeRow(item);
    else if (key === 'change') openPanel(item, 'search');
    else if (key === 'find') { delete props[item.id]; ctx.flow.find(meal, item, 'search'); }
    else if (key === 'amount') openPanel(item, 'amount');
    else if (key === 'grams') openPanel(item, 'grams');
    else if (key === 'skip') apply(item, { skipped: true }, 'menu');
    else if (key === 'unskip') apply(item, { skipped: false }, 'menu');
    else if (key === 'remove') removeRow(item);
  }

  // Focus after a repaint: the same row's next useful control, so keyboard users never lose their place.
  function focusRow(id, key) {
    const li = document.getElementById('ing-' + id);
    if (!li) return;
    const pick = (sel) => li.querySelector(sel);
    const el = (key === 'accept' && pick('[data-act=accept]')) || (key === 'change' && pick('[data-act=change]')) || (key === 'menu' && pick('.ing-menu-btn'))
      || (key === 'busy' && pick('[data-act=match]')) || pick('[data-act=accept]') || pick('[data-act=match]') || pick('[data-act=amount]') || pick('.ing-menu-btn') || li;
    if (el && !el.disabled) el.focus({ preventScroll: false }); else li.focus();
  }
  function paintRow(id, focusKey) {
    const old = document.getElementById('ing-' + id);
    const item = itemOf(id);
    if (!old || !item) { paint(id, focusKey); return; }
    const had = old.contains(document.activeElement);
    old.replaceWith(rowNode(item));
    if (had || focusKey) focusRow(id, focusKey);
  }
  function paintHead() {
    count.textContent = matchedLine(meal, props);
    show(checks, checkBlock(meal));
    const open = unmatchedIds(meal.items).length;
    tools.hidden = !edit || !open;
    const showPrompt = matchPromptShows(meal, props, { edit, running, acted });
    if (showPrompt) promptText.textContent = matchPromptText(matchPromptCount(meal.items, props));
    prompt.hidden = !showPrompt;
    allBtn.disabled = running;
    const more = tools.querySelector('.split-more');
    if (more) more.disabled = running;
    const pending = pendingProposals(meal.items, props);
    acceptRow.hidden = !edit || !pending.length || running;
    acceptBtn.textContent = acceptAllText(pending.length);
    const before = previousCountText(pending);
    previousNote.textContent = before;
    previousNote.hidden = !before;
  }
  function paintRows() {
    const had = list.contains(document.activeElement) ? document.activeElement.closest('.ing-row') : null;
    clear(list);
    meal.items.forEach((it) => list.appendChild(rowNode(it)));
    paintHead();
    if (had && !list.contains(document.activeElement)) focusRow(Number(had.id.slice(4)));
    if (review) paintReview(false);
  }
  function paint(focusId, focusKey) {
    paintRows();
    if (focusId != null) focusRow(focusId, focusKey);
  }

  // ---------- Add Ingredient ----------
  const addBox = h('div', { class: 'match-add' });
  async function addRow(text, search) {
    const row = parseIngredientLine(text);
    if (!row) { show(status, message('Type the ingredient first.', 'error')); return; }
    try {
      const { added, ...m } = await api.addMealItem(meal.id, { src: { text: row.text.slice(0, 300), amount: row.amount, unit: row.unit, name: row.name.slice(0, 200), note: row.note } });
      setMeal(m);
      show(addBox, null);
      paint(added);
      const item = itemOf(added);
      if (search && item) searchRow(item);
      else say('Added ' + row.text + '. Tap + to match it.');
    } catch (e) { fail(e); }
  }
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

  paintRows();
  const el = h('div', { class: 'ing-section' },
    h('h2', { id: 'ing-head' }, 'Ingredients'), edit ? prompt : null, count, checks,
    edit ? tools : null, edit ? acceptRow : null,
    status, limitNote, reviewBox, list,
    edit ? h('div', { class: 'row wrap' }, addBtn) : null, addBox);
  return { el, focus: (id) => focusRow(id) };
}
