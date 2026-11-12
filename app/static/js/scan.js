import { h, show, message, loadImage } from './dom.js';
import { digitsOnly, fitSize } from './util.js';

const FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e'];
let zxingPromise = null;

// Load the vendored decoder only when the browser has no usable BarcodeDetector.
function loadZXing() {
  if (window.ZXing) return Promise.resolve(window.ZXing);
  if (!zxingPromise) {
    zxingPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = '/vendor/zxing-library.min.js';
      s.onload = () => (window.ZXing ? resolve(window.ZXing) : reject(new Error('Barcode decoder missing')));
      s.onerror = () => { zxingPromise = null; reject(new Error('Barcode decoder could not load')); };
      document.head.appendChild(s);
    });
  }
  return zxingPromise;
}

async function nativeDetector() {
  if (!('BarcodeDetector' in window)) return null;
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = FORMATS.filter((f) => supported.indexOf(f) >= 0);
    if (!formats.length) return null;
    const d = new window.BarcodeDetector({ formats });
    return async (src) => { const r = await d.detect(src); return r.length ? r[0].rawValue : null; };
  } catch (e) { return null; }
}

function sourceSize(src) {
  return { w: src.videoWidth || src.naturalWidth || src.width, h: src.videoHeight || src.naturalHeight || src.height };
}

async function zxingDetector() {
  const Z = await loadZXing();
  const reader = new Z.MultiFormatReader();
  const hints = new Map();
  hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E]);
  hints.set(Z.DecodeHintType.TRY_HARDER, true);
  reader.setHints(hints);
  const canvas = document.createElement('canvas');
  return async (src) => {
    const s = sourceSize(src);
    const f = fitSize(s.w, s.h, 1280);
    canvas.width = f.w;
    canvas.height = f.h;
    canvas.getContext('2d').drawImage(src, 0, 0, f.w, f.h);
    try {
      const bmp = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(canvas)));
      return reader.decode(bmp).getText();
    } catch (e) { return null; }  // NotFoundException and friends mean no barcode in this frame
  };
}

// Labels are not always printed upright: when the straight read finds nothing, read the frame turned a quarter turn
// (1D barcodes read the same forwards and backwards, so 0 and 90 degrees cover upside down and sideways too).
function withRotation(detect) {
  const canvas = document.createElement('canvas');
  return async (src) => {
    const code = await detect(src);
    if (code) return code;
    const s = sourceSize(src);
    const f = fitSize(s.w, s.h, 1280);
    canvas.width = f.h;
    canvas.height = f.w;
    const ctx = canvas.getContext('2d');
    ctx.save();
    ctx.translate(f.h, 0);
    ctx.rotate(Math.PI / 2);
    ctx.drawImage(src, 0, 0, f.w, f.h);
    ctx.restore();
    return detect(canvas);
  };
}

let detectorPromise = null;
// Resolves to async (video|img) => digits string or null. Rejects only if neither decoder is available.
function getDetector() {
  if (!detectorPromise) {
    detectorPromise = nativeDetector().then((d) => d || zxingDetector()).then(withRotation).catch((e) => { detectorPromise = null; throw e; });
  }
  return detectorPromise;
}

// Typed digits form, also used on the Add screen.
export function barcodeForm(onCode) {
  const input = h('input', { type: 'text', inputmode: 'numeric', autocomplete: 'off', placeholder: 'Digits under the barcode', 'aria-label': 'Barcode digits' });
  const err = h('div', { 'aria-live': 'polite' });
  const form = h('form', { class: 'row', onsubmit: (e) => {
    e.preventDefault();
    const code = digitsOnly(input.value);
    if (code.length < 8) { show(err, message('Enter at least 8 digits.', 'error')); return; }
    show(err, null);
    onCode(code);
  } }, input, h('button', { class: 'btn', type: 'submit' }, 'Look Up'));
  return h('div', null, form, err);
}

// Scan screen. ctx.lookup(code) handles a found code. Returns a cleanup function that stops the camera.
// Leaving the screen (Back, a nav tab, any other navigation) runs the cleanup, which stops every track.
export function renderScan(root, ctx, opts = {}) {
  let stream = null;
  let timer = null;
  let closed = false;
  const status = h('div', { 'aria-live': 'polite' });
  const video = h('video', { class: 'video', playsinline: '', muted: '', 'aria-label': 'Camera view' });
  video.muted = true;
  const camBox = h('div', { class: 'cam', hidden: '' }, video);
  const startBtn = h('button', { class: 'btn', type: 'button', hidden: '', onclick: start }, 'Try Camera Again');  // only shown after a failed start
  const fileIn = h('input', { type: 'file', accept: 'image/*', class: 'visually-hidden', onchange: onFile });
  const fileBtn = h('label', { class: 'btn' }, 'Upload a Photo', fileIn);
  const below = h('div', { class: 'row wrap' }, startBtn, fileBtn);

  // The photo button sits over the camera view while the camera runs, and below the message otherwise.
  function placePhotoBtn(overCamera) {
    fileBtn.classList.toggle('cam-over', overCamera);
    if (overCamera) camBox.appendChild(fileBtn); else below.appendChild(fileBtn);
  }

  root.appendChild(h('section', { class: 'screen' },
    h('div', { class: 'bar' }, h('button', { class: 'btn ghost', type: 'button', onclick: ctx.back }, 'Back')),
    h('h1', null, 'Scan Barcode'),
    camBox, status, below,
    h('h2', null, 'Type the Digits'),
    barcodeForm(found)));

  function stop() {
    clearTimeout(timer);
    timer = null;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    camBox.hidden = true;
    placePhotoBtn(false);
  }
  // Cleanup for navigation. After this a late camera grant is released at once.
  function dispose() { closed = true; stop(); }
  function found(code) { stop(); ctx.lookup(code); }

  async function start() {
    const md = navigator.mediaDevices;
    if (!md || !md.getUserMedia || window.isSecureContext === false) {
      show(status, message('The camera needs a secure (HTTPS) page. Take a photo instead, or type the digits below.', 'error'));
      return;
    }
    startBtn.hidden = true;
    show(status, message('Starting camera...'));
    // Called synchronously from the Scan Barcode tap (go and render run up to here without awaiting), so iOS and Chrome
    // still count it as a user gesture. Ask for the camera first, then load the barcode reader.
    let got;
    try {
      // A sharper picture helps a lot with glare and small print, so ask for up to 1080p (the browser picks the closest).
      got = await md.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
    } catch (e) {
      if (closed) return;
      const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
      const none = e && (e.name === 'NotFoundError' || e.name === 'OverconstrainedError');
      startBtn.hidden = false;
      show(status, message((denied ? 'Camera access was blocked. Allow it in the browser settings to scan.' : none ? 'No camera was found.' : 'Could not start the camera.') +
        ' Take a photo instead, or type the digits below.', 'error'));
      return;
    }
    if (closed) { got.getTracks().forEach((t) => t.stop()); return; }  // the screen was left while the browser asked
    stream = got;
    keepFocused(got);
    let detect;
    try { detect = await getDetector(); } catch (e) {
      stop();
      if (closed) return;
      show(status, message('Barcode reading is not available in this browser. Type the digits below.', 'error'));
      return;
    }
    if (closed || !stream) { stop(); return; }
    try {
      video.srcObject = stream;
      camBox.hidden = false;
      placePhotoBtn(true);
      await video.play();
      show(status, null);
      loop(detect);
    } catch (e) {
      stop();
      if (closed) return;
      show(status, message('Could not start the camera. Take a photo instead, or type the digits below.', 'error'));
      startBtn.hidden = false;
    }
  }

  // Continuous autofocus where the camera offers it, so the barcode stays sharp when the phone moves.
  function keepFocused(s) {
    const track = s.getVideoTracks()[0];
    const modes = track && track.getCapabilities ? (track.getCapabilities().focusMode || []) : [];
    if (modes.includes('continuous')) track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {});
  }

  function loop(detect) {
    timer = setTimeout(async () => {
      if (!stream) return;
      if (!root.isConnected) { dispose(); return; }
      let code = null;
      try { if (video.readyState >= 2) code = await detect(video); } catch (e) { code = null; }
      if (code && stream) found(code); else if (stream) loop(detect);
    }, 250);
  }

  async function onFile() {
    const file = fileIn.files && fileIn.files[0];
    if (!file) return;
    show(status, message('Reading the photo...'));
    try {
      const detect = await getDetector();
      const code = await detect(await loadImage(file));
      if (code) found(code);
      else show(status, message('No barcode found in that photo. Try again closer, or type the digits below.', 'error'));
    } catch (e) {
      show(status, message(e.message + '. You can still type the digits.', 'error'));
    }
    fileIn.value = '';
  }
  if (opts.autostart) start();
  return dispose;
}
