// Screen URLs (issue #22). Hash routes, so the server, the service worker shell and the auth redirects need no change.
// One table for every screen that has its own URL; pure helpers only, so node can test them (tests/ui/routes.test.mjs).
// Screens not in the table (in progress flows, the food finder of a recipe, scan, Claude, manual entry, editing a logged entry)
// keep the URL of the screen they were opened from, so a reload falls back to that parent screen.

const MEAL_QUERY = ['breakfast', 'lunch', 'dinner', 'snack', 'dessert'];  // same list as util.js MEALS

// path: segments, ':id' is a positive whole number kept in params[key]. query: params allowed after '?'. tab: the bottom bar button.
export const ROUTES = [
  { name: 'today', path: ['today'], tab: 'today' },
  { name: 'recipelog', path: ['today', 'log', ':id'], key: 'groupId', tab: 'today' },
  { name: 'add', path: ['add'], tab: 'add' },
  { name: 'picker', path: ['add', 'food', ':id'], key: 'foodId', query: ['meal'], tab: 'add' },
  { name: 'meal', path: ['add', 'recipe', ':id'], key: 'mealId', query: ['meal'], tab: 'add' },
  { name: 'recipes', path: ['recipes'], tab: 'recipes' },
  { name: 'recipeview', path: ['recipes', ':id'], key: 'mealId', tab: 'recipes' },
  { name: 'cooking', path: ['recipes', ':id', 'cooking'], key: 'mealId', tab: 'recipes' },
  { name: 'settings', path: ['settings'], tab: 'settings' },
  { name: 'saved', path: ['saved'], tab: 'settings' },
  { name: 'admin', path: ['admin'], tab: 'settings' },
];

// The tab of screens without a URL of their own; every other screen belongs to Add.
const TAB_OF = { editfood: 'settings', import: 'recipes', importreview: 'recipes', match: 'recipes', recipe: 'recipes' };

export const tabOf = (name) => {
  const r = ROUTES.find((x) => x.name === name);
  return r ? r.tab : TAB_OF[name] || 'add';
};

const isId = (s) => /^[1-9]\d{0,15}$/.test(s);

// '#/recipes/12/cooking' -> { name: 'cooking', params: { mealId: 12 } }. Null for an empty hash or an unknown route.
// '#settings' (where the SSO link flow returns) means Settings.
export function parseRoute(hash) {
  let s = String(hash || '');
  if (s[0] === '#') s = s.slice(1);
  if (s === 'settings') return { name: 'settings', params: {} };
  if (s[0] !== '/') return null;
  const qi = s.indexOf('?');
  const parts = (qi < 0 ? s : s.slice(0, qi)).split('/').slice(1);
  if (parts.length && parts[parts.length - 1] === '') parts.pop();  // a trailing slash is fine
  const query = new URLSearchParams(qi < 0 ? '' : s.slice(qi + 1));
  for (const r of ROUTES) {
    if (r.path.length !== parts.length) continue;
    const params = {};
    const ok = r.path.every((seg, i) => {
      if (seg !== ':id') return seg === parts[i];
      if (!isId(parts[i])) return false;
      params[r.key] = Number(parts[i]);
      return true;
    });
    if (!ok) continue;
    for (const q of r.query || []) {
      const v = query.get(q);
      if (q === 'meal' && MEAL_QUERY.includes(v)) params.meal = v;
    }
    return { name: r.name, params };
  }
  return null;
}

// The hash for a screen, or null when it has no URL of its own (it keeps its parent's). Params that only make sense
// mid flow (editing a logged entry, picking for a recipe row, a copy from Yesterday, the recipe finder) mean no URL.
export function formatRoute(name, params) {
  const p = params || {};
  const r = ROUTES.find((x) => x.name === name);
  if (!r) return null;
  if (name === 'picker' && (p.entryId != null || p.adjust)) return null;
  if (name === 'recipelog' && p.copy) return null;
  if (name === 'add' && p.ingredient) return null;
  let id = null;
  if (r.key) {
    id = String(p[r.key]);
    if (!isId(id)) return null;
  }
  const path = r.path.map((seg) => (seg === ':id' ? id : seg)).join('/');
  const q = (r.query || []).filter((k) => k === 'meal' && MEAL_QUERY.includes(p.meal)).map((k) => k + '=' + p[k]);
  return '#/' + path + (q.length ? '?' + q.join('&') : '');
}

// The URL to show for a screen: its own, else the current one (the parent screen). current is location.hash; inFlow is true
// while the screen serves a recipe (the food finder of Create Recipe or Match Ingredients), which never has a URL of its own.
export function routeUrl(name, params, current, inFlow) {
  return (!inFlow && formatRoute(name, params)) || current || '';
}

// Where a URL opens: the route, or Today for an unknown one. Null for no hash at all (the Start Screen setting applies).
export function startRoute(hash) {
  if (!hash || hash === '#') return null;
  return parseRoute(hash) || { name: 'today', params: {} };
}
