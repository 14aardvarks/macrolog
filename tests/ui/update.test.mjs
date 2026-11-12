import test from 'node:test';
import assert from 'node:assert/strict';
import { watchUpdates } from '../../app/static/js/update.js';

// A tiny stand-in for navigator.serviceWorker and its registration.
function fake({ controller = null, waiting = null } = {}) {
  const swL = {};
  const regL = {};
  const reg = { waiting, installing: null, updates: 0,
    addEventListener: (t, f) => { regL[t] = f; }, update: async () => { reg.updates++; } };
  const sw = { controller, register: async () => reg, addEventListener: (t, f) => { swL[t] = f; } };
  return { sw, reg, swL, regL };
}
function worker(state) {
  const l = {};
  return { state, sent: [], addEventListener: (t, f) => { l[t] = f; }, postMessage(m) { this.sent.push(m); }, set(s) { this.state = s; l.statechange(); } };
}

test('a fresh install shows nothing', async () => {
  const f = fake();
  let shown = 0;
  await watchUpdates(f.sw, () => { shown++; }, () => {});
  const w = worker('installing');
  f.reg.installing = w;
  f.regL.updatefound();
  w.set('installed');
  f.swL.controllerchange();  // the first worker claiming the page
  assert.equal(shown, 0);
});

test('a worker installed while another controls the page offers a reload, once', async () => {
  const f = fake({ controller: {} });
  let shown = 0;
  let reload;
  let reloads = 0;
  await watchUpdates(f.sw, (r) => { shown++; reload = r; }, () => { reloads++; });
  const w = worker('installing');
  f.reg.installing = w;
  f.regL.updatefound();
  assert.equal(shown, 0);
  w.set('installed');
  w.set('installed');
  assert.equal(shown, 1);
  reload();
  assert.deepEqual(w.sent, [{ type: 'SKIP_WAITING' }]);
  assert.equal(reloads, 0);
  f.swL.controllerchange();
  assert.equal(reloads, 1);
});

test('a worker already waiting at load is offered', async () => {
  const w = worker('installed');
  const f = fake({ controller: {}, waiting: w });
  let shown = 0;
  await watchUpdates(f.sw, () => { shown++; }, () => {});
  assert.equal(shown, 1);
});

test('a waiting worker with no controller (first visit) is not offered', async () => {
  const f = fake({ waiting: worker('installed') });
  let shown = 0;
  await watchUpdates(f.sw, () => { shown++; }, () => {});
  assert.equal(shown, 0);
});

test('a new worker that took over by itself offers a reload that just reloads', async () => {
  const f = fake({ controller: {} });
  let reload;
  let reloads = 0;
  await watchUpdates(f.sw, (r) => { reload = r; }, () => { reloads++; });
  f.swL.controllerchange();
  assert.equal(typeof reload, 'function');
  reload();
  assert.equal(reloads, 1);
});

test('check asks the registration for a newer worker', async () => {
  const f = fake({ controller: {} });
  const w = await watchUpdates(f.sw, () => {}, () => {});
  await w.check();
  assert.equal(f.reg.updates, 1);
});
