// Pure helpers for the recipe cards of the Recipes tab (issue #48): the summary line, the accessible name, the chips, the
// placeholder tone, the grid class and the card menu. No DOM, so node can test them (tests/ui/recipecards.test.mjs).
import { MEALS, MEAL_LABELS, fmtNum, servingText, plural, ownerText } from './util.js';
import { photoUrl } from './photomath.js';

// How many ingredient lines a recipe has, from the list route (items, else needed plus skipped).
export function ingredientCount(meal) {
  if (meal && Array.isArray(meal.items)) return meal.items.length;
  return ((meal && meal.needed) || 0) + ((meal && meal.skipped) || 0);
}

// The parts of the summary line: ["4 servings", "520 kcal", "32 g protein", "8 ingredients"]. Per serving numbers come from
// per_serving; a missing one is left out.
export function summaryParts(meal, fmt = (v) => fmtNum(v, 0)) {
  const m = meal || {};
  const n = m.servings > 0 ? m.servings : 1;
  const per = m.per_serving || {};
  const parts = [servingText(n) + (n === 1 ? ' serving' : ' servings')];
  if (per.kcal != null) parts.push(fmt(per.kcal) + ' kcal');
  if (per.protein != null) parts.push(fmt(per.protein) + ' g protein');
  parts.push(plural(ingredientCount(m), 'ingredient'));
  return parts;
}

// The summary line: "4 servings · 520 kcal · 32 g protein · 8 ingredients".
export function recipeSummary(meal, fmt) { return summaryParts(meal, fmt).join(' · '); }

// The chips of a card, in order: meal tags (meal order), then the owner chip ("Shared by Ann", or "Shared" for my own shared
// recipe), then "3 of 8 matched" for a partial recipe. Each is { kind, label } with kind a meal, 'owner' or 'partial'.
export function cardChips(meal) {
  const m = meal || {};
  const out = MEALS.filter((k) => (m.meals || []).includes(k)).map((k) => ({ kind: k, label: MEAL_LABELS[k] }));
  const owner = ownerText(m);
  if (owner) out.push({ kind: 'owner', label: owner });
  if (m.complete === false && m.needed) out.push({ kind: 'partial', label: m.matched + ' of ' + m.needed + ' matched' });
  return out;
}

// The accessible name of the card button: the title, the summary and the chips, so nothing depends on color.
export function cardLabel(meal) {
  const chips = cardChips(meal).map((c) => c.label);
  return [String((meal && meal.name) || 'Recipe'), recipeSummary(meal)].concat(chips).join(', ');
}

// The placeholder color: the first meal tag in meal order, else the accent for an untagged recipe.
export function placeholderTone(meal) {
  const tags = (meal && meal.meals) || [];
  return MEALS.find((k) => tags.includes(k)) || 'accent';
}

// The list class: photos on gives the photo cards; off gives compact cards with a narrow placeholder strip.
export function cardGridClass(photosOn) {
  return photosOn ? 'card-grid' : 'card-grid compact';
}

// ---------- recipe photos: an uploaded file or a pasted image link (issue #52) ----------

export const PHOTO_LINK_MAX = 2000;  // same as core.PHOTO_URL_MAX

// A pasted image link as the server stores it, or { error }. Blank clears (url null). Only http and https with a host, no user
// name or password, no spaces, control characters, quotes or angle brackets, at most PHOTO_LINK_MAX characters. The server checks
// again and never fetches it.
export function photoLinkCheck(text) {
  const v = String(text == null ? '' : text).trim();
  if (!v) return { url: null };
  if (v.length > PHOTO_LINK_MAX) return { error: 'Keep the image link to ' + PHOTO_LINK_MAX + ' characters or fewer.' };
  if (/[\s\u0000-\u001f\u007f-\u009f<>"']/.test(v)) return { error: 'The image link must not contain spaces, quotes or angle brackets.' };
  let u;
  try { u = new URL(v); } catch (e) { return { error: 'Enter an image link that starts with http or https.' }; }
  if ((u.protocol !== 'http:' && u.protocol !== 'https:') || !u.hostname || !/^https?:\/\//i.test(v)) return { error: 'Enter an image link that starts with http or https.' };
  if (u.username || u.password || u.host.includes('@')) return { error: 'Remove the user name or password from the image link.' };
  return { url: v };
}

// The stored link of a recipe when it is a safe http or https link, else null (a bad stored value never reaches an img src).
export function linkPhotoSrc(meal) {
  const v = meal && meal.photo_url;
  if (typeof v !== 'string') return null;
  const r = photoLinkCheck(v);
  return r.url === v ? v : null;
}

// What the recipe shows as its photo: { src, link } or null. An uploaded photo wins over a link, but is only shown while Allow
// Photos is on (photosOn); a link needs no switch. link true means a hotlink, which the page loads with no referrer.
export function recipePhotoSrc(meal, photosOn) {
  const up = photosOn && meal ? photoUrl(meal.photo) : null;
  if (up) return { src: up, link: false };
  const link = linkPhotoSrc(meal);
  return link ? { src: link, link: true } : null;
}

// The photo actions of the three dot menus. Upload Photo and Take Photo store a file, so they need Allow Photos; Paste Image Link does not.
// Remove Photo shows when there is something to remove (an upload while photos are on, or a link). [{ key, label }].
export function photoMenuItems(meal, photosOn) {
  const m = meal || {};
  const out = [];
  if (photosOn) out.push({ key: 'photo-upload', label: 'Upload Photo' }, { key: 'photo-take', label: 'Take Photo' });
  out.push({ key: 'photo-link', label: 'Paste Image Link' });
  if ((photosOn && m.photo) || m.photo_url) out.push({ key: 'photo-remove', label: 'Remove Photo', danger: true });
  return out;
}

// The label of the photo button on the recipe screen: Add Photo, or Change Photo when the recipe has one.
export function photoButtonLabel(meal, photosOn) {
  return recipePhotoSrc(meal, photosOn) ? 'Change Photo' : 'Add Photo';
}

// The toast after logging a recipe that has no photo, and its Take Photo button.
export const photoPromptText = (name) => 'Add a photo of ' + String(name || 'this recipe') + '?';

// The card menu: Log, Cooking and Duplicate for every recipe I can read; Delete and the photo actions only with can_edit.
// Returns [{ key, label }].
export function cardMenuItems(meal, photosOn) {
  const m = meal || {};
  const edit = m.can_edit !== false;
  const out = [{ key: 'log', label: 'Log' }, { key: 'cooking', label: 'Cooking' }];
  if (edit) out.push(...photoMenuItems(m, photosOn));
  out.push({ key: 'duplicate', label: 'Duplicate' });
  if (edit) out.push({ key: 'delete', label: 'Delete' });
  return out;
}

// The menu button's name: "More Actions for Pancakes".
export function menuLabel(meal) { return 'More Actions for ' + String((meal && meal.name) || 'Recipe'); }

// Keyboard movement in an open menu: the next index for a key, or null when the key does not move.
export function menuMove(key, index, count) {
  if (!count) return null;
  if (key === 'ArrowDown') return (index + 1) % count;
  if (key === 'ArrowUp') return (index - 1 + count) % count;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  return null;
}
