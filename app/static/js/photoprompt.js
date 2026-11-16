// The in app prompt after logging a recipe that has no photo: a polite bar above the bottom nav with Take Photo and Dismiss.
// The server decides when to ask (POST /api/meals/{id}/log answers photo_prompt true once per recipe, only with Allow Photos on)
// and has already recorded it, so closing the bar in any way never brings it back. It stays about PROMPT_MS, pauses while the
// pointer or keyboard focus is on it, and Escape closes it. Only one is up at a time. Same look as the Undo notice.
import { h } from './dom.js';
import { choosePhoto, photosOn } from './photo.js';
import { photoPromptText } from './recipecards.js';

export const PROMPT_MS = 15000;
let current = null;

export function closePhotoPrompt() {
  if (current) current.close();
}

// rec: { id, name }. Does nothing while photos are off.
export function showPhotoPrompt(rec) {
  if (!photosOn() || !rec) return null;
  closePhotoPrompt();
  const text = h('span', { class: 'undo-text' }, photoPromptText(rec.name));
  const takeBtn = h('button', { class: 'btn', type: 'button', onclick: take }, 'Take Photo');
  const closeBtn = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Dismiss', onclick: () => close() }, '×');
  const bar = h('div', { class: 'undo-bar photo-prompt', role: 'status', 'aria-live': 'polite' }, text, takeBtn, closeBtn);
  let timer = null;
  let left = PROMPT_MS;
  let started = 0;
  let hovered = false;
  let focused = false;
  const start = () => { if (timer || hovered || focused) return; started = Date.now(); timer = setTimeout(() => close(), left); };
  const pause = () => { if (!timer) return; clearTimeout(timer); timer = null; left = Math.max(2000, left - (Date.now() - started)); };
  bar.addEventListener('mouseenter', () => { hovered = true; pause(); });
  bar.addEventListener('mouseleave', () => { hovered = false; start(); });
  bar.addEventListener('focusin', () => { focused = true; pause(); });
  bar.addEventListener('focusout', (e) => { if (!bar.contains(e.relatedTarget)) { focused = false; start(); } });
  bar.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); close(true); } });
  const me = { close };
  function close(refocus) {
    if (timer) clearTimeout(timer);
    timer = null;
    const had = bar.contains(document.activeElement);
    bar.remove();
    if (current === me) { current = null; document.body.classList.remove('has-undo'); }
    if ((refocus || had) && document.getElementById('main')) document.getElementById('main').focus({ preventScroll: true });
  }
  async function take() {
    takeBtn.disabled = true;
    pause();
    try {
      const saved = await choosePhoto({ id: rec.id, name: rec.name, photo: null }, 'meal', (t) => { text.textContent = t; }, true);
      if (saved) { text.textContent = 'Photo saved.'; takeBtn.remove(); left = 4000; closeBtn.focus(); } else { text.textContent = photoPromptText(rec.name); takeBtn.disabled = false; }
    } catch (e) {
      text.textContent = e.message;
      takeBtn.disabled = false;
    }
    start();
  }
  current = me;
  document.body.classList.add('has-undo');
  document.body.appendChild(bar);
  start();
  return me;
}
