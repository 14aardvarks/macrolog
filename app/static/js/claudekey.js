import { api } from './api.js';
import { h, clear, field, message, show } from './dom.js';
import { claudeStatusLines, parseCap, keyBody, ssoView } from './adminutil.js';
import { dollarText } from './util.js';

// The Claude block in Settings: which key is in use, plus the personal key and limit. The key is write-only.
export function renderClaudeSection(ai0, useGlobal) {
  const box = h('div');
  const status = h('div', { 'aria-live': 'polite' });
  let ai = ai0;

  function paint() {
    clear(box);
    const lines = claudeStatusLines(ai, useGlobal);
    if (ai.key_source === 'global' && ai.price_known && ai.cost_this_month != null) lines[0] += ' About ' + dollarText(ai.cost_this_month) + ' so far.';
    const key = field('Personal Claude key', { type: 'password', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false',
      placeholder: ai.personal_key_set ? 'Saved' : 'Paste your key' });
    const cap = field('Your monthly request limit', { inputmode: 'numeric', value: String(ai.personal_cap) });
    const save = async (e) => {
      e.preventDefault();
      const c = parseCap(cap.input.value);
      if (!c.ok) { show(status, message(c.error, 'error')); return; }
      const body = keyBody(key.input.value, c.value, ai.personal_cap);
      if (!body) { show(status, message('Nothing to change.')); return; }
      await run(() => api.putAiKey(body), body.key ? 'Saved. Your key is stored and never shown again.' : 'Saved.');
    };
    const remove = h('button', { class: 'btn', type: 'button', onclick: () => run(() => api.deleteAiKey(), 'Your key was removed.') }, 'Remove key');
    box.appendChild(h('div', null,
      lines.map((t) => h('p', { class: 'sub' }, t)),
      h('form', { onsubmit: save }, key, cap,
        h('p', { class: 'sub' }, 'A personal key bills your own Anthropic account and is used instead of the shared key.'),
        h('div', { class: 'row wrap' }, h('button', { class: 'btn primary', type: 'submit' }, 'Save'), ai.personal_key_set ? remove : null)),
      status));
  }

  async function run(call, okText) {
    try {
      ai = await call();
      paint();
      show(status, message(okText));
    } catch (err) { show(status, message(err.message, 'error')); }
  }
  paint();
  return box;
}

// The Sign-in block in Settings. Connect is a plain link; Disconnect posts to the server.
export function renderSignIn(cfg, me0) {
  const box = h('div');
  const status = h('div', { 'aria-live': 'polite' });
  let me = me0;
  function paint() {
    clear(box);
    const v = ssoView(cfg, me);
    if (v.state === 'off') return;
    box.appendChild(h('h2', null, 'Sign-in'));
    if (v.state === 'connect') {
      box.appendChild(h('p', { class: 'sub' }, 'Link your account to ' + (cfg.oidc_name || 'single sign-on') + ' to sign in without a password.'));
      box.appendChild(h('a', { class: 'btn', href: '/auth/oidc/link' }, 'Connect SSO'));
    } else {
      const off = h('button', { class: 'btn', type: 'button', disabled: !v.canDisconnect, 'aria-describedby': v.hint ? 'sso-hint' : null, onclick: async () => {
        try { me = await api.unlinkSso(); paint(); show(status, message('SSO disconnected.')); } catch (err) { show(status, message(err.message, 'error')); }
      } }, 'Disconnect');
      box.appendChild(h('p', { class: 'sub' }, 'Connected to SSO.'));
      box.appendChild(off);
      if (v.hint) box.appendChild(h('p', { class: 'sub', id: 'sso-hint' }, v.hint));
    }
    box.appendChild(status);
  }
  paint();
  return box;
}
