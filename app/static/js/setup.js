import { api } from './api.js';
import { h, field, message, show } from './dom.js';
import { setupError } from './adminutil.js';

// First-run screen. onDone(user) runs after the first administrator is created and signed in.
export function renderSetup(root, onDone) {
  const user = field('Username', { autocomplete: 'username', autocapitalize: 'none', required: '' });
  const name = field('Display name (optional)', { autocomplete: 'name' });
  const pass = field('Password', { type: 'password', autocomplete: 'new-password', required: '', minlength: '8' });
  const showPass = h('input', { type: 'checkbox', id: 'show-pass' });
  showPass.addEventListener('change', () => { pass.input.type = showPass.checked ? 'text' : 'password'; });
  const status = h('div', { 'aria-live': 'polite' });
  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault();
    const bad = setupError(user.input.value, pass.input.value);
    if (bad) { show(status, message(bad, 'error')); return; }
    show(status, null);
    try {
      const me = await api.setup({ username: user.input.value.trim(), display_name: name.input.value.trim(), password: pass.input.value });
      await onDone(me);
    } catch (err) { show(status, message(err.message, 'error')); }
  } }, user, name, pass,
  h('div', { class: 'switch-row' }, h('label', { for: 'show-pass' }, showPass, h('span', null, 'Show password'))),
  status, h('button', { class: 'btn primary', type: 'submit' }, 'Create Account'));
  root.appendChild(h('section', { class: 'screen login' }, h('h1', null, 'Macrolog'),
    h('p', { class: 'sub' }, 'Welcome to Macrolog. Create the first admin account.'), form));
}
