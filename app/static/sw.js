// Caches the static shell only. Never touches /api or /auth.
const CACHE = 'macrolog-shell-v57';
const SHELL = ['/', '/style.css', '/manifest.webmanifest', '/icon.svg', '/icon-192.png', '/icon-512.png', '/icon-maskable-512.png', '/apple-touch-icon.png', '/js/app.js', '/js/api.js', '/js/util.js', '/js/dom.js',
  '/js/picker.js', '/js/scan.js', '/js/ai.js', '/js/notice.js', '/js/foodform.js', '/js/chart.js', '/js/guide.js', '/js/guide-view.js',
  '/js/setup.js', '/js/admin.js', '/js/adminutil.js', '/js/claudekey.js', '/js/saved.js', '/js/micros.js', '/js/recipe.js', '/js/tablemodel.js', '/js/daytable.js', '/js/refresh.js', '/js/recipeimport.js', '/js/recipeflow.js', '/js/recipes.js', '/js/steps.js', '/js/servingsize.js', '/js/update.js', '/js/recipelog.js', '/js/cooking.js'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

// A new worker waits until the page asks (the Update Available banner), so nobody is switched mid-use.
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.indexOf('/api/') === 0 || url.pathname.indexOf('/auth/') === 0) return;
  // Network first so updates arrive; the cache only answers when offline.
  e.respondWith(fetch(req).then((res) => {
    if (res.ok && res.type === 'basic') { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  }).catch(() => caches.match(req).then((hit) => hit || (req.mode === 'navigate' ? caches.match('/') : Response.error()))));
});
