// Pure helpers for photos on foods and recipes: the crop view math, sizes and URLs. No DOM, so node can test them
// (tests/ui/photo.test.mjs). A view is { iw, ih, w, h, zoom, ox, oy }: the image size in pixels, the frame size on screen,
// the zoom (1 = the image just covers the frame) and the image's top left corner in frame coordinates.

export const PHOTO_MAX_SIDE = 1600;  // the client sends at most this on the longest side; the server enforces it again
export const ZOOM_MAX = 4;
export const FRAMES = ['square', 'original'];
export const FRAME_LABELS = { square: 'Square', original: 'Original' };

// The served URL of a stored photo name, or null. Names are random letters, digits, - and _ with .jpg (the server checks too).
export function photoUrl(name) {
  return typeof name === 'string' && /^[A-Za-z0-9_-]{16,64}\.jpg$/.test(name) ? '/api/photos/' + name : null;
}

export function photoAlt(name) {
  const n = String(name || '').trim();
  return n ? 'Photo of ' + n : 'Photo';
}

// Scale a size so its longest side is at most max (never enlarges), as whole pixels of at least 1.
export function scaledSize(w, h, max = PHOTO_MAX_SIDE) {
  const k = Math.min(1, max / Math.max(w, h));
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) };
}

// The frame on screen for a frame kind: square, or the photo's own shape no taller than 1.25 times the width.
export function frameSize(kind, iw, ih, maxW) {
  const w0 = Math.max(1, Math.round(maxW));
  if (kind !== 'original') return { w: w0, h: w0 };
  let w = w0;
  let h = Math.round(w0 * ih / iw);
  const maxH = Math.round(w0 * 1.25);
  if (h > maxH) { h = maxH; w = Math.max(1, Math.round(h * iw / ih)); }
  return { w, h: Math.max(1, h) };
}

// The smallest scale at which the image covers the frame.
export function coverScale(iw, ih, w, h) { return Math.max(w / iw, h / ih); }

export function viewScale(v) { return coverScale(v.iw, v.ih, v.w, v.h) * v.zoom; }

const clampNum = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

// Keep the frame covered: the image may not leave a gap on any side, and the zoom stays within 1 and ZOOM_MAX.
export function clampView(v) {
  const zoom = clampNum(Number.isFinite(v.zoom) ? v.zoom : 1, 1, ZOOM_MAX);
  const s = coverScale(v.iw, v.ih, v.w, v.h) * zoom;
  return { ...v, zoom, ox: clampNum(v.ox, v.w - v.iw * s, 0), oy: clampNum(v.oy, v.h - v.ih * s, 0) };
}

// A centered view at zoom 1 for an image and a frame.
export function startView(iw, ih, w, h) {
  const s = coverScale(iw, ih, w, h);
  return clampView({ iw, ih, w, h, zoom: 1, ox: (w - iw * s) / 2, oy: (h - ih * s) / 2 });
}

export function panView(v, dx, dy) { return clampView({ ...v, ox: v.ox + dx, oy: v.oy + dy }); }

// Zoom to a new level keeping the point (cx, cy) of the frame over the same spot of the image (the frame center by default).
export function zoomView(v, zoom, cx = v.w / 2, cy = v.h / 2) {
  const s0 = viewScale(v);
  const z = clampNum(zoom, 1, ZOOM_MAX);
  const s1 = coverScale(v.iw, v.ih, v.w, v.h) * z;
  const ix = (cx - v.ox) / s0;
  const iy = (cy - v.oy) / s0;
  return clampView({ ...v, zoom: z, ox: cx - ix * s1, oy: cy - iy * s1 });
}

// The same view in a new frame (Square to Original): zoom kept, centered on the same image point.
export function reframe(v, w, h) {
  const s0 = viewScale(v);
  const ix = (v.w / 2 - v.ox) / s0;
  const iy = (v.h / 2 - v.oy) / s0;
  const s1 = coverScale(v.iw, v.ih, w, h) * v.zoom;
  return clampView({ ...v, w, h, ox: w / 2 - ix * s1, oy: h / 2 - iy * s1 });
}

// The part of the image the frame shows, in image pixels (whole numbers inside the image).
export function cropRect(v) {
  const s = viewScale(v);
  const sx = clampNum(Math.round(-v.ox / s), 0, v.iw - 1);
  const sy = clampNum(Math.round(-v.oy / s), 0, v.ih - 1);
  const sw = clampNum(Math.round(v.w / s), 1, v.iw - sx);
  const sh = clampNum(Math.round(v.h / s), 1, v.ih - sy);
  return { sx, sy, sw, sh };
}

// The distance between two pointers, for pinch zoom.
export function pointerDistance(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
