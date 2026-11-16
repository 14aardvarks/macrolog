import test from 'node:test';
import assert from 'node:assert/strict';
import { recipeSummary, ingredientCount, cardChips, cardLabel, placeholderTone, cardGridClass, cardMenuItems, menuLabel, menuMove,
  photoLinkCheck, linkPhotoSrc, recipePhotoSrc, photoMenuItems, photoButtonLabel, photoPromptText, PHOTO_LINK_MAX }
  from '../../app/static/js/recipecards.js';

const base = { id: 1, name: 'Pancakes', servings: 4, per_serving: { kcal: 520.4, protein: 31.6, carbs: 60, fat: 18 },
  items: [{}, {}, {}], needed: 3, matched: 3, skipped: 0, complete: true, meals: ['dinner', 'breakfast'], mine: true, shared: false, can_edit: true };

test('summary line has servings, per serving kcal and protein and the ingredient count', () => {
  assert.equal(recipeSummary(base), '4 servings · 520 kcal · 32 g protein · 3 ingredients');
  assert.equal(recipeSummary({ ...base, servings: 1, items: [{}] }), '1 serving · 520 kcal · 32 g protein · 1 ingredient');
});

test('summary leaves out unknown per serving numbers and treats no servings as one', () => {
  assert.equal(recipeSummary({ items: [], per_serving: { kcal: null } }), '1 serving · 0 ingredients');
  assert.equal(recipeSummary(null), '1 serving · 0 ingredients');
  assert.equal(recipeSummary({ ...base, per_serving: { kcal: 100 } }), '4 servings · 100 kcal · 3 ingredients');
});

test('ingredient count falls back to needed plus skipped', () => {
  assert.equal(ingredientCount({ needed: 5, skipped: 2 }), 7);
  assert.equal(ingredientCount({}), 0);
});

test('chips: meal tags in meal order, then owner, then partial', () => {
  assert.deepEqual(cardChips(base), [{ kind: 'breakfast', label: 'Breakfast' }, { kind: 'dinner', label: 'Dinner' }]);
  const theirs = { ...base, meals: [], mine: false, shared: true, owner: { name: 'Ann' }, complete: false, matched: 2, needed: 3 };
  assert.deepEqual(cardChips(theirs), [{ kind: 'owner', label: 'Shared by Ann' }, { kind: 'partial', label: '2 of 3 matched' }]);
  assert.deepEqual(cardChips({ ...base, meals: [], shared: true }), [{ kind: 'owner', label: 'Shared' }]);
  assert.deepEqual(cardChips({ meals: ['brunch'] }), []);
});

test('card label names the title, summary and chips', () => {
  assert.equal(cardLabel(base), 'Pancakes, 4 servings · 520 kcal · 32 g protein · 3 ingredients, Breakfast, Dinner');
});

test('placeholder tone is the first meal in meal order, else the accent', () => {
  assert.equal(placeholderTone(base), 'breakfast');
  assert.equal(placeholderTone({ meals: ['dessert', 'snack'] }), 'snack');
  assert.equal(placeholderTone({ meals: [] }), 'accent');
  assert.equal(placeholderTone(null), 'accent');
});

test('grid class is compact when photos are off', () => {
  assert.equal(cardGridClass(true), 'card-grid');
  assert.equal(cardGridClass(false), 'card-grid compact');
});

test('menu items follow edit rights and the photo switch', () => {
  const keys = (m, on) => cardMenuItems(m, on).map((i) => i.key);
  assert.deepEqual(keys(base, true), ['log', 'cooking', 'photo-upload', 'photo-take', 'photo-link', 'duplicate', 'delete']);
  assert.deepEqual(keys(base, false), ['log', 'cooking', 'photo-link', 'duplicate', 'delete']);  // a link needs no Allow Photos
  assert.deepEqual(keys({ ...base, can_edit: false }, true), ['log', 'cooking', 'duplicate']);
  assert.deepEqual(keys({ ...base, photo: 'abcdefghijklmnop.jpg' }, true), ['log', 'cooking', 'photo-upload', 'photo-take', 'photo-link', 'photo-remove', 'duplicate', 'delete']);
  assert.deepEqual(keys({ ...base, photo_url: 'https://a.com/x.jpg' }, false), ['log', 'cooking', 'photo-link', 'photo-remove', 'duplicate', 'delete']);
  assert.deepEqual(keys({ ...base, photo: 'abcdefghijklmnop.jpg' }, false), ['log', 'cooking', 'photo-link', 'duplicate', 'delete']);  // a stored upload is not removable while photos are off
  assert.equal(menuLabel(base), 'More Actions for Pancakes');
});

test('photo menu labels', () => {
  assert.deepEqual(photoMenuItems(base, true).map((i) => i.label), ['Upload Photo', 'Take Photo', 'Paste Image Link']);
  assert.deepEqual(photoMenuItems({ photo_url: 'https://a.com/x.jpg' }, true).map((i) => i.label), ['Upload Photo', 'Take Photo', 'Paste Image Link', 'Remove Photo']);
  assert.equal(photoMenuItems({ photo_url: 'https://a.com/x.jpg' }, true).pop().danger, true);
  assert.deepEqual(photoMenuItems(null, false).map((i) => i.key), ['photo-link']);
});

test('image link check: http and https only, no credentials, no spaces, bounded', () => {
  assert.deepEqual(photoLinkCheck(' https://a.com/x.jpg '), { url: 'https://a.com/x.jpg' });
  assert.deepEqual(photoLinkCheck('http://a.com:8080/p?q=1#f'), { url: 'http://a.com:8080/p?q=1#f' });
  assert.deepEqual(photoLinkCheck(''), { url: null });
  assert.deepEqual(photoLinkCheck(null), { url: null });
  for (const bad of ['ftp://a.com/x', 'javascript:alert(1)', 'data:image/png;base64,AAAA', '//a.com/x', 'a.com/x.jpg', 'http://', 'https://u:p@a.com/x',
    'https://a.com/a b', 'https://a.com/"x', "https://a.com/'x", 'https://a.com/<x>', 'https://a.com:99999/x', 'file:///etc/passwd', 'blob:https://a.com/1']) {
    assert.ok(photoLinkCheck(bad).error, bad);
  }
  assert.ok(photoLinkCheck('https://a.com/' + 'x'.repeat(PHOTO_LINK_MAX)).error);
  assert.equal(photoLinkCheck('https://a.com/' + 'x'.repeat(PHOTO_LINK_MAX - 14)).url.length, PHOTO_LINK_MAX);
});

test('error text has no em dash, bold or colon', () => {
  for (const bad of ['ftp://a.com', 'https://u:p@a.com/x', 'https://a.com/a b', 'https://a.com/' + 'x'.repeat(PHOTO_LINK_MAX)]) {
    const e = photoLinkCheck(bad).error;
    assert.ok(!/[\u2014:*]/.test(e), e);
  }
  assert.ok(!/[\u2014:*]/.test(photoPromptText('Pancakes')));
});

test('a stored link is shown only when it is safe', () => {
  assert.equal(linkPhotoSrc({ photo_url: 'https://a.com/x.jpg' }), 'https://a.com/x.jpg');
  for (const bad of ['javascript:alert(1)', 'https://u:p@a.com/x', ' https://a.com/x ', '', null, 7]) assert.equal(linkPhotoSrc({ photo_url: bad }), null, String(bad));
  assert.equal(linkPhotoSrc(null), null);
});

test('recipePhotoSrc: an upload wins over a link, a link needs no Allow Photos', () => {
  const up = 'Ab_cd-EF0123456789xyzQ.jpg';
  const both = { photo: up, photo_url: 'https://a.com/x.jpg' };
  assert.deepEqual(recipePhotoSrc(both, true), { src: '/api/photos/' + up, link: false });
  assert.deepEqual(recipePhotoSrc(both, false), { src: 'https://a.com/x.jpg', link: true });  // photos off: the upload is hidden, the link shows
  assert.deepEqual(recipePhotoSrc({ photo_url: 'https://a.com/x.jpg' }, true), { src: 'https://a.com/x.jpg', link: true });
  assert.deepEqual(recipePhotoSrc({ photo: up }, true), { src: '/api/photos/' + up, link: false });
  assert.equal(recipePhotoSrc({ photo: up }, false), null);
  assert.equal(recipePhotoSrc({ photo: 'bad.jpg', photo_url: 'ftp://a.com/x' }, true), null);
  assert.equal(recipePhotoSrc(null, true), null);
});

test('photo button label and prompt text', () => {
  assert.equal(photoButtonLabel(base, true), 'Add Photo');
  assert.equal(photoButtonLabel({ photo_url: 'https://a.com/x.jpg' }, false), 'Change Photo');
  assert.equal(photoButtonLabel({ photo: 'abcdefghijklmnop.jpg' }, false), 'Add Photo');
  assert.equal(photoPromptText('Pancakes'), 'Add a photo of Pancakes?');
  assert.equal(photoPromptText(''), 'Add a photo of this recipe?');
});

test('menu keys wrap and ignore other keys', () => {
  assert.equal(menuMove('ArrowDown', 4, 5), 0);
  assert.equal(menuMove('ArrowUp', 0, 5), 4);
  assert.equal(menuMove('Home', 3, 5), 0);
  assert.equal(menuMove('End', 0, 5), 4);
  assert.equal(menuMove('a', 0, 5), null);
  assert.equal(menuMove('ArrowDown', 0, 0), null);
});

test('summary parts keep each figure whole for no wrap spans', async () => {
  const { summaryParts } = await import('../../app/static/js/recipecards.js');
  assert.deepEqual(summaryParts(base), ['4 servings', '520 kcal', '32 g protein', '3 ingredients']);
});
