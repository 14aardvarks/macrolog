import test from 'node:test';
import assert from 'node:assert/strict';
import { GUIDE, GUIDE_TITLE } from '../../app/static/js/guide.js';
import { startPreset } from '../../app/static/js/util.js';

test('guide has a title, headings and no empty or dashed bullets', () => {
  assert.equal(GUIDE_TITLE, 'How to use Macrolog');
  assert.ok(GUIDE.length >= 9);
  for (const g of GUIDE) {
    assert.ok(g.heading.trim());
    assert.ok(g.bullets.length > 0, g.heading);
    for (const b of g.bullets) {
      assert.equal(typeof b, 'string');
      assert.ok(b.trim().length > 0, 'empty bullet under ' + g.heading);
      assert.ok(!b.includes('—'), 'em dash: ' + b);
      assert.ok(b.split(/\s+/).length <= 16, 'too long: ' + b);
    }
  }
});

test('startPreset: edit keeps its own, use last off ignores carried and last amounts', () => {
  const food = { last: { amount: 6, unit: 'oz' } };
  const carried = { amount: 3, unit: 'oz' };
  assert.equal(startPreset(true, carried, food, false), carried);
  assert.equal(startPreset(false, carried, food, true), carried);
  assert.equal(startPreset(false, {}, food, true), food.last);
  assert.equal(startPreset(false, carried, food, false), null);
  assert.equal(startPreset(false, {}, food, undefined), food.last);
});
