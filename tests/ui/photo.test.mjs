import test from 'node:test';
import assert from 'node:assert/strict';
import { photoUrl, photoAlt, scaledSize, frameSize, coverScale, startView, clampView, panView, zoomView, reframe, cropRect, viewScale,
  pointerDistance, PHOTO_MAX_SIDE, ZOOM_MAX, FRAMES, FRAME_LABELS } from '../../app/static/js/photomath.js';

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, a + ' != ' + b);

test('photoUrl accepts only stored names', () => {
  const ok = 'Ab_cd-EF0123456789xyzQ.jpg';
  assert.equal(photoUrl(ok), '/api/photos/' + ok);
  for (const bad of [null, '', 'x.jpg', '../../etc/passwd', 'a'.repeat(30) + '.png', 'a/' + 'b'.repeat(30) + '.jpg', 'a'.repeat(30) + '.jpg?x=1', 42]) {
    assert.equal(photoUrl(bad), null, String(bad));
  }
});

test('photoAlt names the item', () => {
  assert.equal(photoAlt('Banana Bread'), 'Photo of Banana Bread');
  assert.equal(photoAlt('  '), 'Photo');
  assert.equal(photoAlt(null), 'Photo');
});

test('scaledSize keeps the longest side at most 1600 and never enlarges', () => {
  assert.equal(PHOTO_MAX_SIDE, 1600);
  assert.deepEqual(scaledSize(4000, 3000), { w: 1600, h: 1200 });
  assert.deepEqual(scaledSize(3000, 4000), { w: 1200, h: 1600 });
  assert.deepEqual(scaledSize(800, 600), { w: 800, h: 600 });
  assert.deepEqual(scaledSize(10000, 1), { w: 1600, h: 1 });
  assert.deepEqual(scaledSize(500, 250, 100), { w: 100, h: 50 });
});

test('frameSize: square, or the photo shape no taller than 1.25 widths', () => {
  assert.deepEqual(frameSize('square', 4000, 3000, 300), { w: 300, h: 300 });
  assert.deepEqual(frameSize('original', 4000, 3000, 400), { w: 400, h: 300 });
  assert.deepEqual(frameSize('original', 1000, 3000, 400), { w: 167, h: 500 });
  assert.deepEqual(FRAMES, ['square', 'original']);
  assert.equal(FRAME_LABELS.square, 'Square');
});

test('startView covers the frame, centered', () => {
  const v = startView(400, 200, 100, 100);
  near(coverScale(400, 200, 100, 100), 0.5);
  near(viewScale(v), 0.5);
  near(v.ox, -50);
  near(v.oy, 0);
  assert.deepEqual(cropRect(v), { sx: 100, sy: 0, sw: 200, sh: 200 });
});

test('panView never leaves a gap', () => {
  let v = startView(400, 200, 100, 100);
  v = panView(v, 1000, 1000);
  near(v.ox, 0);
  near(v.oy, 0);
  assert.deepEqual(cropRect(v), { sx: 0, sy: 0, sw: 200, sh: 200 });
  v = panView(v, -1000, 0);
  near(v.ox, -100);
  assert.deepEqual(cropRect(v), { sx: 200, sy: 0, sw: 200, sh: 200 });
});

test('zoomView keeps the point under the pinch and stays within 1 and ZOOM_MAX', () => {
  const v = startView(400, 400, 100, 100);  // scale 0.25
  const z = zoomView(v, 2);  // around the center
  near(viewScale(z), 0.5);
  assert.deepEqual(cropRect(z), { sx: 100, sy: 100, sw: 200, sh: 200 });
  const corner = zoomView(v, 2, 0, 0);
  assert.deepEqual(cropRect(corner), { sx: 0, sy: 0, sw: 200, sh: 200 });
  assert.equal(zoomView(v, 99).zoom, ZOOM_MAX);
  assert.equal(zoomView(v, 0.1).zoom, 1);
  assert.equal(clampView({ ...v, zoom: NaN }).zoom, 1);
});

test('reframe keeps the same center of the photo', () => {
  const v = zoomView(startView(400, 300, 100, 100), 2);
  const r = reframe(v, 100, 75);
  const a = cropRect(v);
  const b = cropRect(r);
  near(a.sx + a.sw / 2, b.sx + b.sw / 2, 1.01);
  near(a.sy + a.sh / 2, b.sy + b.sh / 2, 1.01);
  near(b.sw / b.sh, 100 / 75, 0.02);
});

test('cropRect always stays inside the photo', () => {
  for (const [iw, ih] of [[1, 1], [3000, 17], [17, 3000], [1601, 900]]) {
    for (const zoom of [1, 2.5, ZOOM_MAX]) {
      const v = zoomView(startView(iw, ih, 320, 320), zoom);
      const r = cropRect(panView(v, 12345, -12345));
      assert.ok(r.sx >= 0 && r.sy >= 0 && r.sw >= 1 && r.sh >= 1);
      assert.ok(r.sx + r.sw <= iw && r.sy + r.sh <= ih, JSON.stringify([iw, ih, zoom, r]));
    }
  }
});

test('pointerDistance', () => {
  assert.equal(pointerDistance({ x: 0, y: 0 }, { x: 3, y: 4 }), 5);
});
