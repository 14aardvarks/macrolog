import { groupByMeal, shownMicros, microValue, fmtNum, roundTo } from './util.js';

export const VIEW_KEY = 'macrolog.todayView';
export const VIEWS = ['list', 'table'];
export const VIEW_LABELS = { list: 'List', table: 'Table' };

// The saved Today view. Anything unknown, or a storage that throws (private mode), gives the list.
export function loadView(storage) {
  try {
    const v = (storage || globalThis.localStorage).getItem(VIEW_KEY);
    return VIEWS.includes(v) ? v : 'list';
  } catch (e) { return 'list'; }
}

export function saveView(view, storage) {
  try { (storage || globalThis.localStorage).setItem(VIEW_KEY, view); } catch (e) { /* not saved, the choice still applies this session */ }
}

const MACRO_COLS = [
  { key: 'kcal', label: 'Calories', unit: '', digits: 0 },
  { key: 'carbs', label: 'Carbs', unit: 'g', digits: 1 },
  { key: 'protein', label: 'Protein', unit: 'g', digits: 1 },
  { key: 'fat', label: 'Fat', unit: 'g', digits: 1 },
];

// Number columns after Food and Amount: the four macros, then the micronutrients the Display settings show.
export function tableColumns(display) {
  return [...MACRO_COLS, ...shownMicros(display).map((m) => ({ key: m.key, label: m.label, unit: m.unit, micro: true }))];
}

export function columnHeader(col) { return col.unit ? col.label + ' (' + col.unit + ')' : col.label; }

// One cell. Macros are always numbers; a micronutrient that is null is a dash.
export function cellText(col, value) {
  return col.micro ? microValue(value, col.unit) : fmtNum(Number(value) || 0, col.digits);
}

// Sum of the known values, or null when none are known (so the cell shows a dash, never a false 0).
export function sumColumn(col, entries) {
  let sum = 0, known = 0;
  for (const e of entries) {
    const v = e[col.key];
    if (v == null || !Number.isFinite(Number(v))) continue;
    sum += Number(v); known += 1;
  }
  if (!known) return col.micro ? null : 0;
  return roundTo(sum, 2);
}

// Model for the table: meal groups with their entries and subtotal cells, plus a totals row.
// Each cell is a display string, so the view only places them.
export function buildTable(entries, display) {
  const cols = tableColumns(display);
  const cells = (list) => cols.map((c) => cellText(c, sumColumn(c, list)));
  const groups = groupByMeal(entries).map((g) => ({
    meal: g.meal, label: g.label, entries: g.entries, subtotal: cells(g.entries),
    rows: g.entries.map((e) => ({ entry: e, cells: cols.map((c) => cellText(c, e[c.key])) })),
  }));
  return { cols, groups, totals: cells(entries || []), count: (entries || []).length };
}
