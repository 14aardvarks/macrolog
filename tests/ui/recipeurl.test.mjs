import test from 'node:test';
import assert from 'node:assert/strict';
import { urlCheck, urlImportOn, recipeUrlCostLine, sourceLink, URL_TEXT, URL_MAX, importWhat, reviewDraft, reviewBody } from '../../app/static/js/recipeimport.js';
import { noticeLines, sentence } from '../../app/static/js/util.js';

test('urlCheck mirrors the server: http or https with a host, no credentials, no spaces or control characters, length cap', () => {
  assert.deepEqual(urlCheck('  https://example.com/pancakes?x=1#top '), { url: 'https://example.com/pancakes?x=1#top' });
  assert.deepEqual(urlCheck('HTTP://Example.com'), { url: 'HTTP://Example.com' });
  assert.deepEqual(urlCheck('https://example.com:8080/a'), { url: 'https://example.com:8080/a' });
  const bad = ['', '   ', 'example.com/r', 'ftp://example.com', 'javascript:alert(1)', 'file:///etc/passwd', 'https://', 'https://:80/',
    'https://user:pw@example.com', 'https://user@example.com', 'https://example.com/a b', 'https://example.com/\u0000',
    'https://example.com/\u007f', 'https://example.com/<x>', 'https://example.com/' + 'a'.repeat(URL_MAX)];
  for (const b of bad) assert.ok(urlCheck(b).error, JSON.stringify(b));
  assert.ok(urlCheck(null).error);
  const long = 'https://example.com/' + 'a'.repeat(URL_MAX - 20);
  assert.equal(long.length, URL_MAX);
  assert.deepEqual(urlCheck(long), { url: long });
  assert.match(urlCheck('https://u:p@x.org').error, /user name or password/);
  for (const b of bad) assert.equal(sentence(urlCheck(b).error), urlCheck(b).error);
});

test('urlImportOn needs Claude for the user, recipe import and the URL switch', () => {
  assert.equal(urlImportOn({ enabled: true, features: { recipe: true, recipe_url: true } }), true);
  assert.equal(urlImportOn({ enabled: true, features: { recipe: true, recipe_url: false } }), false);
  assert.equal(urlImportOn({ enabled: true, features: { recipe: true } }), false);  // off unless the server says on
  assert.equal(urlImportOn({ enabled: true, features: { recipe: false, recipe_url: true } }), false);
  assert.equal(urlImportOn({ enabled: false, features: { recipe: true, recipe_url: true } }), false);
  assert.equal(urlImportOn(null), false);
});

test('the cost notice for a URL import says it is an upper estimate', () => {
  const r = noticeLines({ cap: 100, remaining: 40, est_cost_label: 0.0035, est_upper: true }, importWhat('url'));
  assert.equal(r.lines[0], 'Sends a web address to Claude.');
  assert.equal(r.lines[2], 'Estimated cost up to about 0.35 cents. This is an upper estimate, for a page at the size limit.');
  assert.equal(noticeLines({ cap: 100, remaining: 40, est_cost_label: 0.0035 }, 'x').lines[2], 'Estimated cost about 0.35 cents.');
  assert.equal(noticeLines({ cap: 100, remaining: 40, est_cost_label: null, est_upper: true }, 'x').lines[2], 'Cost not available.');
  for (const t of r.lines) assert.ok(!/—|–/.test(t));
});

test('Full Claude Use line for URL import states the upper cost and requests left', () => {
  const st = { remaining: 7, cap: 100, action_costs: { recipe_url: 0.0035, sample: true } };
  assert.equal(recipeUrlCostLine(st), 'Full Claude Use is on, so Read With Claude sends the address at once. '
    + 'Up to about 0.35 cents per import at sample prices, an upper estimate. 7 of 100 Claude requests left this month.');
  assert.equal(recipeUrlCostLine({ remaining: 1, cap: 5, action_costs: {} }), 'Full Claude Use is on, so Read With Claude sends the address at once. 1 of 5 Claude requests left this month.');
});

test('sourceLink renders only http and https addresses, named by their site', () => {
  assert.deepEqual(sourceLink('https://www.example.com/pancakes'), { href: 'https://www.example.com/pancakes', text: 'example.com' });
  assert.deepEqual(sourceLink('http://blog.example.org/a?b=1'), { href: 'http://blog.example.org/a?b=1', text: 'blog.example.org' });
  for (const u of [null, '', 'javascript:alert(1)', 'data:text/html,x', 'ftp://example.com', '//example.com', 'https://']) assert.equal(sourceLink(u), null, String(u));
});

test('the review draft keeps the source address and the save body sends it', () => {
  const recipe = { name: 'Pancakes', servings: 4, ingredients: [{ text: '1 cup flour', amount: 1, unit: 'cup', name: 'flour', note: null }], steps: [], source_url: 'https://example.com/p' };
  const d = reviewDraft(recipe, { warnings: [] });
  assert.equal(d.sourceUrl, 'https://example.com/p');
  assert.equal(reviewBody(d).body.source_url, 'https://example.com/p');
  const plain = reviewDraft({ ...recipe, source_url: undefined });
  assert.equal(plain.sourceUrl, null);
  assert.ok(!('source_url' in reviewBody(plain).body));
});

test('URL help text is a sentence without em dashes', () => {
  assert.equal(sentence(URL_TEXT), URL_TEXT);
  assert.ok(!/—|–/.test(URL_TEXT));
  assert.match(URL_TEXT, /never through this server/);
});
