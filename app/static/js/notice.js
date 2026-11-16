import { autoClaudePlan, refreshClaudePlan, CLAUDE_CAP_NOTE } from './util.js';

// An automatic Claude step of Full Claude Use. st: a fresh /api/ai/status. Resolves { go, note }: go false and no note when
// Full Claude Use, the switch or the key is missing (silent fallback); the cap gives one quiet note and nothing is sent;
// otherwise it goes ahead. No dialog ever shows: the setting and the button the user pressed are the choice.
export async function autoClaude(settings, st, feature) {
  const plan = autoClaudePlan(settings, st, feature);
  if (plan === 'off') return { go: false, note: '' };
  if (plan === 'cap') return { go: false, note: CLAUDE_CAP_NOTE };
  return { go: true, note: '' };
}

// Search Then Claude chosen for a Refresh Nutrients run. Same result as autoClaude, but the choice itself replaces the Full Claude Use check.
export async function refreshClaude(settings, st) {
  const plan = refreshClaudePlan(settings, st);
  if (plan === 'off') return { go: false, note: '' };
  if (plan === 'cap') return { go: false, note: CLAUDE_CAP_NOTE };
  return { go: true, note: '' };
}
