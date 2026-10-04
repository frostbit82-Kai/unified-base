// Web — Unified Base Windows demo: twin of demo_module/Linux/web-worker.
//
// Demo #1 is a canvas particle field. This one is about the browser's threading
// model: the same prime sieve run two ways, with the UI thread's own frame time
// charted live so the difference is visible rather than asserted.

import { sieve, tail } from './sieve.js';

const $ = (id) => document.getElementById(id);
const CHART_W = 600;
const CHART_H = 150;
const SAMPLES = 120;
const frames = [];            // recent frame durations, ms

// Vite resolves this URL form at build time and bundles the worker properly —
// `new Worker('./worker.js')` would break once the app is built.
const worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' });

let busy = false;
let spinAngle = 0;
let lastFrame = performance.now();
// Worst frame seen *since the current job started*. Reading the tail of
// `frames` instead would report page-load hitches as if the job caused them.
let jobWorst = 0;

const limitFor = (steps) => steps * 4_000_000;      // slider -> sieve size
const fmt = (n) => n.toLocaleString();

// -- the heartbeat ---------------------------------------------------------
// rAF measures the UI thread's real responsiveness: when something blocks it,
// the gaps between frames grow and the chart shows it directly.
let warmup = 3;               // first frames include page setup, not our work

function frame(now) {
  const dt = now - lastFrame;
  lastFrame = now;
  if (warmup > 0) {           // don't let load cost be charged to a job
    warmup--;
    requestAnimationFrame(frame);
    return;
  }
  frames.push(dt);
  if (frames.length > SAMPLES) frames.shift();
  if (busy) jobWorst = Math.max(jobWorst, dt);

  spinAngle = (spinAngle + dt * 0.28) % 360;
  $('spin').style.transform = `rotate(${spinAngle}deg)`;

  drawChart();
  requestAnimationFrame(frame);
}

function colorFor(ms) {
  return ms >= 100 ? '#ff7b72' : ms > 20 ? '#f0883e' : '#2ea043';
}

function drawChart() {
  const max = Math.max(60, ...frames);
  const bw = CHART_W / SAMPLES;
  // Rebuilding the bars as one string beats mutating 120 DOM nodes per frame.
  let svg = '';
  frames.forEach((ms, i) => {
    const h = Math.max(1, (ms / max) * (CHART_H - 8));
    svg += `<rect x="${(i * bw).toFixed(1)}" y="${(CHART_H - h).toFixed(1)}" ` +
           `width="${(bw - 0.6).toFixed(1)}" height="${h.toFixed(1)}" ` +
           `fill="${colorFor(ms)}" />`;
  });
  // 16.7 ms reference line (60 fps).
  const y = CHART_H - (16.7 / max) * (CHART_H - 8);
  svg += `<line x1="0" x2="${CHART_W}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" ` +
         `stroke="#30363d" stroke-dasharray="4 4" />`;
  $('chart').innerHTML = svg;

  const recent = frames.slice(-30);
  const avg = recent.reduce((a, b) => a + b, 0) / (recent.length || 1);
  $('fps').textContent = `${(1000 / avg).toFixed(0)} fps · worst ` +
                         `${Math.max(...frames).toFixed(0)} ms`;
}

// -- running the work ------------------------------------------------------
function showResult(where, { limit, count, ms, largest, bytes }) {
  const dl = $('result');
  dl.innerHTML = '';
  const pairs = [
    ['ran on', where],
    ['limit', fmt(limit)],
    ['primes', fmt(count)],
    ['time', `${ms.toFixed(0)} ms`],
    ['largest', largest.join(', ')],
    ['sieve buffer', bytes ? `${(bytes / 1048576).toFixed(1)} MB transferred` : 'kept in place']
  ];
  for (const [k, v] of pairs) {
    const dt = document.createElement('dt'); dt.textContent = k;
    const dd = document.createElement('dd'); dd.textContent = v;
    dl.append(dt, dd);
  }
}

function setBusy(state, note) {
  if (state) jobWorst = 0;
  busy = state;
  $('worker').disabled = state;
  $('main').disabled = state;
  $('status').textContent = note;
}

worker.onmessage = (e) => {
  const { count, ms, limit, largest, buffer } = e.data;
  const worst = jobWorst;
  showResult('worker thread', { limit, count, ms, largest, bytes: buffer.byteLength });
  $('verdict').textContent =
    `worker: UI kept moving — worst frame ${worst.toFixed(0)} ms during ${ms.toFixed(0)} ms of work`;
  setBusy(false, `worker finished in ${ms.toFixed(0)} ms`);
};

$('worker').onclick = () => {
  if (busy) return;
  setBusy(true, 'working off-thread…');
  worker.postMessage({ limit: limitFor(+$('size').value) });
};

$('main').onclick = () => {
  if (busy) return;
  const limit = limitFor(+$('size').value);
  setBusy(true, 'blocking the UI thread…');
  // Yield once so the button's disabled state actually paints before the
  // thread locks up — otherwise the freeze swallows its own feedback.
  requestAnimationFrame(() => setTimeout(() => {
    const t0 = performance.now();
    const { count, flags } = sieve(limit);
    const ms = performance.now() - t0;
    showResult('main thread', { limit, count, ms, largest: tail(flags, limit) });
    // The blocking run never yields, so no rAF fired during it: the freeze
    // is the gap the NEXT frame measures, which is ~the run time itself.
    const worst = Math.max(jobWorst, ms);
    $('verdict').textContent =
      `main thread: UI froze — one ${worst.toFixed(0)} ms frame during ${ms.toFixed(0)} ms of work`;
    setBusy(false, `main thread finished in ${ms.toFixed(0)} ms`);
  }, 0));
};

$('size').oninput = () => {
  $('sizelabel').textContent = `${fmt(limitFor(+$('size').value))} numbers`;
};

$('size').oninput();
requestAnimationFrame(frame);
// Kick off one worker run so the page has something to show — after a beat, so
// the measurement starts from a settled page rather than from first paint.
setTimeout(() => $('worker').click(), 700);
