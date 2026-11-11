import { h } from './dom.js';
import { GUIDE, GUIDE_TITLE } from './guide.js';

// A native collapsible block, closed by default. Text only, built with createElement.
export function renderGuide() {
  return h('details', { class: 'guide' },
    h('summary', null, GUIDE_TITLE),
    GUIDE.map((g) => h('div', { class: 'guide-group' },
      h('h3', null, g.heading),
      h('ul', null, g.bullets.map((b) => h('li', null, b))))));
}
