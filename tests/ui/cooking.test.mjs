import test from 'node:test';
import assert from 'node:assert/strict';
import { cookBase, cookStep, cookServingsNext, cookIngredient, cookIngredients, cookSteps, cookToggle, setAmountFormat } from '../../app/static/js/util.js';
import { keepAwake } from '../../app/static/js/cooking.js';

const meal = {
  servings: 4, steps: ['Boil water.', 'Add the rice and simmer for 15 minutes'],
  items: [
    { src: { text: '1 1/2 cups long grain rice, rinsed', amount: 1.5, unit: 'cups', name: 'long grain rice', note: 'rinsed' }, food: { name: 'Rice, white' }, amount: 1, unit: 'cup' },
    { src: { text: 'salt to taste', amount: null, unit: null, name: 'salt', note: null }, food: null, amount: null, unit: null },
    { src: null, food: { name: 'Olive Oil' }, amount: 2, unit: 'tbsp' },
    { src: { text: '3 eggs', amount: 3, unit: '', name: 'eggs', note: '' }, food: null, skipped: true },
  ],
};

test('base servings and the step size', () => {
  assert.equal(cookBase(meal), 4);
  assert.equal(cookBase({}), 1);
  assert.equal(cookBase({ servings: 0 }), 1);
  assert.equal(cookStep(2), 0.5);
  assert.equal(cookStep(4), 1);
});

test('servings move by a step and stay in range', () => {
  assert.equal(cookServingsNext(4, 4, 1), 5);
  assert.equal(cookServingsNext(1, 4, -1), 1);
  assert.equal(cookServingsNext(1, 1, 1), 1.5);
  assert.equal(cookServingsNext(0.5, 1, -1), 0.5);
  assert.equal(cookServingsNext(1000, 4, 1), 1000);
});

test('ingredients keep the recipe wording and scale with the servings shown', () => {
  setAmountFormat('fraction');
  assert.deepEqual(cookIngredients(meal, 4).map((i) => i.text), ['1 1/2 cups long grain rice, rinsed', 'salt to taste', '2 tbsp Olive Oil', '3 eggs']);
  assert.deepEqual(cookIngredients(meal, 8).map((i) => i.text), ['3 cups long grain rice, rinsed', 'salt to taste', '4 tbsp Olive Oil', '6 eggs']);
  assert.equal(cookIngredients(meal, 2)[0].text, '3/4 cups long grain rice, rinsed');
  assert.equal(cookIngredients(meal, 4)[1].scaled, false);
  assert.equal(cookIngredients(meal, 4)[0].scaled, true);
  assert.equal(cookIngredients(meal, 4).length, 4);
});

test('amounts follow the fraction or decimal setting', () => {
  setAmountFormat('decimal');
  assert.equal(cookIngredient(meal.items[0], 1).text, '1.5 cups long grain rice, rinsed');
  setAmountFormat('fraction');
  assert.equal(cookIngredient({ src: { amount: 250, unit: 'g', name: 'flour' } }, 1.5).text, '375 g flour');
});

test('a row with nothing to show still reads', () => {
  assert.equal(cookIngredient({}, 1).text, 'Ingredient');
  assert.equal(cookIngredient({ food: { name: 'Egg' }, amount: 2, unit: 'serving' }, 1).text, '2 Egg');
});

test('steps and ticking', () => {
  assert.deepEqual(cookSteps(meal).map((s) => s.key), ['s0', 's1']);
  assert.deepEqual(cookSteps({}), []);
  const a = new Set();
  const b = cookToggle(a, 'i0');
  assert.equal(a.size, 0);
  assert.ok(b.has('i0'));
  assert.ok(!cookToggle(b, 'i0').has('i0'));
});

function fakeDoc() {
  const l = {};
  return { visibilityState: 'visible', addEventListener: (n, f) => { l[n] = f; }, removeEventListener: (n) => { delete l[n]; }, l };
}

test('keepAwake does nothing without the Wake Lock API', () => {
  const doc = fakeDoc();
  const stop = keepAwake({}, doc);
  assert.equal(typeof stop, 'function');
  assert.deepEqual(doc.l, {});
  stop();
});

test('keepAwake asks again when the page returns, releases on stop and ignores errors', async () => {
  const doc = fakeDoc();
  let asked = 0; let released = 0;
  const nav = { wakeLock: { request: async (k) => { asked++; assert.equal(k, 'screen'); return { release: async () => { released++; } }; } } };
  const stop = keepAwake(nav, doc);
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(asked, 1);
  doc.l.visibilitychange();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(asked, 2);
  stop();
  assert.equal(released, 1);
  assert.deepEqual(doc.l, {});
  const bad = keepAwake({ wakeLock: { request: async () => { throw new Error('denied'); } } }, fakeDoc());
  await new Promise((r) => setTimeout(r, 0));
  bad();
});
