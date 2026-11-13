import test from 'node:test';
import assert from 'node:assert/strict';
import { RECIPE_PURGE_DAYS, UNDO_MS, purgeDays, deleteRecipeConfirm, deleteForeverConfirm, deletedNoticeText, restoredText, purgedText,
  deletedHint, deletedTitle, daysLeftText, sortDeleted, withoutDeleted } from '../../app/static/js/trash.js';

const texts = () => [deleteRecipeConfirm('Toast'), deleteForeverConfirm('Toast'), deletedNoticeText('Toast'), restoredText('Toast'),
  purgedText('Toast'), deletedHint(), deletedTitle(2), daysLeftText(3)];

test('defaults: 30 days kept, the Undo notice about 10 seconds', () => {
  assert.equal(RECIPE_PURGE_DAYS, 30);
  assert.equal(UNDO_MS, 10000);
  assert.equal(purgeDays(14), 14);
  for (const bad of [undefined, null, 0, -3, 'x', NaN]) assert.equal(purgeDays(bad), 30);
});

test('confirm and notice texts', () => {
  assert.equal(deleteRecipeConfirm('Toast'),
    'Delete This Recipe? "Toast" moves to Recently Deleted for 30 days, then is removed for good. Entries already in your log stay.');
  assert.equal(deleteForeverConfirm('Toast'), 'Delete Forever? "Toast" is removed for good and cannot be restored. Entries already in your log stay.');
  assert.equal(deletedNoticeText('Toast'), '"Toast" moved to Recently Deleted.');
  assert.equal(restoredText('Toast'), '"Toast" is back in your recipes.');
  assert.equal(purgedText('Toast'), '"Toast" was deleted for good.');
  assert.match(deletedHint(), /^Deleted recipes stay here for 30 days, then are removed for good\. /);
  assert.match(deletedHint(7), /for 7 days/);
  assert.equal(deletedTitle(2), 'Recently Deleted (2)');
  for (const t of texts()) assert.ok(!t.includes('—'), 'em dash: ' + t);
});

test('daysLeftText', () => {
  assert.equal(daysLeftText(30), '30 days left');
  assert.equal(daysLeftText(1), '1 day left');
  assert.equal(daysLeftText(0), 'Last day');
  assert.equal(daysLeftText(-2), 'Last day');
  assert.equal(daysLeftText(undefined), 'Last day');
  assert.equal(daysLeftText(2.7), '2 days left');
});

test('sortDeleted keeps newest first without changing the input, withoutDeleted drops one', () => {
  const list = [{ id: 1, deleted_at: '2026-11-01T10:00:00+00:00' }, { id: 2, deleted_at: '2026-11-12T10:00:00+00:00' },
    { id: 3, deleted_at: '2026-11-12T10:00:00+00:00' }];
  assert.deepEqual(sortDeleted(list).map((m) => m.id), [3, 2, 1]);
  assert.deepEqual(list.map((m) => m.id), [1, 2, 3]);
  assert.deepEqual(sortDeleted(null), []);
  assert.deepEqual(withoutDeleted(list, 2).map((m) => m.id), [1, 3]);
  assert.deepEqual(withoutDeleted(undefined, 2), []);
});
