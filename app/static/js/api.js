import { localDate, sentence } from './util.js';

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

function detailText(d) {
  if (typeof d === 'string') return sentence(d);
  if (Array.isArray(d)) return sentence(d.map((x) => (x && x.msg) || String(x)).join('; '));
  return 'Something went wrong';
}

function qs(params) {
  const p = Object.keys(params || {}).filter((k) => params[k] != null && params[k] !== '');
  return p.length ? '?' + p.map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(params[k])).join('&') : '';
}

async function request(method, path, opts = {}) {
  const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (opts.json !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.json);
  } else if (opts.form) {
    init.body = opts.form;
  }
  let res;
  try {
    res = await fetch(path + qs(opts.query), init);
  } catch (e) {
    throw new ApiError(0, 'Cannot reach the server. Check your connection.');
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (res.status === 401 && !opts.keep401) onUnauthorized();
  if (!res.ok) throw new ApiError(res.status, detailText(data && data.detail));
  return data;
}

const day = () => localDate();
const get = (p, query) => request('GET', p, { query });
const send = (m, p, json) => request(m, p, { json: json === undefined ? {} : json });

export const api = {
  authConfig: () => get('/api/auth/config'),
  login: (username, password) => request('POST', '/api/auth/login', { json: { username, password }, keep401: true }),
  logout: () => send('POST', '/api/auth/logout'),
  me: () => get('/api/auth/me'),
  setup: (body) => request('POST', '/api/auth/setup', { json: body, keep401: true }),
  unlinkSso: () => send('POST', '/api/auth/sso/unlink'),
  putAiKey: (body) => send('PUT', '/api/ai/key', body),
  deleteAiKey: () => request('DELETE', '/api/ai/key'),
  adminUsers: () => get('/api/admin/users'),
  adminCreateUser: (body) => send('POST', '/api/admin/users', body),
  adminPatchUser: (id, body) => send('PATCH', '/api/admin/users/' + id, body),
  adminConfig: () => get('/api/admin/config'),
  adminSaveConfig: (body) => send('PUT', '/api/admin/config', body),
  adminTestOidc: (body) => send('POST', '/api/admin/oidc/test', body),
  adminLog: () => get('/api/admin/log'),
  settings: () => get('/api/settings'),
  saveSettings: (s) => send('PUT', '/api/settings', s),
  display: () => get('/api/settings/display'),
  saveDisplay: (patch) => send('PUT', '/api/settings/display', patch),
  goals: () => get('/api/goals'),
  microGoals: () => get('/api/goals/micros'),
  saveMicroGoals: (targets) => send('PUT', '/api/goals/micros', { targets }),
  saveGoals: (g) => send('PUT', '/api/goals', g),
  day: (d) => get('/api/day', { day: d || day() }),
  quick: (kind, d, meal) => get('/api/quick/' + kind, kind === 'yesterday' ? { day: d || day() } : kind === 'recent' && meal && meal !== 'all' ? { meal } : undefined),
  search: (q, remote, source) => get('/api/foods/search', { q, remote: remote ? 1 : 0, source: source && source !== 'all' ? source : null }),
  barcode: (code) => get('/api/foods/barcode/' + encodeURIComponent(code)),
  food: (id) => get('/api/foods/' + id),
  createFood: (f) => send('POST', '/api/foods', f),
  preview: (food_id, amount, unit) => get('/api/preview', { food_id, amount, unit }),
  logEntry: (e) => send('POST', '/api/entries', { day: day(), ...e }),
  patchEntry: (id, patch) => send('PATCH', '/api/entries/' + id, patch),
  deleteEntry: (id) => request('DELETE', '/api/entries/' + id),
  logGroup: (id) => get('/api/entry-groups/' + id),
  patchGroup: (id, patch) => send('PATCH', '/api/entry-groups/' + id, patch),
  deleteGroup: (id) => request('DELETE', '/api/entry-groups/' + id),
  copyGroup: (id, body) => send('POST', '/api/entry-groups/' + id + '/copy', { day: day(), ...body }),
  favorite: (id, on) => request(on ? 'POST' : 'DELETE', '/api/favorites/' + id),
  meals: () => get('/api/meals'),
  createMeal: (body) => send('POST', '/api/meals', body),
  deleteMeal: (id) => request('DELETE', '/api/meals/' + id),
  mealFromMeal: (name, meal, entry_ids, d) => send('POST', '/api/meals/from-meal', { name, meal, entry_ids, day: d || day() }),
  logMeal: (id, body) => send('POST', '/api/meals/' + id + '/log', { day: day(), ...body }),
  saved: () => get('/api/saved'),
  favoriteTags: (id, meals) => send('PUT', '/api/favorites/' + id + '/tags', { meals }),
  removeFromLists: (id) => send('POST', '/api/saved/favorites/' + id + '/remove'),
  patchMeal: (id, body) => send('PATCH', '/api/meals/' + id, body),
  patchFood: (id, body) => send('PATCH', '/api/foods/' + id, body),
  refreshNutrients: (id) => send('POST', '/api/foods/' + id + '/refresh-nutrients'),
  missingNutrients: (d) => get('/api/foods/missing-nutrients', d ? { date: d } : undefined),
  deleteFood: (id) => request('DELETE', '/api/foods/' + id),
  aiStatus: (images, chars, extra) => get('/api/ai/status', images || chars != null || extra ? { images, chars, ...(extra || {}) } : undefined),
  aiLabel: (form) => request('POST', '/api/ai/label', { form }),
  aiLookup: (text, note) => send('POST', '/api/ai/lookup', note ? { text, note } : { text }),
  meal: (id) => get('/api/meals/' + id),
  importMeal: (body) => send('POST', '/api/meals/import', body),
  matchItem: (mealId, itemId, body) => send('PATCH', '/api/meals/' + mealId + '/items/' + itemId, body),
  addMealItem: (mealId, body) => send('POST', '/api/meals/' + mealId + '/items', body),
  deleteMealItem: (mealId, itemId) => request('DELETE', '/api/meals/' + mealId + '/items/' + itemId),
  deleteUncounted: (mealId) => request('DELETE', '/api/meals/' + mealId + '/uncounted'),
  matchItems: (mealId, items) => send('PATCH', '/api/meals/' + mealId + '/items', { items }),
  recipeFromText: (text, note) => send('POST', '/api/recipes/import/text', note ? { text, note } : { text }),
  recipeFromPhotos: (form) => request('POST', '/api/recipes/import/photos', { form }),
  matchSearch: (mealId, ids, source) => send('POST', '/api/recipes/' + mealId + '/match-search', source ? { item_ids: ids, source } : { item_ids: ids }),
  matchIngredients: (mealId, ids) => send('POST', '/api/recipes/' + mealId + '/match', { item_ids: ids }),
};
