import { api } from './api.js';
import { h, clear, field, message, show, extLink } from './dom.js';
import { claudeStatusLines, personalBody, personalHints, ssoView, PRICING_URL, PRICING_LINK_TEXT, PRICE_SAMPLE } from './adminutil.js';
import { dollarText, sentence, fullClaudeRows, fullClaudePriceNote, fullClaudeWarning } from './util.js';

let seq = 0;
// A labelled box with its hint read out by screen readers.
function hinted(label, attrs, hint, link) {
  const id = 'ck-' + (++seq);
  const f = field(label, { ...attrs, 'aria-describedby': id });
  const box = h('div', { class: 'hinted' }, f, h('p', { class: 'sub field-hint', id }, hint, link ? [' See the ', extLink(PRICING_URL, PRICING_LINK_TEXT), '.'] : null));
  box.input = f.input;
  return box;
}

// The Claude block in Settings: which key is in use, plus the personal key, limit, model and prices. The key is write-only.
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
    const hint = personalHints(ai);
    const cap = hinted('Your monthly request limit', { inputmode: 'numeric', value: String(ai.personal_cap) }, hint.cap);
    const model = hinted('Model', { autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', value: ai.personal_model || '', maxlength: '100' }, hint.model);
    const price = (label, v, text, sample) => hinted(label, { inputmode: 'decimal', autocomplete: 'off', value: v == null ? '' : String(v), placeholder: sample }, text, true);
    const priceIn = price('Input Price (USD per Million Tokens)', ai.personal_price_in, hint.priceIn, PRICE_SAMPLE.in);
    const priceOut = price('Output Price (USD per Million Tokens)', ai.personal_price_out, hint.priceOut, PRICE_SAMPLE.out);
    const save = async (e) => {
      e.preventDefault();
      const r = personalBody({ key: key.input.value, cap: cap.input.value, model: model.input.value,
        priceIn: priceIn.input.value, priceOut: priceOut.input.value }, ai);
      if (r.error) { show(status, message(r.error, 'error')); return; }
      const body = r.body;
      if (!body) { show(status, message('Nothing to change.')); return; }
      await run(() => api.putAiKey(body), body.key ? 'Saved. Your key is stored and never shown again.' : 'Saved.');
    };
    const remove = h('button', { class: 'btn', type: 'button', onclick: () => run(() => api.deleteAiKey(), 'Your key was removed.') }, 'Remove Key');
    box.appendChild(h('div', null,
      lines.map((t) => h('p', { class: 'sub' }, t)),
      h('form', { onsubmit: save }, key,
        h('p', { class: 'sub' }, 'A personal key bills your own Anthropic account and is used instead of the shared key.'),
        cap, h('p', { class: 'sub' }, 'The model and prices apply only while your own key is in use.'), model, priceIn, priceOut,
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

// The hint under Full Claude Use. It states the default first.
export const FULL_CLAUDE_HELP = [
  'Off by default.',
  sentence('When on, Claude runs on its own where it helps: Auto-Match After Import set to Search becomes Search Then Claude, '
    + 'a search with no result asks Claude for an estimate, a barcode that is not found offers a Claude estimate, '
    + 'Refresh Nutrients lets Claude fill blanks the source left, and a recipe import, text or photo, sends and matches with Claude without asking'),
  sentence('Each step needs a Claude key and the feature allowed by the administrator, otherwise it is skipped quietly'),
  sentence('The monthly request limit always applies, and the other Claude steps still follow Confirm before using Claude'),
].join(' ');

// Settings, Full Claude Use (settings.full_claude, per user, off by default). Saved at once. ai: /api/ai/status for the
// cost table; save(on) stores it and resolves the new settings.
export function renderFullClaude(settings, ai, save) {
  const box = h('input', { type: 'checkbox', id: 'full-claude', checked: settings.full_claude === true,
    'aria-describedby': 'full-claude-help full-claude-costs full-claude-warning' });
  const status = h('div', { 'aria-live': 'polite' });
  box.addEventListener('change', async () => {
    const want = box.checked;
    box.disabled = true;
    try { await save(want); show(status, message(want ? 'Full Claude Use is on.' : 'Full Claude Use is off.')); }
    catch (err) { box.checked = !want; show(status, message(err.message, 'error')); }
    box.disabled = false;
  });
  const costs = ai && ai.action_costs;
  const rows = fullClaudeRows(costs);
  const table = rows.length ? h('table', { class: 'cost-table', id: 'full-claude-costs' },
    h('caption', null, 'Estimated Cost per Action'),
    h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Action'), h('th', { scope: 'col' }, 'Estimate'))),
    h('tbody', null, rows.map((r) => h('tr', null, h('th', { scope: 'row' }, r.label), h('td', null, r.text))))) : null;
  return h('div', { class: 'switch-row full-claude' },
    h('label', { for: 'full-claude' }, box, h('span', null, 'Full Claude Use')),
    h('p', { class: 'sub', id: 'full-claude-help' }, FULL_CLAUDE_HELP),
    table, h('p', { class: 'sub', id: table ? null : 'full-claude-costs' }, fullClaudePriceNote(costs)),
    h('p', { class: 'badge full-claude-warning', id: 'full-claude-warning' }, fullClaudeWarning(ai)), status);
}
