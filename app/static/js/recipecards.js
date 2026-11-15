// Pure helpers for the recipe cards of the Recipes tab (issue #48): the summary line, the accessible name, the chips, the
// placeholder tone, the grid class and the card menu. No DOM, so node can test them (tests/ui/recipecards.test.mjs).
import { MEALS, MEAL_LABELS, fmtNum, servingText, plural, ownerText } from './util.js';

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

// The card menu: Log, Cooking and Duplicate for every recipe I can read; Delete and the photo action only with can_edit,
// the photo action only while photos are on. Returns [{ key, label }].
export function cardMenuItems(meal, photosOn) {
  const m = meal || {};
  const edit = m.can_edit !== false;
  const out = [{ key: 'log', label: 'Log' }, { key: 'cooking', label: 'Cooking' }];
  if (edit && photosOn) out.push({ key: 'photo', label: m.photo ? 'Replace Photo' : 'Add Photo' });
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
