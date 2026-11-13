// Issue #45 steps 1 to 3: counts never become label servings, package and fuzzy units stay units, printed sizes are exact,
// and every amount to check says why.
import test from 'node:test';
import assert from 'node:assert/strict';
import { matchAmount, printedSize, sizeText, unitWord, amountText, ingredientText, cookIngredient, canonUnit, unitToSave, checkReasonText,
  checkReasonLine, checkNameLine, checkList, checkSummary, COUNTISH, PACKAGE_UNITS, FUZZY_UNITS } from '../../app/static/js/util.js';
import { parseIngredientLine, parseIngredientText, reviewDraft, reviewBody, reviewFlag, pkgNote, useGrams, rowPkg, rowText, IMPORT_UNITS,
  blankRow } from '../../app/static/js/recipeimport.js';

const u = (unit, d, estimated) => ({ unit, default_amount: d, ...(estimated ? { estimated: true } : {}) });
const GARLIC_G = [u('g', 100), u('serving', 1), u('pct', 100), u('oz', 3.53), u('cup', 0.42, true)];
const GARLIC_CLOVE = [u('clove', 1), u('serving', 1), u('pct', 100), u('g', 3), u('count', 1)];
const BEANS = [u('g', 100), u('serving', 1), u('pct', 100), u('oz', 3.53), u('lb', 0.22)];
const SLICE_ONLY = [u('slice', 2), u('serving', 1), u('pct', 100), u('count', 1)];

test('step 1: a count on a gram label is Check Amount, never label servings', () => {
  const nw = { amount: 100, unit: 'g', check: true, reason: 'no_weight' };
  for (const unit of ['cloves', '', null, 'count', 'piece', 'Head', 'shell']) assert.deepEqual(matchAmount(GARLIC_G, 2, unit), nw, String(unit));
  assert.deepEqual(matchAmount(GARLIC_G, 1, 'can'), { ...nw, reason: 'no_size' });
  assert.deepEqual(matchAmount(GARLIC_G, 20, 'g'), { amount: 20, unit: 'g', check: false });
  assert.deepEqual(matchAmount(GARLIC_G, 1, 'cup'), { amount: 1, unit: 'cup', check: false, estimated: true });
});

test('step 1: a count with a known weight converts exactly', () => {
  assert.deepEqual(matchAmount(GARLIC_CLOVE, 2, 'cloves'), { amount: 2, unit: 'clove', check: false });
  assert.deepEqual(matchAmount(GARLIC_CLOVE, 2, null), { amount: 2, unit: 'clove', check: false });
  assert.equal(matchAmount(GARLIC_CLOVE, 1, 'head').reason, 'no_weight');
  assert.equal(matchAmount(GARLIC_CLOVE, 1, 'jar').reason, 'no_size');
});

test('step 2: package and fuzzy units are known, canonical and pluralized', () => {
  assert.equal(COUNTISH.length, PACKAGE_UNITS.length + FUZZY_UNITS.length);
  for (const [t, want] of [['Cloves', 'clove'], ['boxes', 'box'], ['bunches', 'bunch'], ['pkg', 'package'], ['Sticks', 'stick'], ['fillets', 'fillet'], ['ribs', 'rib']]) {
    assert.equal(canonUnit(t), want, t);
    assert.equal(unitToSave(t), want, t);
  }
  for (const [unit, n, want] of [['clove', 2, 'cloves'], ['clove', 1, 'clove'], ['clove', 0.5, 'clove'], ['pinch', 3, 'pinches'], ['box', 2, 'boxes'],
    ['dash', 2, 'dashes'], ['can', 1.5, 'cans'], ['cup', 2, 'cup'], ['floz', 2, 'fl oz'], ['Shell', 2, 'Shell']]) assert.equal(unitWord(unit, n), want, unit + n);
  assert.equal(amountText(2, 'clove'), '2 cloves');
  assert.equal(ingredientText(2, 'clove', 'garlic'), '2 cloves garlic');
  assert.equal(cookIngredient({ src: { amount: 1, unit: 'clove', name: 'garlic', note: 'minced' } }, 2).text, '2 cloves garlic, minced');
  for (const w of [...PACKAGE_UNITS, ...FUZZY_UNITS]) assert.ok(IMPORT_UNITS.some(([v]) => v === w), w);
});

test('step 2: the local splitter keeps units structured and the name clean', () => {
  const r = parseIngredientLine('2 cloves garlic, minced');
  assert.deepEqual([r.amount, r.unit, r.name, r.note], [2, 'clove', 'garlic', 'minced']);
  assert.equal(r.pkg_amount, undefined);
  assert.equal(rowText(reviewDraft({ ingredients: [r] }).rows[0]), '2 cloves garlic, minced');
});

test('step 3: printed sizes', () => {
  const cases = [
    ['1 (15 oz) can black beans', [1, 'can', 15, 'oz', 'black beans']],
    ['2 (8-ounce) packages cream cheese', [2, 'package', 8, 'oz', 'cream cheese']],
    ['1 stick (113 g) butter', [1, 'stick', 113, 'g', 'butter']],
    ['1 can (14.5 oz) diced tomatoes', [1, 'can', 14.5, 'oz', 'diced tomatoes']],
    ['1 15-oz can chickpeas', [1, 'can', 15, 'oz', 'chickpeas']],
    ['2 (12 fl oz) bottles beer', [2, 'bottle', 12, 'floz', 'beer']],
    ['1 1/2 (1 lb) bags spinach', [1.5, 'bag', 1, 'lb', 'spinach']],
  ];
  for (const [t, want] of cases) {
    const p = printedSize(t);
    assert.deepEqual([p.amount, p.unit, p.size, p.sizeUnit, p.rest], want, t);
  }
  for (const t of ['1 (14 to 15 oz) can beans', '1 (14-15 oz) can beans', '1 (oz) can beans', '2 cans beans', '1 cup (240 ml) milk', '', null]) {
    assert.equal(printedSize(t), null, String(t));
  }
  assert.equal(sizeText(12, 'floz'), '12 fl oz');
});

test('step 3: a printed size row goes through review and into the import body', () => {
  const r = parseIngredientLine('1 (15 oz) can black beans, rinsed');
  assert.deepEqual(r, { text: '1 (15 oz) can black beans, rinsed', amount: 1, unit: 'can', name: 'black beans', note: '15 oz, rinsed', pkg_amount: 15, pkg_unit: 'oz' });
  const d = reviewDraft({ name: 'Chili', ingredients: [r, parseIngredientLine('1 can corn')] });
  assert.equal(pkgNote(d.rows[0]), '15 oz per can, exact');
  assert.equal(reviewFlag(d.rows[0]), '');
  const b = reviewBody(d).body.ingredients;
  assert.deepEqual(b.map((i) => [i.amount, i.unit, i.pkg_amount, i.pkg_unit]), [[1, 'can', 15, 'oz'], [1, 'can', null, null]]);
  d.rows[0].unit = 'cup';  // another unit drops the size
  assert.equal(rowPkg(d.rows[0]), null);
  assert.equal(reviewBody(d).body.ingredients[0].pkg_amount, null);
});

test('step 3: matchAmount uses the printed size once', () => {
  assert.deepEqual(matchAmount(BEANS, 1, 'can', { amount: 15, unit: 'oz' }), { amount: 15, unit: 'oz', check: false });
  assert.deepEqual(matchAmount(BEANS, 2, 'package', { amount: 8, unit: 'ounces' }), { amount: 16, unit: 'oz', check: false });
  assert.equal(matchAmount(BEANS, 1, 'can', { amount: null, unit: null }).reason, 'no_size');
  assert.equal(matchAmount(SLICE_ONLY, 1, 'can', { amount: 15, unit: 'oz' }).reason, 'no_convert');
  const canFood = [u('can', 1), u('serving', 1), u('g', 425), u('oz', 15)];
  assert.deepEqual(matchAmount(canFood, 1, 'can', { amount: 15, unit: 'oz' }), { amount: 15, unit: 'oz', check: false });  // never can x size
});

test('review flags a package or fuzzy unit without a printed size, and Use Grams clears it', () => {
  const rows = parseIngredientText('2 cloves garlic\n1 can corn\n3 carrots\n1 cup flour\nsalt to taste').ingredients;
  const d = reviewDraft({ ingredients: rows });
  assert.deepEqual(d.rows.map(reviewFlag), ['No standard weight for clove, enter grams', 'Can size not printed, pick a size or enter grams', '', '', '']);
  useGrams(d.rows[0]);
  assert.deepEqual([d.rows[0].unit, d.rows[0].amount, reviewFlag(d.rows[0])], ['g', '', '']);
  assert.equal(reviewFlag({ ...blankRow(), amount: '1', unit: 'piece' }), '');  // a plain count word
});

test('each check reason has its own words', () => {
  assert.equal(checkReasonText('no_weight', 'clove'), 'no standard weight for clove, enter grams');
  assert.equal(checkReasonText('no_size', 'can'), 'can size not printed, pick a size or enter grams');
  assert.equal(checkReasonText('no_convert', 'cup'), 'no cup weight for this food');
  assert.equal(checkReasonText('no_convert', 'floz'), 'no fl oz weight for this food');
  assert.equal(checkReasonText('no_amount', null), 'amount missing, enter one');
  assert.equal(checkReasonText('estimated', 'cup', 'density'), 'estimated from a typical weight, source a typical density for this food');
  assert.equal(checkReasonText('estimated', 'cup', 'guess'), 'estimated from a typical weight, source 1 g per ml, no density known');
  assert.equal(checkReasonText('estimated', 'g', 'claude'), 'estimated from a typical weight, source Claude');
  assert.equal(checkReasonText(null, 'cup'), 'amount could not be worked out, enter one');
  assert.equal(checkReasonLine('no_weight', 'clove'), 'No standard weight for clove, enter grams');
  assert.equal(checkNameLine('garlic', 'no_weight', 'clove'), 'Garlic: no standard weight for clove, enter grams');
  assert.equal(checkNameLine('Black beans', 'no_size', 'can'), 'Black beans: can size not printed, pick a size or enter grams');
  assert.equal(checkNameLine('flour', 'no_convert', 'cup'), 'Flour: no cup weight for this food');
});

test('the recipe header lists each check with its reason, estimates after', () => {
  const it = (id, src, extra) => ({ id, src, food: { name: 'F' }, unit: 'g', check: false, skipped: false, ...extra });
  const meal = { items: [
    it(1, { name: 'garlic', unit: 'clove' }, { check: true, check_reason: 'no_weight' }),
    it(2, { name: 'black beans', unit: 'can' }, { check: true, check_reason: 'no_size' }),
    it(3, { name: 'flour', unit: 'cup' }, { estimated: true, estimate_source: 'density' }),
    it(4, { name: 'salt', unit: 'pinch' }, { check: true, check_reason: 'no_weight', skipped: true }),
    it(5, { name: 'rice', unit: 'g' })] };
  const list = checkList(meal);
  assert.deepEqual(list.map((x) => [x.id, x.check, x.text]), [
    [1, true, 'Garlic: no standard weight for clove, enter grams'],
    [2, true, 'Black beans: can size not printed, pick a size or enter grams'],
    [3, false, 'Flour: estimated from a typical weight, source a typical density for this food']]);
  assert.equal(checkSummary(list), '2 ingredients need a check');
  assert.equal(checkSummary(list.slice(0, 1)), '1 ingredient needs a check');
  assert.equal(checkSummary(list.slice(2)), '1 amount is estimated');
  assert.equal(checkSummary([]), '');
});
