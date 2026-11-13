// The Undo notice after deleting a recipe: a polite status bar above the bottom nav with Undo and Dismiss. It stays about
// UNDO_MS, pauses while the pointer or keyboard focus is on it, and Escape closes it. Only one is up at a time. The recipe is
// also kept in Recently Deleted on the Recipes tab, so Undo is not the only way back.
import { h } from './dom.js';
import { api } from './api.js';
import { UNDO_MS, deletedNoticeText, restoredText } from './trash.js';

let current = null;

export function closeUndo() {
  if (current) current.close();
}

// rec: { id, name }. onRestored(meal) runs after a successful restore (repaint the screen).
export function showUndo(rec, onRestored) {
  closeUndo();
  const text = h('span', { class: 'undo-text' }, deletedNoticeText(rec.name));
  const undoBtn = h('button', { class: 'btn', type: 'button', onclick: undo }, 'Undo');
  const closeBtn = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Dismiss', onclick: () => close() }, '×');
  const bar = h('div', { class: 'undo-bar', role: 'status', 'aria-live': 'polite' }, text, undoBtn, closeBtn);
  let timer = null;
  let left = UNDO_MS;
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
  async function undo() {
    undoBtn.disabled = true;
    pause();
    try {
      const meal = await api.restoreMeal(rec.id);
      text.textContent = restoredText(rec.name);
      undoBtn.remove();
      left = 4000;
      if (!bar.contains(document.activeElement)) focused = false;
      closeBtn.focus();
      if (onRestored) await onRestored(meal);
    } catch (e) {
      text.textContent = e.message;
      undoBtn.disabled = false;
    }
    start();
  }
  current = me;
  document.body.classList.add('has-undo');
  document.body.appendChild(bar);
  start();
  return me;
}
