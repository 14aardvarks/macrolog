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

let detectorPromise = null;
// Resolves to async (video|img) => digits string or null. Rejects only if neither decoder is available.
function getDetector() {
  if (!detectorPromise) {
    detectorPromise = nativeDetector().then((d) => d || zxingDetector()).catch((e) => { detectorPromise = null; throw e; });
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
  } }, input, h('button', { class: 'btn', type: 'submit' }, 'Look up'));
  return h('div', null, form, err);
}

// Scan screen. ctx.lookup(code) handles a found code. Returns a cleanup function that stops the camera.
export function renderScan(root, ctx) {
  let stream = null;
  let timer = null;
  const status = h('div', { 'aria-live': 'polite' });
  const video = h('video', { class: 'video', playsinline: '', muted: '', hidden: '', 'aria-label': 'Camera view' });
  video.muted = true;
  const startBtn = h('button', { class: 'btn primary', type: 'button', onclick: start }, 'Start camera');
  const stopBtn = h('button', { class: 'btn', type: 'button', hidden: '', onclick: stop }, 'Stop camera');
  const fileIn = h('input', { type: 'file', accept: 'image/*', capture: 'environment', class: 'visually-hidden', onchange: onFile });
  const fileBtn = h('label', { class: 'btn' }, 'Take or choose a photo', fileIn);

  root.appendChild(h('section', { class: 'screen' },
    h('h1', null, 'Scan a barcode'),
    h('p', { class: 'sub' }, 'The camera only starts when you tap Start camera.'),
    video, status,
    h('div', { class: 'row wrap' }, startBtn, stopBtn, fileBtn),
    h('h2', null, 'Or type the digits'),
    barcodeForm(found)));

  function stop() {
    clearTimeout(timer);
    timer = null;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    video.srcObject = null;
    video.hidden = true;
    stopBtn.hidden = true;
    startBtn.hidden = false;
  }
  function found(code) { stop(); ctx.lookup(code); }

  async function start() {
    const md = navigator.mediaDevices;
    if (!md || !md.getUserMedia || window.isSecureContext === false) {
      show(status, message('The camera needs a secure (HTTPS) page. Take a photo instead, or type the digits.', 'error'));
      return;
    }
    show(status, message('Starting camera...'));
    let detect;
    try { detect = await getDetector(); } catch (e) {
      show(status, message('Barcode reading is not available in this browser. Type the digits instead.', 'error'));
      return;
    }
    try {
      stream = await md.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
      video.srcObject = stream;
      video.hidden = false;
      stopBtn.hidden = false;
      startBtn.hidden = true;
      await video.play();
      show(status, message('Point the camera at the barcode.'));
      loop(detect);
    } catch (e) {
      stop();
      const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
      show(status, message((denied ? 'Camera access was blocked.' : 'Could not start the camera.') +
        ' Take a photo instead, or type the digits.', 'error'));
    }
  }

  function loop(detect) {
    timer = setTimeout(async () => {
      if (!stream) return;
      if (!root.isConnected) { stop(); return; }
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
      else show(status, message('No barcode found in that photo. Try again closer, or type the digits.', 'error'));
    } catch (e) {
      show(status, message(e.message + '. You can still type the digits.', 'error'));
    }
    fileIn.value = '';
  }
  return stop;
}
