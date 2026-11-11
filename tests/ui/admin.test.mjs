import test from 'node:test';
import assert from 'node:assert/strict';
import {
  sourceLabel, setupError, userBadges, claudeStatusLines, parseCap, keyBody, ssoView, buildChanges, SIGNIN_SPECS, CLAUDE_SPECS,
  envRows, testLine, logLine, initialValue,
} from '../../app/static/js/adminutil.js';

test('source labels', () => {
  assert.equal(sourceLabel('database'), 'Saved here');
  assert.equal(sourceLabel('environment'), 'From environment');
  assert.equal(sourceLabel('default'), 'Default');
  assert.equal(sourceLabel('x'), '');
});

test('setup validation', () => {
  assert.match(setupError('', 'longenough'), /username/);
  assert.match(setupError('a', 'short'), /8 characters/);
  assert.equal(setupError('a', 'longenough'), '');
});

test('badges', () => {
  assert.deepEqual(userBadges({ is_admin: true, disabled: true, sso_linked: true, personal_key_set: true }), ['Admin', 'Disabled', 'SSO', 'Own Claude key']);
  assert.deepEqual(userBadges({}), []);
});

test('claude status lines', () => {
  const base = { key_source: 'personal', personal_used_this_month: 3, personal_cap: 50, used_this_month: 9, cap: 100, can_use_global: true };
  assert.match(claudeStatusLines(base, true)[0], /personal key.*3 of 50/);
  assert.match(claudeStatusLines({ ...base, key_source: 'global' }, true)[0], /shared key.*9 of 100/);
  const none = claudeStatusLines({ ...base, key_source: null, can_use_global: false }, false);
  assert.match(none[0], /No Claude key/);
  assert.ok(none.includes('The shared key is turned off for your account.'));
  assert.ok(claudeStatusLines({ ...base, key_source: null, can_use_global: false }, true).includes('There is no shared key on this server.'));
});

test('cap and key body', () => {
  assert.deepEqual(parseCap(' 25 '), { ok: true, value: 25 });
  assert.equal(parseCap('0').ok, false);
  assert.equal(parseCap('1.5').ok, false);
  assert.equal(parseCap('10001').ok, false);
  assert.equal(keyBody('', 100, 100), null);
  assert.deepEqual(keyBody(' sk-x ', 100, 100), { key: 'sk-x' });
  assert.deepEqual(keyBody('', 20, 100), { cap: 20 });
});

test('sso view', () => {
  assert.equal(ssoView({ oidc: false }, {}).state, 'off');
  assert.equal(ssoView({ oidc: true }, { sso_linked: false }).state, 'connect');
  assert.equal(ssoView({ oidc: true, local: true }, { sso_linked: true, has_password: true }).canDisconnect, true);
  const nopw = ssoView({ oidc: true, local: true }, { sso_linked: true, has_password: false });
  assert.equal(nopw.canDisconnect, false);
  assert.ok(nopw.hint);
  assert.equal(ssoView({ oidc: true, local: false }, { sso_linked: true, has_password: true }).canDisconnect, false);
});

const items = {
  local_login: { value: true, source: 'default' }, oidc_allow_signup: { value: false, source: 'default' },
  oidc_name: { value: 'Authentik', source: 'database' }, oidc_issuer: { value: '', source: 'default' },
  oidc_client_id: { value: '', source: 'default' }, oidc_client_secret: { set: true, source: 'database' },
  ai_global_key: { set: false, source: 'default' }, ai_model: { value: '', source: 'default' },
  ai_monthly_cap: { value: 100, source: 'default' }, ai_price_in_per_mtok: { value: null, source: 'default' },
  ai_price_out_per_mtok: { value: 5, source: 'database' },
};

test('buildChanges sends only changed keys', () => {
  const st = (o) => o;
  assert.deepEqual(buildChanges(SIGNIN_SPECS, items, {}).changes, {});
  const r = buildChanges(SIGNIN_SPECS, items, {
    local_login: st({ value: true }), oidc_allow_signup: st({ value: true }), oidc_name: st({ value: 'Authentik' }),
    oidc_issuer: st({ value: ' https://a.example/ ' }), oidc_client_secret: st({ value: '' }),
  });
  assert.deepEqual(r.changes, { oidc_allow_signup: true, oidc_issuer: 'https://a.example/' });
});

test('buildChanges revert and clear', () => {
  const r = buildChanges(SIGNIN_SPECS, items, { oidc_name: { revert: true }, oidc_client_secret: { clear: true, value: '' } });
  assert.deepEqual(r.changes, { oidc_name: null, oidc_client_secret: '' });
  const s = buildChanges(SIGNIN_SPECS, items, { oidc_client_secret: { value: 'newsecret' } });
  assert.deepEqual(s.changes, { oidc_client_secret: 'newsecret' });
  assert.deepEqual(buildChanges(SIGNIN_SPECS, items, { oidc_client_secret: { revert: true } }).changes, { oidc_client_secret: null });
});

test('buildChanges numbers', () => {
  assert.deepEqual(buildChanges(CLAUDE_SPECS, items, { ai_monthly_cap: { value: '250' } }).changes, { ai_monthly_cap: 250 });
  assert.match(buildChanges(CLAUDE_SPECS, items, { ai_monthly_cap: { value: '2.5' } }).error, /whole number/);
  assert.deepEqual(buildChanges(CLAUDE_SPECS, items, { ai_price_in_per_mtok: { value: '3' } }).changes, { ai_price_in_per_mtok: '3' });
  assert.deepEqual(buildChanges(CLAUDE_SPECS, items, { ai_price_out_per_mtok: { value: '' } }).changes, { ai_price_out_per_mtok: '' });
  assert.match(buildChanges(CLAUDE_SPECS, items, { ai_price_in_per_mtok: { value: 'abc' } }).error, /number/);
  assert.equal(initialValue(CLAUDE_SPECS[4], items.ai_price_out_per_mtok), '5');
  assert.equal(initialValue(CLAUDE_SPECS[0], items.ai_global_key), '');
});

test('env rows never show a secret', () => {
  const rows = envRows({ SECRET_KEY: { set: true }, DB_PATH: '/d/m.db', PUBLIC_URL: '', TRUST_PROXY: false, COOKIE_SECURE: true, note: 'x' });
  assert.deepEqual(rows, [['SECRET_KEY', 'Set'], ['DB_PATH', '/d/m.db'], ['PUBLIC_URL', 'Not set'], ['TRUST_PROXY', 'Off'], ['COOKIE_SECURE', 'On']]);
});

test('test line and log line', () => {
  assert.equal(testLine(null), 'No successful test yet.');
  assert.match(testLine({ at: '2026-01-02T03:04:05Z', matches_current: true }), /^Last good test .*\.$/);
  assert.match(testLine({ at: '2026-01-02T03:04:05Z', matches_current: false }), /before the current settings/);
  const l = logLine({ at: 'bad', admin_username: null, action: 'config.update', target: 'ai_model', detail: '' });
  assert.deepEqual(l, { when: 'bad', who: 'system', text: 'config.update - ai_model' });
});

test('sign-in specs include the admin group settings with hints', () => {
  const keys = SIGNIN_SPECS.map((s) => s.key);
  assert.ok(keys.includes('oidc_admin_group') && keys.includes('oidc_groups_claim') && keys.includes('oidc_user_group'));
  const spec = SIGNIN_SPECS.find((s) => s.key === 'oidc_admin_group');
  assert.match(spec.hint, /Leave empty to manage admins manually/);
  assert.match(SIGNIN_SPECS.find((s) => s.key === 'oidc_allow_signup').hint, /application bindings/);
});
