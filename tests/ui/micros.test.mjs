import test from 'node:test';
import assert from 'node:assert/strict';
import { MICROS, DEFAULT_DISPLAY, shownMicros, microValue, microText, microNote, microOver, toggleMicro } from '../../app/static/js/util.js';

test('micronutrient list matches the server order, units and kinds', () => {
  assert.deepEqual(MICROS.map((m) => m.key), ['fiber', 'sugars', 'saturated_fat', 'sodium', 'cholesterol', 'potassium', 'calcium', 'iron', 'vitamin_d']);
  assert.deepEqual(MICROS.filter((m) => m.kind === 'limit').map((m) => m.key), ['sugars', 'saturated_fat', 'sodium', 'cholesterol']);
  assert.equal(MICROS.find((m) => m.key === 'vitamin_d').unit, 'mcg');
});

test('shownMicros follows the switch and the chosen list, defaults show everything', () => {
  assert.equal(shownMicros(undefined).length, 9);
  assert.equal(shownMicros(DEFAULT_DISPLAY).length, 9);
  assert.deepEqual(shownMicros({ ...DEFAULT_DISPLAY, show_micros: false }), []);
  assert.deepEqual(shownMicros({ ...DEFAULT_DISPLAY, micros_shown: ['iron', 'sodium'] }).map((m) => m.key), ['sodium', 'iron']);
  assert.equal(DEFAULT_DISPLAY.micros_open, false);
});

test('microValue shows a dash for unknown, never 0, and rounds by unit', () => {
  assert.equal(microValue(null, 'mg'), '-');
  assert.equal(microValue(undefined, 'g'), '-');
  assert.equal(microValue(0, 'g'), '0');
  assert.equal(microValue(712.6, 'mg'), '713');
  assert.equal(microValue(1.25, 'g'), '1.3');
  assert.equal(microValue(0.375, 'mcg'), '0.4');
});

test('microText and microNote for Today rows', () => {
  assert.equal(microText({ total: 6.25, target: 28, count: 2 }, 'g'), '6.3 / 28 g');
  assert.equal(microText({ total: null, target: 2300, count: 0 }, 'mg'), '0 / 2300 mg');
  assert.equal(microText({ total: null, target: 2300, count: 3 }, 'mg'), '- / 2300 mg');
  assert.equal(microNote({ known: 2, count: 3 }), '2 of 3 foods');
  assert.equal(microNote({ known: 0, count: 1 }), '0 of 1 food');
  assert.equal(microNote({ known: 3, count: 3 }), '');
  assert.equal(microNote({ known: 0, count: 0 }), '');
});

test('microOver warns only for a passed limit', () => {
  assert.equal(microOver({ kind: 'limit', total: 2400, target: 2300 }), true);
  assert.equal(microOver({ kind: 'limit', total: 2300, target: 2300 }), false);
  assert.equal(microOver({ kind: 'goal', total: 40, target: 28 }), false);
  assert.equal(microOver({ kind: 'limit', total: null, target: 20 }), false);
});

test('toggleMicro keeps the fixed order', () => {
  assert.deepEqual(toggleMicro(['iron'], 'sodium'), ['sodium', 'iron']);
  assert.deepEqual(toggleMicro(['sodium', 'iron'], 'iron'), ['sodium']);
  assert.deepEqual(toggleMicro(undefined, 'fiber'), ['fiber']);
});
