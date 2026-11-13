// Recently Deleted recipes (issue #41). Pure helpers, no DOM: texts, timing and list order for the Undo notice and the
// Recently Deleted section on the Recipes tab. The server keeps a deleted recipe RECIPE_PURGE_DAYS days (core.RECIPE_PURGE_DAYS),
// then removes it for good; GET /api/meals/deleted sends the same number as purge_days.
import { sentence } from './util.js';

export const RECIPE_PURGE_DAYS = 30;
export const UNDO_MS = 10000;  // how long the Undo notice stays up (paused while hovered or focused)

// The number of days a deleted recipe is kept, from the server when it says, else the default.
export function purgeDays(v) {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : RECIPE_PURGE_DAYS;
}

export function deleteRecipeConfirm(name, days) {
  return 'Delete This Recipe? ' + sentence('"' + name + '" moves to Recently Deleted for ' + purgeDays(days) + ' days, then is removed for good')
    + ' ' + sentence('Entries already in your log stay');
}

export function deleteForeverConfirm(name) {
  return 'Delete Forever? ' + sentence('"' + name + '" is removed for good and cannot be restored') + ' ' + sentence('Entries already in your log stay');
}

export function deletedNoticeText(name) { return sentence('"' + name + '" moved to Recently Deleted'); }
export function restoredText(name) { return sentence('"' + name + '" is back in your recipes'); }
export function purgedText(name) { return sentence('"' + name + '" was deleted for good'); }

// The hint under the Recently Deleted heading, stating the default.
export function deletedHint(days) {
  return sentence('Deleted recipes stay here for ' + purgeDays(days) + ' days, then are removed for good') + ' '
    + sentence('Restore brings one back exactly as it was') + ' ' + sentence('Entries already in your log stay');
}

// "Recently Deleted (2)" for the collapsible section's summary.
export function deletedTitle(n) { return 'Recently Deleted (' + n + ')'; }

// "12 days left", "1 day left", "Last day" (0 or less, removed at the next listing or start).
export function daysLeftText(n) {
  const d = Math.max(0, Math.floor(Number(n) || 0));
  if (d <= 0) return 'Last day';
  return d + (d === 1 ? ' day left' : ' days left');
}

// Newest deleted first (the server's order), so a list changed on the client keeps it. Does not change the input.
export function sortDeleted(list) {
  return (list || []).slice().sort((a, b) => String(b.deleted_at || '').localeCompare(String(a.deleted_at || '')) || (b.id - a.id));
}

// Takes one recipe out of the deleted list (after Restore or Delete Forever).
export function withoutDeleted(list, id) { return (list || []).filter((m) => m.id !== id); }
