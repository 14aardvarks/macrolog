import { api } from './api.js';
import { h } from './dom.js';
import { noticeLines } from './util.js';

// Ask before anything goes to Claude. Resolves true to go ahead, false to cancel.
// opts: { what: "1 photo of a label", images: 1 } for a label read, or { what, chars: text length } for a text lookup. With "Confirm before using Claude" off it resolves true at once.
// opts.query: extra status parameters for the estimate (recipe_chars, recipe_images or match_rows).
// Built in the page (no window.confirm). Reuse it for any other Claude action.
export async function confirmClaude(settings, opts) {
  if (settings && settings.confirm_ai === false) return true;
  let st = null;
  try { st = await api.aiStatus(opts.chars != null ? null : opts.images || 1, opts.chars, opts.query); } catch (e) { st = null; }
  const info = st ? noticeLines(st, opts.what) : { blocked: false, lines: ['Sends ' + opts.what + ' to Claude.', 'Cost not available.'], warn: '' };
  return new Promise((resolve) => {
    const previous = document.activeElement;
    const done = (ok) => {
      document.removeEventListener('keydown', onKey, true);
      overlay.remove();
      if (previous && previous.focus) previous.focus();
      resolve(ok);
    };
    const cancel = h('button', { class: 'btn', type: 'button', onclick: () => done(false) }, info.blocked ? 'Back' : 'Cancel');
    const go = info.blocked ? null : h('button', { class: 'btn primary', type: 'button', onclick: () => done(true) }, 'Continue');
    const box = h('div', { class: 'notice', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'notice-title' },
      h('h2', { id: 'notice-title' }, info.blocked ? 'No Claude Requests Left' : 'Ask Claude?'),
      info.lines.map((t) => h('p', null, t)),
      info.warn ? h('p', { class: 'badge' }, info.warn) : null,
      h('div', { class: 'row' }, cancel, go));
    const overlay = h('div', { class: 'overlay' }, box);
    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); done(false); return; }
      if (e.key !== 'Tab') return;
      const items = [cancel, go].filter(Boolean);
      const i = items.indexOf(document.activeElement);
      e.preventDefault();
      items[(i + (e.shiftKey ? items.length - 1 : 1)) % items.length].focus();
    }
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(overlay);
    (go || cancel).focus();
  });
}
