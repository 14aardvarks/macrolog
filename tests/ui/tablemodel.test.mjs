import test from 'node:test';
import assert from 'node:assert/strict';
import { VIEW_KEY, loadView, saveView, tableColumns, columnHeader, cellText, sumColumn, buildTable } from '../../app/static/js/tablemodel.js';
import { DEFAULT_DISPLAY } from '../../app/static/js/util.js';

const store = (init = {}) => ({ data: { ...init }, getItem(k) { return k in this.data ? this.data[k] : null; }, setItem(k, v) { this.data[k] = String(v); } });
const throwing = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };

test('view choice defaults to list, round trips, and survives broken storage', () => {
  assert.equal(loadView(store()), 'list');
  assert.equal(loadView(store({ [VIEW_KEY]: 'bogus' })), 'list');
  const s = store();
  saveView('table', s);
  assert.equal(loadView(s), 'table');
  assert.equal(loadView(throwing), 'list');
  assert.doesNotThrow(() => saveView('table', throwing));
});

test('columns are the four macros plus the micronutrients that are shown', () => {
  assert.deepEqual(tableColumns(DEFAULT_DISPLAY).map((c) => c.key),
    ['kcal', 'carbs', 'protein', 'fat', 'fiber', 'sugars', 'saturated_fat', 'sodium', 'cholesterol', 'potassium', 'calcium', 'iron', 'vitamin_d']);
  assert.deepEqual(tableColumns({ ...DEFAULT_DISPLAY, micros_shown: ['iron', 'sodium'] }).map((c) => c.key), ['kcal', 'carbs', 'protein', 'fat', 'sodium', 'iron']);
  assert.deepEqual(tableColumns({ ...DEFAULT_DISPLAY, show_micros: false }).map((c) => c.key), ['kcal', 'carbs', 'protein', 'fat']);
  assert.equal(columnHeader({ label: 'Sodium', unit: 'mg' }), 'Sodium (mg)');
  assert.equal(columnHeader({ label: 'Calories', unit: '' }), 'Calories');
});

test('unknown micronutrients are a dash, zero stays zero', () => {
  const sodium = tableColumns(DEFAULT_DISPLAY).find((c) => c.key === 'sodium');
  assert.equal(cellText(sodium, null), '-');
  assert.equal(cellText(sodium, 0), '0');
  assert.equal(cellText(sodium, 1700.4), '1700');
  assert.equal(cellText({ key: 'kcal', digits: 0 }, 160.4), '160');
});

test('sums use known values only and stay unknown when none are known', () => {
  const fiber = { key: 'fiber', micro: true };
  assert.equal(sumColumn(fiber, [{ fiber: 4 }, { fiber: null }, { fiber: 1.5 }]), 5.5);
  assert.equal(sumColumn(fiber, [{ fiber: null }]), null);
  assert.equal(sumColumn({ key: 'kcal' }, []), 0);
});

test('buildTable groups by meal with subtotals and a totals row', () => {
  const entries = [
    { id: 1, meal: 'snack', name: 'Chips', kcal: 320, carbs: 30, protein: 4, fat: 20, fiber: 2, sodium: 3400 },
    { id: 2, meal: 'breakfast', name: 'Oats', kcal: 166, carbs: 28, protein: 6, fat: 3.6, fiber: 4, sodium: 9 },
    { id: 3, meal: 'breakfast', name: 'Banana', kcal: 105, carbs: 27, protein: 1.3, fat: 0.4, fiber: null, sodium: null },
  ];
  const t = buildTable(entries, { ...DEFAULT_DISPLAY, micros_shown: ['fiber', 'sodium', 'iron'] });
  assert.deepEqual(t.cols.map((c) => c.key), ['kcal', 'carbs', 'protein', 'fat', 'fiber', 'sodium', 'iron']);
  assert.deepEqual(t.groups.map((g) => g.label), ['Breakfast', 'Snack']);
  assert.deepEqual(t.groups[0].subtotal, ['271', '55', '7.3', '4', '4', '9', '-']);
  assert.deepEqual(t.groups[0].rows[1].cells, ['105', '27', '1.3', '0.4', '-', '-', '-']);
  assert.deepEqual(t.totals, ['591', '85', '11.3', '24', '6', '3409', '-']);
  assert.equal(t.count, 3);
});

test('buildTable handles an empty day', () => {
  const t = buildTable([], DEFAULT_DISPLAY);
  assert.equal(t.groups.length, 0);
  assert.equal(t.totals[0], '0');
  assert.equal(t.totals[4], '-');
});
