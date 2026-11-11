import { h, svg } from './dom.js';
import { macroBarParts, macroBarLabel, macroShares, percentParts, donutSegments, arcPath, fmtNum, MACRO_KEYS } from './util.js';

const LABELS = { carbs: 'Carbs', protein: 'Protein', fat: 'Fat' };

function ring(cx, cy, rOut, rIn, shares, cls) {
  if (!shares) return svg('circle', { cx, cy, r: (rOut + rIn) / 2, fill: 'none', 'stroke-width': rOut - rIn, class: 'ring-empty' });
  return svg('g', { class: cls }, donutSegments(shares).map((s) => svg('path', { d: arcPath(cx, cy, rOut, rIn, s.start, s.end), class: 'seg seg-' + s.key })));
}

// Calorie share donut for the day (outer ring) and the goal split (inner ring), with a text legend.
// d: the /api/day payload.
export function splitChart(d) {
  const eaten = macroShares(d.totals);
  const goal = macroShares(d.targets);
  const pe = percentParts(eaten);
  const pg = percentParts(goal);
  const kcal = fmtNum(d.totals.kcal, 0);
  const goalKcal = fmtNum(d.targets.kcal, 0);
  const art = svg('svg', { viewBox: '-4 -4 168 168', class: 'donut', role: 'img',
    'aria-label': kcal + ' of ' + goalKcal + ' calories. ' + (eaten ? 'Outer ring logged, inner ring goal' : 'Nothing logged yet') },
  ring(80, 80, 76, 50, eaten, 'ring-eaten'), ring(80, 80, 42, 30, goal, 'ring-goal'),
  svg('text', { x: 80, y: 67, class: 'donut-unit', 'text-anchor': 'middle' }, 'Goal'),
  svg('text', { x: 80, y: 86, class: 'donut-num', 'text-anchor': 'middle' }, goalKcal),
  svg('text', { x: 80, y: 97, class: 'donut-unit', 'text-anchor': 'middle' }, 'kcal'));
  const goalNum = Number(d.targets.kcal);
  const loggedPct = goalNum > 0 ? ' (' + Math.round(Number(d.totals.kcal) / goalNum * 100) + '%)' : '';
  const rows = MACRO_KEYS.map((k) => h('li', null,
    h('span', { class: 'sw sw-' + k, 'aria-hidden': 'true' }),
    h('div', { class: 'lg-main' }, h('span', { class: 'lg-name' }, LABELS[k]),
      h('span', null, eaten ? pe[k] + '% (' + fmtNum(d.totals[k], 0) + ' g)' : '-')),
    h('div', { class: 'lg-goal' }, 'Goal ' + pg[k] + '%')));
  return h('div', { class: 'split' }, art,
    h('div', { class: 'legend' },
      h('p', { class: 'legend-head' }, 'Logged: ' + kcal + ' kcal' + loggedPct),
      h('ul', null, rows)));
}

// Thin stacked bar of the calorie share from carbs, protein and fat. Returns null when there is nothing to show.
// Update an existing bar in place with fillMacroBar.
export function macroBar(g) {
  const bar = h('span', { class: 'macro-bar', role: 'img' });
  return fillMacroBar(bar, g) ? bar : null;
}

export function fillMacroBar(bar, g) {
  const parts = macroBarParts(g);
  bar.hidden = !parts;
  while (bar.firstChild) bar.removeChild(bar.firstChild);
  if (!parts) { bar.removeAttribute('aria-label'); return false; }
  bar.setAttribute('aria-label', macroBarLabel(parts));
  MACRO_KEYS.forEach((k) => { if (parts[k] > 0) bar.appendChild(h('span', { class: 'mb mb-' + k, style: 'width:' + parts[k] + '%' })); });
  return true;
}
