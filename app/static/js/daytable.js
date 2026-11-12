import { h, sourceBadge } from './dom.js';
import { buildTable, columnHeader, VIEWS, VIEW_LABELS } from './tablemodel.js';
import { isRecipeLog, entryAmountText } from './recipeimport.js';
import { entryKey } from './util.js';

// The List and Table buttons above the day's entries. onPick(view) runs after a tap.
export function viewToggle(current, onPick) {
  const btns = VIEWS.map((v) => h('button', { class: 'chip', type: 'button', 'aria-pressed': v === current ? 'true' : 'false', onclick: () => {
    btns.forEach((b, i) => b.setAttribute('aria-pressed', VIEWS[i] === v ? 'true' : 'false'));
    onPick(v);
  } }, VIEW_LABELS[v]));
  return h('div', { class: 'chips view-toggle', role: 'group', 'aria-label': 'Entries view' }, btns);
}

// The day's entries as a table. opts: { display, onOpen(entry), onDelete(entry) }. The Food column stays pinned when it scrolls.
export function dayTable(entries, opts) {
  const t = buildTable(entries, opts.display);
  const head = h('tr', null, h('th', { scope: 'col', class: 'food-col' }, 'Food'), h('th', { scope: 'col', class: 'amt-col' }, 'Amount'),
    t.cols.map((c) => h('th', { scope: 'col', class: 'num', 'aria-label': columnHeader(c) }, c.label, c.unit ? h('span', { class: 'th-unit' }, ' (' + c.unit.replace(/^\(|\)$/g, '') + ')') : null)), h('th', { scope: 'col', class: 'del-col' }, h('span', { class: 'sr-only' }, 'Remove')));
  const rows = [];
  for (const g of t.groups) {
    rows.push(h('tr', { class: 'meal-row' }, h('th', { scope: 'row', class: 'food-col' }, g.label), h('td', { class: 'amt-col' }, 'Subtotal'),
      g.subtotal.map((s) => h('td', { class: 'num' }, s)), h('td', { class: 'del-col' })));
    g.rows.forEach((r) => {
      const e = r.entry;
      const name = e.brand ? e.name + ' (' + e.brand + ')' : e.name;
      const recipe = isRecipeLog(e);  // a logged recipe is one row with the combined values of its ingredients
      const food = e.food_id == null && !recipe ? h('span', null, name)
        : h('button', { class: 'food-link', type: 'button', onclick: () => opts.onOpen(e) }, name);
      const src = recipe ? h('span', { class: 'src-wrap' }, h('span', { class: 'src src-recipe' }, 'Recipe')) : sourceBadge(e.source, true);
      rows.push(h('tr', null, h('th', { scope: 'row', class: 'food-col' }, food, src ? h('div', { class: 'src-sub' }, src) : null), h('td', { class: 'amt-col' }, entryAmountText(e)),
        r.cells.map((s) => h('td', { class: 'num' }, s)),
        h('td', { class: 'del-col' }, h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove ' + e.name, 'data-row': entryKey(e), onclick: () => opts.onDelete(e) }, '×'))));
    });
  }
  rows.push(h('tr', { class: 'total-row' }, h('th', { scope: 'row', class: 'food-col' }, 'Total'), h('td', { class: 'amt-col' }),
    t.totals.map((s) => h('td', { class: 'num' }, s)), h('td', { class: 'del-col' })));
  return h('div', { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Entries table' },
    h('table', { class: 'day-table' }, h('thead', null, head), h('tbody', null, rows)));
}
