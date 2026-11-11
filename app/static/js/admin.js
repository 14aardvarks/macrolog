import { api } from './api.js';
import { h, clear, field, message, show } from './dom.js';
import {
  sourceLabel, userName, userBadges, initialValue, buildChanges, SIGNIN_SPECS, CLAUDE_SPECS, FOOD_SPECS, envRows, testLine, logLine, setupError,
} from './adminutil.js';

const bool = (v) => !!v;
let changed = () => {};  // set by renderAdmin: refreshes the Activity list after any change

// ---------- config fields ----------

// One setting. Returns {el, state}. state.value is what the user typed, state.revert and state.clear are the buttons.
function configField(spec, item, extra) {
  const st = { value: initialValue(spec, item), revert: false, clear: false };
  const hint = h('p', { class: 'src' });
  const id = 'cfg-' + spec.key;
  let control;
  const paintHint = () => {
    const bits = [];
    const src = sourceLabel(item.source);
    if (src) bits.push(src);
    if (spec.kind === 'secret' && item.unreadable) bits.push('The stored value could not be read');
    if (st.revert) bits.push('Will use the default when you save');
    if (st.clear) bits.push('Will be cleared when you save');
    hint.textContent = bits.join('. ');
  };
  const useDefault = item.source === 'database' ? h('button', { class: 'link-btn', type: 'button', onclick: () => {
    st.revert = true; st.clear = false;
    if (control.type === 'checkbox') control.disabled = true; else { control.value = ''; control.disabled = true; }
    undo.hidden = false; useDefault.hidden = true; paintHint();
  } }, 'Use default') : null;
  const undo = h('button', { class: 'link-btn', type: 'button', hidden: true, onclick: () => {
    st.revert = false; control.disabled = false;
    if (control.type === 'checkbox') control.checked = bool(initialValue(spec, item)); else control.value = initialValue(spec, item);
    st.value = initialValue(spec, item);
    undo.hidden = true; if (useDefault) useDefault.hidden = false; paintHint();
  } }, 'Undo');

  let el;
  if (spec.kind === 'bool') {
    control = h('input', { type: 'checkbox', id, checked: bool(st.value), 'aria-describedby': id + '-src' });
    control.addEventListener('change', () => { st.value = control.checked; });
    el = h('div', { class: 'switch-row' }, h('label', { for: id }, control, h('span', null, spec.label)));
  } else if (spec.kind === 'secret') {
    control = h('input', { type: 'password', id, autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false',
      placeholder: item.set ? 'Saved' : 'Not set', 'aria-describedby': id + '-src' });
    control.addEventListener('input', () => { st.value = control.value; if (control.value) { st.clear = false; paintHint(); } });
    const clearBtn = item.set ? h('button', { class: 'btn', type: 'button', onclick: () => {
      st.clear = true; control.value = ''; st.value = ''; paintHint();
    } }, 'Clear') : null;
    el = h('div', { class: 'field' }, h('label', { for: id }, h('span', null, spec.label)),
      h('div', { class: 'row' }, control, clearBtn));
  } else {
    const num = spec.kind === 'int' || spec.kind === 'price';
    control = h('input', { type: 'text', id, value: st.value, autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false',
      inputmode: num ? 'decimal' : null, 'aria-describedby': id + '-src' });
    control.addEventListener('input', () => { st.value = control.value; });
    el = h('div', { class: 'field' }, h('label', { for: id }, h('span', null, spec.label)), control);
  }
  hint.id = id + '-src';
  paintHint();
  el.appendChild(h('div', { class: 'src-row' }, hint, useDefault, undo));
  if (spec.hint) el.appendChild(h('p', { class: 'sub' }, spec.hint));
  if (extra) el.appendChild(extra);
  return { el, state: st, control };
}

// A section with its fields and one Save button. onSaved(cfg) repaints with fresh data.
function configSection(title, specs, cfg, note, opts) {
  const o = opts || {};
  const status = h('div', { 'aria-live': 'polite' });
  const fields = {};
  const nodes = specs.map((spec) => {
    const f = configField(spec, cfg.settings[spec.key], o.extra && o.extra[spec.key]);
    fields[spec.key] = f;
    return f.el;
  });
  const save = async (e) => {
    e.preventDefault();
    const states = {};
    for (const k of Object.keys(fields)) states[k] = fields[k].state;
    const r = buildChanges(specs, cfg.settings, states);
    if (r.error) { show(status, message(r.error, 'error')); return; }
    if (!Object.keys(r.changes).length) { show(status, message('Nothing to change.')); return; }
    try {
      const next = await api.adminSaveConfig(r.changes);
      changed();
      o.onSaved(next, 'Saved.');
    } catch (err) { show(status, message(err.message, 'error')); }
  };
  if (note) show(status, message(note));
  return { fields, status, el: h('form', { class: 'admin-form', onsubmit: save }, nodes, o.after || null, status,
    h('button', { class: 'btn primary', type: 'submit' }, 'Save')) };
}

// ---------- sections ----------

function signInSection(cfg, note, onSaved) {
  const uri = cfg.oidc_redirect_uri;
  const copyStatus = h('span', { class: 'src', 'aria-live': 'polite' });
  const copy = uri ? h('button', { class: 'btn', type: 'button', onclick: async () => {
    try { await navigator.clipboard.writeText(uri); copyStatus.textContent = 'Copied.'; } catch (e) { copyStatus.textContent = 'Press and hold the address to copy it.'; }
  } }, 'Copy') : null;
  const redirect = h('div', { class: 'redirect' },
    h('h3', null, 'Redirect URI'),
    uri ? h('div', { class: 'row wrap' }, h('code', { class: 'uri' }, uri), copy, copyStatus) : null,
    cfg.oidc_redirect_uri_warning ? message(cfg.oidc_redirect_uri_warning, 'error') : null,
    h('p', { class: 'sub' }, 'Paste this into authentik. In authentik:'),
    h('ul', { class: 'checklist' }, cfg.authentik_checklist.map((t) => h('li', null, t))));
  const testOut = h('div', { 'aria-live': 'polite' });
  const lastTest = h('p', { class: 'src' }, testLine(cfg.oidc_test));
  const section = configSection('Sign-in', SIGNIN_SPECS, cfg, note, { onSaved });
  const test = h('button', { class: 'btn', type: 'button', onclick: async (e) => {
    const b = e.currentTarget;
    b.disabled = true;
    show(testOut, message('Testing...'));
    try {
      const body = {};
      const iss = section.fields.oidc_issuer, cid = section.fields.oidc_client_id;
      if (!iss.state.revert && iss.state.value.trim()) body.issuer = iss.state.value.trim();
      if (!cid.state.revert && cid.state.value.trim()) body.client_id = cid.state.value.trim();
      const r = await api.adminTestOidc(body);
      show(testOut, message((r.ok ? 'Works. ' : 'Failed. ') + r.message, r.ok ? '' : 'error'));
      const fresh = await api.adminConfig();
      lastTest.textContent = testLine(fresh.oidc_test);
    } catch (err) { show(testOut, message(err.message, 'error')); }
    b.disabled = false;
  } }, 'Test connection');
  return h('section', { class: 'admin-sec' }, h('h2', null, 'Sign-in'),
    h('p', { class: 'sub' }, 'Local password sign-in and single sign-on (OpenID Connect).'),
    section.el, h('h3', null, 'Test'), h('div', { class: 'row wrap' }, test), testOut, lastTest, redirect);
}

function claudeSection(cfg, note, onSaved) {
  const s = configSection('Claude', CLAUDE_SPECS, cfg, note, { onSaved });
  return h('section', { class: 'admin-sec' }, h('h2', null, 'Claude'),
    h('p', { class: 'sub' }, 'The shared key and limit are used by everyone who has the shared key turned on.'), s.el);
}

function foodSection(cfg, note, onSaved) {
  const s = configSection('Food data', FOOD_SPECS, cfg, note, { onSaved });
  return h('section', { class: 'admin-sec' }, h('h2', null, 'Food data'),
    h('p', { class: 'sub' }, 'DEMO_KEY is rate limited. Get a free key at api.data.gov.'), s.el);
}

function serverSection(cfg) {
  const rows = envRows(cfg.environment);
  return h('section', { class: 'admin-sec' }, h('h2', null, 'Server info'),
    h('p', { class: 'sub' }, 'These are set in your .env or compose file and need a restart to change.'),
    cfg.warnings.length ? h('ul', { class: 'warnings' }, cfg.warnings.map((w) => h('li', null, w))) : null,
    h('dl', { class: 'env' }, rows.map(([k, v]) => [h('dt', null, k), h('dd', null, v)]).flat()));
}

// ---------- users ----------

function userRow(u, me, onChange) {
  let open = false;
  let user = u;
  const li = h('li', { class: 'user' });
  const panelId = 'user-panel-' + u.id;

  async function patch(body, okText, panelStatus) {
    try {
      user = await api.adminPatchUser(user.id, body);
      onChange(user);
      changed();
      paint();
      const st = li.querySelector('.user-status');
      if (st) show(st, message(okText || 'Saved.'));
    } catch (err) { show(panelStatus, message(err.message, 'error')); }
  }

  function panel() {
    const status = h('div', { class: 'user-status', 'aria-live': 'polite' });
    const name = field('Name', { value: user.display_name || '', autocomplete: 'off' });
    const email = field('Email', { value: user.email || '', type: 'text', inputmode: 'email', autocomplete: 'off', autocapitalize: 'none' });
    const profile = h('form', { onsubmit: (e) => { e.preventDefault(); patch({ display_name: name.input.value, email: email.input.value }, 'Saved.', status); } },
      name, email, h('button', { class: 'btn', type: 'submit' }, 'Save name and email'));
    const pw = field('New password', { type: 'password', autocomplete: 'new-password', minlength: '8' });
    const reset = h('form', { onsubmit: (e) => {
      e.preventDefault();
      const bad = setupError('x', pw.input.value);
      if (bad) { show(status, message(bad, 'error')); return; }
      patch({ password: pw.input.value }, 'Password changed. They are signed out everywhere.', status);
    } }, pw, h('button', { class: 'btn', type: 'submit' }, 'Reset password'));
    const act = (label, body, okText) => h('button', { class: 'btn', type: 'button', onclick: () => patch(body, okText, status) }, label);
    const isSelf = me && me.id === user.id;
    return h('div', { class: 'user-panel', id: panelId },
      profile, reset,
      h('div', { class: 'row wrap' },
        user.admin_by_group ? null : act(user.is_admin ? 'Remove admin' : 'Make admin', { is_admin: !user.is_admin }),
        isSelf && !user.disabled ? null : act(user.disabled ? 'Enable' : 'Disable', { disabled: !user.disabled }),
        act(user.use_global_ai ? 'Turn shared Claude key off' : 'Turn shared Claude key on', { use_global_ai: !user.use_global_ai }),
        user.sso_linked ? act('Disconnect SSO', { unlink_sso: true }, 'SSO disconnected.') : null),
      user.admin_by_group ? h('p', { class: 'sub' }, 'Admin role is managed by the authentik group.') : null,
      status);
  }

  function paint() {
    clear(li);
    const badges = userBadges(user);
    li.appendChild(h('button', { class: 'item-main user-head', type: 'button', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': panelId, onclick: () => { open = !open; paint(); } },
      h('span', { class: 'item-title' }, userName(user)),
      h('span', { class: 'item-sub' }, user.email ? user.username + ' - ' + user.email : user.username),
      badges.length ? h('span', { class: 'pills' }, badges.map((b) => h('span', { class: 'pill' }, b))) : null));
    if (open) li.appendChild(panel());
  }
  paint();
  return li;
}

function addUserForm(onCreated) {
  const status = h('div', { 'aria-live': 'polite' });
  const username = field('Username', { autocomplete: 'off', autocapitalize: 'none', required: '' });
  const name = field('Name', { autocomplete: 'off' });
  const email = field('Email', { inputmode: 'email', autocomplete: 'off', autocapitalize: 'none' });
  const pass = field('Password', { type: 'password', autocomplete: 'new-password', required: '', minlength: '8' });
  const admin = h('input', { type: 'checkbox', id: 'new-admin' });
  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault();
    const bad = setupError(username.input.value, pass.input.value);
    if (bad) { show(status, message(bad, 'error')); return; }
    try {
      const u = await api.adminCreateUser({ username: username.input.value.trim(), display_name: name.input.value.trim(),
        email: email.input.value.trim(), password: pass.input.value, is_admin: admin.checked });
      form.reset();
      changed();
      onCreated(u);
      show(status, message('Added ' + userName(u) + '.'));
    } catch (err) { show(status, message(err.message, 'error')); }
  } }, username, name, email, pass,
  h('div', { class: 'switch-row' }, h('label', { for: 'new-admin' }, admin, h('span', null, 'Administrator'))),
  status, h('button', { class: 'btn primary', type: 'submit' }, 'Add user'));
  return h('details', { class: 'guide add-user' }, h('summary', null, 'Add user'), h('div', { class: 'guide-group' }, form));
}

function usersSection(me) {
  const list = h('ul', { class: 'list' });
  const body = h('div');
  let users = [];
  const paint = () => {
    clear(list);
    users.forEach((u) => list.appendChild(userRow(u, me, (nu) => { users = users.map((x) => (x.id === nu.id ? nu : x)); })));
  };
  api.adminUsers().then((r) => { users = r.users; paint(); }).catch((e) => show(body, message(e.message, 'error')));
  return h('section', { class: 'admin-sec' }, h('h2', null, 'Users'), list, body,
    addUserForm((u) => { users = users.concat([u]); paint(); }));
}

function activitySection() {
  const box = h('div');
  const load = () => api.adminLog().then((r) => {
    if (!r.entries.length) { show(box, message('Nothing yet.')); return; }
    show(box, h('ul', { class: 'list log' }, r.entries.map((e) => {
      const l = logLine(e);
      return h('li', { class: 'log-row' }, h('span', { class: 'log-meta' }, l.when + ' - ' + l.who), h('span', { class: 'log-text' }, l.text));
    })));
  }).catch((e) => show(box, message(e.message, 'error')));
  load();
  changed = load;
  return h('section', { class: 'admin-sec' }, h('h2', null, 'Activity'), box);
}

// ---------- screen ----------

export async function renderAdmin(root, ctx) {
  const me = await api.me();
  if (!me.is_admin) { ctx.go('settings', {}, true); return; }
  const cfg0 = await api.adminConfig();
  const cfgBox = h('div');
  // Rebuilds the config sections from fresh data. `where` says which one gets the note.
  function paint(cfg, where, note) {
    const repaint = (name) => (next, text) => paint(next, name, text);
    clear(cfgBox);
    cfgBox.appendChild(signInSection(cfg, where === 'signin' ? note : '', repaint('signin')));
    cfgBox.appendChild(claudeSection(cfg, where === 'claude' ? note : '', repaint('claude')));
    cfgBox.appendChild(foodSection(cfg, where === 'food' ? note : '', repaint('food')));
    cfgBox.appendChild(serverSection(cfg));
  }
  paint(cfg0);
  const users = usersSection(me);
  const activity = activitySection();
  // Sections in order: Users, Sign-in, Claude, Food data, Server info, Activity.
  root.appendChild(h('section', { class: 'screen admin' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, 'Admin'), users, cfgBox, activity));
}
