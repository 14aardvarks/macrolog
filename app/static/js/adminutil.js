// Pure helpers for the setup, Claude key and Admin screens. No DOM here so node can test them.

export const MIN_PASSWORD = 8;
export const PERSONAL_CAP_MAX = 10000;
export const PERSONAL_CAP_DEFAULT = 100;  // same as ai.DEFAULT_PERSONAL_CAP
export const DEFAULT_MODEL = 'claude-haiku-5-5';  // same as ai.DEFAULT_MODEL
export const PRICE_MAX = 10000;  // same limit as the admin price fields

const SOURCE_LABELS = { database: 'Saved here', environment: 'From environment', default: 'Default' };
export function sourceLabel(source) { return SOURCE_LABELS[source] || ''; }

// First-run form check. Returns an error text, or '' when the form is fine.
export function setupError(username, password) {
  if (!String(username || '').trim()) return 'Enter a username.';
  if (String(password || '').length < MIN_PASSWORD) return 'The password needs at least ' + MIN_PASSWORD + ' characters.';
  return '';
}

export function userName(u) { return u.display_name || u.username; }

export function userBadges(u) {
  const out = [];
  if (u.is_admin) out.push('Admin');
  if (u.disabled) out.push('Disabled');
  if (u.sso_linked) out.push('SSO');
  if (u.personal_key_set) out.push('Own Claude key');
  return out;
}

// Which Claude key a user is on, in plain words. ai is /api/ai/status, useGlobal is me.use_global_ai.
export function claudeStatusLines(ai, useGlobal) {
  const lines = [];
  if (ai.key_source === 'personal') {
    lines.push('Using your personal key. Used ' + ai.personal_used_this_month + ' of ' + ai.personal_cap + ' requests this month.');
  } else if (ai.key_source === 'global') {
    lines.push('Using the shared key. Used ' + ai.used_this_month + ' of ' + ai.cap + ' requests this month.');
  } else {
    lines.push('No Claude key in use. Claude is off for you.');
  }
  if (ai.personal_key_unreadable) lines.push('Your saved key could not be read. Paste it again.');
  if (!ai.can_use_global) {
    lines.push(useGlobal === false ? 'The shared key is turned off for your account.' : 'There is no shared key on this server.');
  }
  return lines;
}

// Personal cap input: returns {ok, value} or {ok:false, error}.
export function parseCap(text) {
  const t = String(text == null ? '' : text).trim();
  if (!/^\d+$/.test(t)) return { ok: false, error: 'The limit must be a whole number.' };
  const n = Number(t);
  if (n < 1 || n > PERSONAL_CAP_MAX) return { ok: false, error: 'The limit must be from 1 to ' + PERSONAL_CAP_MAX + '.' };
  return { ok: true, value: n };
}

// Body for PUT /api/ai/key, or null when nothing changed.
export function keyBody(keyText, capValue, originalCap) {
  const body = {};
  const key = String(keyText || '').trim();
  if (key) body.key = key;
  if (capValue !== originalCap) body.cap = capValue;
  return Object.keys(body).length ? body : null;
}

// A price box: '' (not set) or a number from 0 to PRICE_MAX. Returns {ok, value} with value '' or a number, or {ok:false, error}.
export function parsePrice(text, label) {
  const t = String(text == null ? '' : text).trim().replace(',', '.');
  if (!t) return { ok: true, value: '' };
  const n = Number(t);
  if (!/^(\d+\.?\d*|\.\d+)$/.test(t) || n > PRICE_MAX) return { ok: false, error: label + ' must be a number from 0 to ' + PRICE_MAX + '.' };
  return { ok: true, value: n };
}

// Body for PUT /api/ai/key from the personal Claude form, or {error}. body is null when nothing changed.
// f: {key, cap, model, priceIn, priceOut} as typed; ai: /api/ai/status. Cleared fields send '' (the server stores not set).
export function personalBody(f, ai) {
  const c = parseCap(f.cap);
  if (!c.ok) return { error: c.error };
  const pin = parsePrice(f.priceIn, 'Input price');
  if (!pin.ok) return { error: pin.error };
  const pout = parsePrice(f.priceOut, 'Output price');
  if (!pout.ok) return { error: pout.error };
  const body = keyBody(f.key, c.value, ai.personal_cap) || {};
  const model = String(f.model || '').trim();
  if (model !== (ai.personal_model || '')) body.model = model;
  const was = (v) => (v == null ? '' : v);
  if (pin.value !== was(ai.personal_price_in)) body.price_in = pin.value;
  if (pout.value !== was(ai.personal_price_out)) body.price_out = pout.value;
  return { body: Object.keys(body).length ? body : null };
}

// Hints under the personal Claude fields, with the defaults. ai: /api/ai/status.
export function personalHints(ai) {
  const server = (ai && (ai.server_model || ai.model)) || DEFAULT_MODEL;
  const cap = (ai && ai.personal_cap_default) || PERSONAL_CAP_DEFAULT;
  return {
    cap: 'The most requests your own key can make per calendar month, from 1 to ' + PERSONAL_CAP_MAX + '. ' + cap + ' by default.',
    model: 'The Claude model your own key uses. Empty by default, which uses the server\'s model, ' + server + '.',
    priceIn: 'What Anthropic charges for input tokens on your model, in USD. Empty by default, so no cost is shown.',
    priceOut: 'What Anthropic charges for output tokens on your model, in USD. Empty by default, so no cost is shown.',
  };
}

// What the Sign-in block of Settings should show.
export function ssoView(cfg, me) {
  if (!cfg || !cfg.oidc) return { state: 'off' };
  if (!me.sso_linked) return { state: 'connect' };
  if (!me.has_password) return { state: 'linked', canDisconnect: false, hint: 'Set a password first. Ask an administrator.' };
  if (cfg.local === false) return { state: 'linked', canDisconnect: false, hint: 'Password sign-in is off on this server.' };
  return { state: 'linked', canDisconnect: true, hint: '' };
}

// Value of one config field as the admin form sees it.
// spec: {key, kind: 'text'|'bool'|'int'|'price'|'secret'}, item: the setting from GET /api/admin/config.
export function initialValue(spec, item) {
  if (spec.kind === 'secret') return '';
  if (spec.kind === 'bool') return !!item.value;
  return item.value == null ? '' : String(item.value);
}

// Only the keys that changed. state: {value, revert, clear}. Returns {changes} or {error}.
// A revert sends null (use the default or environment value); a secret clear sends "".
export function buildChanges(specs, items, states) {
  const changes = {};
  for (const spec of specs) {
    const item = items[spec.key];
    const st = states[spec.key];
    if (!st) continue;
    if (st.revert) { changes[spec.key] = null; continue; }
    if (spec.kind === 'secret') {
      const v = String(st.value || '').trim();
      if (st.clear) changes[spec.key] = '';
      else if (v) changes[spec.key] = v;
      continue;
    }
    const start = initialValue(spec, item);
    if (spec.kind === 'bool') {
      if (!!st.value !== start) changes[spec.key] = !!st.value;
      continue;
    }
    const v = String(st.value == null ? '' : st.value).trim();
    if (v === start) continue;
    if (spec.kind === 'int') {
      if (!/^\d+$/.test(v)) return { error: spec.label + ' must be a whole number.' };
      changes[spec.key] = Number(v);
    } else if (spec.kind === 'price') {
      if (v !== '' && !(Number(v) >= 0)) return { error: spec.label + ' must be a number.' };
      changes[spec.key] = v;
    } else {
      changes[spec.key] = v;
    }
  }
  return { changes };
}

export const SIGNIN_SPECS = [
  { key: 'local_login', kind: 'bool', label: 'Password sign-in' },
  { key: 'oidc_allow_signup', kind: 'bool', label: 'Create accounts on first SSO sign-in',
    hint: 'Anyone who can sign in to the authentik application gets an account. Restrict access with application bindings in authentik.' },
  { key: 'oidc_name', kind: 'text', label: 'Button name' },
  { key: 'oidc_issuer', kind: 'text', label: 'Issuer URL' },
  { key: 'oidc_client_id', kind: 'text', label: 'Client ID' },
  { key: 'oidc_client_secret', kind: 'secret', label: 'Client secret' },
  { key: 'oidc_admin_group', kind: 'text', label: 'Admin group',
    hint: 'Members of this authentik group become Macrolog admins, for example admin. Leave empty to manage admins manually.' },
  { key: 'oidc_user_group', kind: 'text', label: 'Allowed user group',
    hint: 'Only members of this group (or the admin group) can sign in with SSO, for example user. Leave empty to allow everyone who can sign in to the authentik application.' },
  { key: 'oidc_groups_claim', kind: 'text', label: 'Groups claim' },
];
export const CLAUDE_SPECS = [
  { key: 'ai_global_key', kind: 'secret', label: 'Shared Claude key',
    hint: 'Your Anthropic API key, shared by everyone on this server who has not set their own. Create one at console.anthropic.com. Empty by default, so Claude is off until a key is set. Stored encrypted and never shown again.' },
  { key: 'ai_model', kind: 'text', label: 'Model',
    hint: 'The Claude model used for label reading, typed lookups and recipe parsing. Empty by default, which uses ' + DEFAULT_MODEL + ', the cheapest option and fine for these jobs.' },
  { key: 'ai_monthly_cap', kind: 'int', label: 'Monthly request limit',
    hint: 'The most Claude requests everyone on the shared key can make per calendar month. 100 by default. Set 0 to turn shared use off.' },
  { key: 'ai_price_in_per_mtok', kind: 'price', label: 'Input price per million tokens',
    hint: 'What Anthropic charges for input tokens on your model, in USD. Empty by default, so no cost is shown. Fill in from Anthropic\'s pricing page to see the cost of each request.' },
  { key: 'ai_price_out_per_mtok', kind: 'price', label: 'Output price per million tokens',
    hint: 'What Anthropic charges for output tokens on your model, in USD. Empty by default, so no cost is shown. Fill in from Anthropic\'s pricing page to see the cost of each request.' },
  { key: 'ai_allow_label', kind: 'bool', label: 'Allow Claude Photo Label Reading',
    hint: 'On by default. Turn off to hide Ask Claude for nutrition label photos and refuse those requests for everyone.' },
  { key: 'ai_allow_lookup', kind: 'bool', label: 'Allow Claude Typed Search',
    hint: 'On by default. Turn off to remove Claude from the Source choice on Add and refuse typed lookups for everyone.' },
  { key: 'ai_allow_recipe', kind: 'bool', label: 'Allow Claude Recipe Import',
    hint: 'On by default. Turn off to stop Claude reading recipes and matching ingredients for everyone. Split Lines Without Claude and Search still work.' },
];
export const FOOD_SPECS = [
  { key: 'fdc_api_key', kind: 'secret', label: 'USDA API key',
    hint: 'Without your own key, the shared demo key allows only 30 lookups per hour and 50 per day, for everyone on this server together. A free personal key allows 1,000 per hour. Get one at fdc.nal.usda.gov/api-key-signup.html, enter your email, and the key arrives by email within minutes. Foods already saved here never use a lookup again.' },
];

// Server info rows. SECRET_KEY is only ever set or not set.
export function envRows(env) {
  const rows = [];
  for (const k of Object.keys(env || {})) {
    if (k === 'note') continue;
    const v = env[k];
    let text;
    if (v && typeof v === 'object') text = v.set ? 'Set' : 'Not set';
    else if (typeof v === 'boolean') text = v ? 'On' : 'Off';
    else text = v === '' || v == null ? 'Not set' : String(v);
    rows.push([k, text]);
  }
  return rows;
}

// "2026-11-11T10:20:30Z" to a short local text. Falls back to the raw text.
export function whenText(iso) {
  const d = new Date(iso);
  if (!iso || isNaN(d.getTime())) return String(iso || '');
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function testLine(rec) {
  if (!rec || !rec.at) return 'No successful test yet.';
  return 'Last good test ' + whenText(rec.at) + (rec.matches_current === false ? ', before the current settings.' : '.');
}

// One activity row: who, what, target.
export function logLine(e) {
  const parts = [e.action];
  if (e.target) parts.push(e.target);
  if (e.detail) parts.push(e.detail);
  return { when: whenText(e.at), who: e.admin_username || 'system', text: parts.join(' - ') };
}
