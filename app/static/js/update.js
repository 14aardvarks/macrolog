import { h } from './dom.js';

// Update Available banner. A new service worker waits until the person taps Reload; nothing happens on a fresh install.

// Registers the worker and offers an update when a new one is installed and waiting, or when a new one took over
// without being asked (an older worker that skipped waiting by itself). sw is navigator.serviceWorker.
// show(reload) puts the banner up once; reload() reloads the page. Returns { check } to look for a newer worker.
export async function watchUpdates(sw, show, reload, url = '/sw.js') {
  const hadController = !!sw.controller;
  let offered = false;
  let reloading = false;
  const offer = (worker) => {
    if (offered) return;
    offered = true;
    show(() => {
      reloading = true;
      if (worker) {
        worker.postMessage({ type: 'SKIP_WAITING' });
        setTimeout(reload, 2500);  // in case the worker never reports the change
      } else reload();
    });
  };
  sw.addEventListener('controllerchange', () => {
    if (reloading) reload();
    else if (hadController) offer(null);
  });
  const reg = await sw.register(url);
  const watch = (worker) => {
    if (!worker) return;
    if (worker.state === 'installed') { if (sw.controller) offer(worker); return; }
    worker.addEventListener('statechange', () => { if (worker.state === 'installed' && sw.controller) offer(worker); });
  };
  watch(reg.waiting);
  reg.addEventListener('updatefound', () => watch(reg.installing));
  return { check: () => reg.update().catch(() => {}) };
}

// The banner element: a polite status line with a Reload button.
export function updateBanner(onReload) {
  const btn = h('button', { class: 'btn', type: 'button', onclick: () => { btn.disabled = true; onReload(); } }, 'Reload');
  return h('div', { class: 'update-banner', role: 'status' }, h('span', null, 'Update Available'), btn);
}

// Browser wiring, called once from app.js.
export function startUpdates() {
  const sw = navigator.serviceWorker;
  if (!sw) return;
  const go = async () => {
    try {
      const w = await watchUpdates(sw, (reload) => { document.body.insertBefore(updateBanner(reload), document.body.firstChild); }, () => location.reload());
      document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') w.check(); });
    } catch (e) { /* no service worker, nothing to update */ }
  };
  if (document.readyState === 'complete') go(); else window.addEventListener('load', go);
}
