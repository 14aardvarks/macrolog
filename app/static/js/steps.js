// Recipe steps (the method): the numbered list on the recipe screen, and the editor used by Import Recipe, New Recipe
// and Edit Steps. Steps are notes only; they never change nutrition or logging.
import { h, clear } from './dom.js';
import { moveItem, MAX_STEP_LEN } from './util.js';

// The steps as a numbered list, or a short note when there are none.
export function stepsList(steps) {
  return steps && steps.length ? h('ol', { class: 'steps-list' }, steps.map((s) => h('li', null, s)))
    : h('p', { class: 'sub' }, 'No steps yet.');
}

// Editable steps. holder.steps (an array of text) is changed in place, so a draft keeps every edit.
// Each step has Up, Down and a remove button; Add Step appends an empty one and focuses it.
export function stepsEditor(holder) {
  if (!Array.isArray(holder.steps)) holder.steps = [];
  const list = h('ol', { class: 'steps-edit' });
  const tool = (label, aria, onclick, off) => h('button', { class: 'btn small', type: 'button', 'aria-label': aria, disabled: off, onclick }, label);
  function paint(focus) {
    clear(list);
    const n = holder.steps.length;
    holder.steps.forEach((text, i) => {
      const id = 'step-' + i;
      const area = h('textarea', { id, rows: '2', maxlength: String(MAX_STEP_LEN), autocomplete: 'off', class: 'step-text' });
      area.value = text;
      area.addEventListener('input', () => { holder.steps[i] = area.value; });
      list.appendChild(h('li', { class: 'step-row' },
        h('label', { class: 'step-num', for: id }, 'Step ' + (i + 1)),
        area,
        h('div', { class: 'row step-tools' },
          tool('Up', 'Move step ' + (i + 1) + ' up', () => move(i, -1), i === 0),
          tool('Down', 'Move step ' + (i + 1) + ' down', () => move(i, 1), i === n - 1),
          h('button', { class: 'btn small ghost', type: 'button', 'aria-label': 'Remove step ' + (i + 1),
            onclick: () => { holder.steps.splice(i, 1); paint(null); } }, 'Remove'))));
    });
    if (!n) list.appendChild(h('li', { class: 'sub step-none' }, 'No steps yet.'));
    if (focus) { const el = list.querySelector(focus); if (el) el.focus(); }
  }
  // After a move the same step keeps focus on the button that moved it, unless that button is now disabled.
  function move(i, dir) {
    holder.steps = moveItem(holder.steps, i, dir);
    const j = i + dir;
    const n = holder.steps.length;
    const btn = (dir < 0 && j > 0) || (dir > 0 && j < n - 1) ? (dir < 0 ? 1 : 2) : (dir < 0 ? 2 : 1);
    paint('.step-row:nth-child(' + (j + 1) + ') .step-tools button:nth-child(' + btn + ')');
  }
  const add = h('button', { class: 'btn', type: 'button', onclick: () => {
    holder.steps.push('');
    paint('#step-' + (holder.steps.length - 1));
  } }, 'Add Step');
  paint(null);
  return h('div', { class: 'steps-editor' }, list, add);
}
