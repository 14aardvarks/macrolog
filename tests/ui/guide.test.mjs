import test from 'node:test';
import assert from 'node:assert/strict';
import { GUIDE, GUIDE_TITLE } from '../../app/static/js/guide.js';
import { startPreset, sentence } from '../../app/static/js/util.js';

test('guide has a title, headings and no empty or dashed bullets', () => {
  assert.equal(GUIDE_TITLE, 'How to Use Macrolog');
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

const SMALL = new Set(['a', 'an', 'and', 'of', 'to', 'in', 'on', 'or', 'the']);
function isTitleCase(t) {
  return t.split(' ').every((w, i) => {
    const bare = w.replace(/^[("]+/, '');
    return i > 0 && SMALL.has(bare) ? true : /^[A-Z0-9]/.test(bare);
  });
}

test('guide headings are Title Case and every bullet ends with a period', () => {
  assert.ok(isTitleCase(GUIDE_TITLE));
  for (const g of GUIDE) {
    assert.ok(isTitleCase(g.heading), g.heading);
    for (const b of g.bullets) assert.match(b, /[.?!]$/, b);
  }
});

test('sentence adds a period to real sentences only', () => {
  assert.equal(sentence('Open Food Facts has no nutrition data for this product'), 'Open Food Facts has no nutrition data for this product.');
  assert.equal(sentence('Already done.'), 'Already done.');
  assert.equal(sentence('Is it ok?'), 'Is it ok?');
  assert.equal(sentence('Searching...'), 'Searching...');
  assert.equal(sentence('Not found'), 'Not found');
  assert.equal(sentence(null), '');
});

test('Your Claude Key bullets explain the price unit and sample, each at most 16 words', () => {
  const g = GUIDE.find((x) => x.heading === 'Your Claude Key');
  assert.ok(g.bullets.some((b) => /USD per million tokens/.test(b) && /no cost is shown/.test(b)));
  assert.ok(g.bullets.some((b) => /0\.10/.test(b) && /0\.50/.test(b)));
  for (const b of g.bullets) assert.ok(b.split(/\s+/).length <= 16, b);
});
