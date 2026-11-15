// A three dot (or any) menu button: a real button (aria-haspopup, aria-expanded, aria-controls) that opens a list of menuitems
// below it, or above it near the bottom of the window. Arrow keys, Home and End move, Escape and Tab close, and Escape returns
// focus to the button. Used by the recipe cards and the ingredient rows (v77). Only one menu is open at a time.
import { h } from './dom.js';
import { menuMove } from './recipecards.js';

let openMenu = null;  // the close function of the menu that is open

export function closeMenus() { if (openMenu) openMenu(false); }

// host: the element that gets class menu-open while the list shows (lifts it above its neighbours). items: [{ key, label, danger? }].
// label: the button's accessible name. onPick(key) runs after the menu closed. opts: { btnClass, wrapClass, face (button content),
// describedBy }.
export function menuButton(host, items, label, onPick, opts) {
  const o = opts || {};
  const id = 'menu-' + Math.random().toString(36).slice(2, 9);
  const btn = h('button', { class: o.btnClass || 'card-menu-btn', type: 'button', 'aria-haspopup': 'menu', 'aria-expanded': 'false', 'aria-controls': id,
    'aria-label': label, 'aria-describedby': o.describedBy || null, title: o.title || 'More Actions' },
  o.face || h('span', { class: 'dots', 'aria-hidden': 'true' }, h('span'), h('span'), h('span')));
  const list = h('ul', { class: 'card-menu', role: 'menu', id, 'aria-label': label, hidden: true });
  items.forEach((it) => list.appendChild(h('li', { role: 'none' }, h('button', { type: 'button', role: 'menuitem', tabindex: '-1',
    class: 'card-menu-item' + (it.key === 'delete' || it.danger ? ' danger-text' : ''), onclick: () => { close(false); onPick(it.key); } }, it.label))));
  const buttons = () => Array.prototype.slice.call(list.querySelectorAll('[role=menuitem]'));
  function outside(e) { if (!list.contains(e.target) && e.target !== btn && !btn.contains(e.target)) close(false); }
  function close(focusBtn) {
    if (list.hidden) return;
    list.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    host.classList.remove('menu-open');
    document.removeEventListener('pointerdown', outside, true);
    if (openMenu === close) openMenu = null;
    if (focusBtn) btn.focus();
  }
  function open(at) {
    if (openMenu) openMenu(false);
    list.hidden = false;
    host.classList.add('menu-open');
    btn.setAttribute('aria-expanded', 'true');
    const r = btn.getBoundingClientRect();
    list.classList.toggle('up', window.innerHeight - r.bottom < list.offsetHeight + 72);  // room above the bottom nav
    document.addEventListener('pointerdown', outside, true);
    openMenu = close;
    const b = buttons();
    (at === 'last' ? b[b.length - 1] : b[0]).focus();
  }
  btn.addEventListener('click', () => (list.hidden ? open('first') : close(true)));
  btn.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); open(e.key === 'ArrowUp' ? 'last' : 'first'); }
  });
  list.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); return; }
    if (e.key === 'Tab') { close(false); return; }
    const b = buttons();
    const next = menuMove(e.key, b.indexOf(document.activeElement), b.length);
    if (next != null) { e.preventDefault(); b[next].focus(); }
  });
  return h('div', { class: o.wrapClass || 'card-menu-wrap' }, btn, list);
}
