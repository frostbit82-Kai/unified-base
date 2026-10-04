// Web — Unified Base Windows demo #2: what Edge can do on Windows.
//
// Each card is one web platform feature that reaches into the OS: the GPU
// through WebGPU (Direct3D 12 underneath), Windows' speech voices, the whole
// screen through the EyeDropper, Windows' Share dialog, XInput controllers,
// the contrast themes. Every card checks for its feature first, so the page
// also runs (with honest "not here" notes) in browsers that lack one.

const $ = (id) => document.getElementById(id);
const status = (s) => { $('status').textContent = s; };

function rows(dl, pairs) {
  dl.replaceChildren(...pairs.flatMap(([k, v]) => {
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = k;
    dd.textContent = v;
    return [dt, dd];
  }));
}

// -- Platform --------------------------------------------------------------
async function platform() {
  const ua = navigator.userAgentData;
  if (!ua) {
    rows($('platform'), [['client hints', 'not supported here'],
                         ['user agent', navigator.userAgent]]);
    return;
  }
  const hi = await ua.getHighEntropyValues(
    ['platformVersion', 'architecture', 'bitness', 'fullVersionList']);
  const major = parseInt(hi.platformVersion, 10);
  const os = ua.platform !== 'Windows' ? ua.platform
    : major >= 13 ? 'Windows 11' : major > 0 ? 'Windows 10' : 'Windows 7/8.1';
  const list = hi.fullVersionList || [];
  const brand = list.find((b) => !/Not.?A.?Brand|Chromium/i.test(b.brand)) ||
    list.find((b) => b.brand === 'Chromium') || list[0] || { brand: '?', version: '?' };
  rows($('platform'), [
    ['system', `${os} (platformVersion ${hi.platformVersion})`],
    ['browser', `${brand.brand} ${brand.version}`],
    ['cpu', `${hi.architecture} ${hi.bitness}-bit · ${navigator.hardwareConcurrency} threads`],
    ['memory', navigator.deviceMemory ? `≥ ${navigator.deviceMemory} GB (bucketed)` : '?'],
    ['screen', `${screen.width}×${screen.height} css px · ` +
               `${Math.round(devicePixelRatio * 100)} % scale`],
  ]);
}

// -- Theme & accessibility -------------------------------------------------
const MEDIA = [
  ['(prefers-color-scheme: dark)', 'dark mode'],
  ['(forced-colors: active)', 'contrast theme'],
  ['(prefers-contrast: more)', 'more contrast'],
  ['(prefers-reduced-motion: reduce)', 'animations off'],
  ['(prefers-reduced-transparency: reduce)', 'transparency off'],
];

function media() {
  const ul = $('media');
  ul.replaceChildren(...MEDIA.map(([q, label]) => {
    const li = document.createElement('li');
    const mq = matchMedia(q);
    // A query this browser doesn't know parses to "not all".
    const val = mq.media === 'not all' ? 'n/a' : mq.matches ? 'yes' : 'no';
    li.innerHTML = `<span>${label}</span><b>${val}</b>`;
    return li;
  }));
}

for (const [q] of MEDIA) matchMedia(q).addEventListener('change', () => {
  media();
  status(`Windows changed a setting: ${q}`);
});

// -- WebGPU Game of Life ---------------------------------------------------
const N = 128;                 // power of two: u32 wrap-around stays a torus

// Gosper's glider gun: the first pattern found to grow forever (1970).
const GUN = [
  '........................O...........',
  '......................O.O...........',
  '............OO......OO............OO',
  '...........O...O....OO............OO',
  'OO........O.....O...OO..............',
  'OO........O...O.OO....O.O...........',
  '..........O.....O.......O...........',
  '...........O...O....................',
  '............OO......................',
];

function gliderGun(n) {
  const c = new Uint32Array(n * n);
  GUN.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === 'O') c[(y + 8) * n + x + 8] = 1;
  }));
  return c;
}

const SHADER = /* wgsl */ `
struct VOut {
  @builtin(position) pos: vec4f,
  @location(0) cell: vec2f,
};
@group(0) @binding(0) var<uniform> grid: vec2f;
@group(0) @binding(1) var<storage> cellIn: array<u32>;
@group(0) @binding(2) var<storage, read_write> cellOut: array<u32>;

@vertex fn vs(@location(0) p: vec2f, @builtin(instance_index) i: u32) -> VOut {
  let c = vec2f(f32(i % u32(grid.x)), f32(i / u32(grid.x)));
  let on = f32(cellIn[i]);
  // Dead cells collapse to a point and draw nothing.
  let pos = (p * on + 1.0) / grid - 1.0 + c / grid * 2.0;
  var o: VOut;
  o.pos = vec4f(pos.x, -pos.y, 0.0, 1.0);
  o.cell = c;
  return o;
}

@fragment fn fs(v: VOut) -> @location(0) vec4f {
  let t = v.cell / grid;
  return vec4f(0.25 + 0.6 * t.x, 0.55 + 0.4 * t.y, 1.0 - 0.5 * t.x, 1.0);
}

fn cellAt(x: u32, y: u32) -> u32 {
  let n = u32(grid.x);
  return cellIn[(y % n) * n + (x % n)];
}

@compute @workgroup_size(8, 8)
fn cs(@builtin(global_invocation_id) id: vec3u) {
  let x = id.x;
  let y = id.y;
  let n = cellAt(x + 1u, y + 1u) + cellAt(x + 1u, y) + cellAt(x + 1u, y - 1u) +
          cellAt(x, y - 1u) + cellAt(x - 1u, y - 1u) + cellAt(x - 1u, y) +
          cellAt(x - 1u, y + 1u) + cellAt(x, y + 1u);
  let i = y * u32(grid.x) + x;
  switch n {
    case 2u: { cellOut[i] = cellIn[i]; }
    case 3u: { cellOut[i] = 1u; }
    default: { cellOut[i] = 0u; }
  }
}`;

async function life() {
  const stat = $('life-stat');
  if (!navigator.gpu) {
    stat.textContent = 'WebGPU is not available in this browser.';
    return;
  }
  const adapter = await navigator.gpu.requestAdapter();
  if (!adapter) {
    stat.textContent = 'WebGPU: no adapter (GPU blocklisted or disabled).';
    return;
  }
  const device = await adapter.requestDevice();
  const ctx = $('life').getContext('webgpu');
  const format = navigator.gpu.getPreferredCanvasFormat();
  ctx.configure({ device, format, alphaMode: 'opaque' });

  const uniform = device.createBuffer({
    size: 8, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  device.queue.writeBuffer(uniform, 0, new Float32Array([N, N]));
  const bufs = [0, 1].map(() => device.createBuffer({
    size: N * N * 4, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST }));
  const quad = new Float32Array([-.8, -.8, .8, -.8, .8, .8, -.8, -.8, .8, .8, -.8, .8]);
  const vbuf = device.createBuffer({
    size: quad.byteLength, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
  device.queue.writeBuffer(vbuf, 0, quad);

  const module = device.createShaderModule({ code: SHADER });
  const S = GPUShaderStage;
  const bgl = device.createBindGroupLayout({ entries: [
    { binding: 0, visibility: S.VERTEX | S.FRAGMENT | S.COMPUTE, buffer: {} },
    { binding: 1, visibility: S.VERTEX | S.COMPUTE, buffer: { type: 'read-only-storage' } },
    { binding: 2, visibility: S.COMPUTE, buffer: { type: 'storage' } },
  ] });
  const layout = device.createPipelineLayout({ bindGroupLayouts: [bgl] });
  // Ping-pong: group k reads buffer k and writes the other one.
  const groups = [0, 1].map((k) => device.createBindGroup({ layout: bgl, entries: [
    { binding: 0, resource: { buffer: uniform } },
    { binding: 1, resource: { buffer: bufs[k] } },
    { binding: 2, resource: { buffer: bufs[1 - k] } },
  ] }));
  const render = device.createRenderPipeline({
    layout,
    vertex: { module, entryPoint: 'vs', buffers: [{ arrayStride: 8,
      attributes: [{ format: 'float32x2', offset: 0, shaderLocation: 0 }] }] },
    fragment: { module, entryPoint: 'fs', targets: [{ format }] },
  });
  const compute = device.createComputePipeline({
    layout, compute: { module, entryPoint: 'cs' } });

  let step = 0;
  let running = true;
  const seed = (cells) => device.queue.writeBuffer(bufs[step % 2], 0, cells);
  const random = () => {
    const c = new Uint32Array(N * N);
    for (let i = 0; i < c.length; i++) c[i] = Math.random() < 0.28 ? 1 : 0;
    seed(c);
  };
  random();
  $('life-random').onclick = random;
  $('life-gun').onclick = () => seed(gliderGun(N));
  $('life-pause').onclick = (e) => {
    running = !running;
    e.target.textContent = running ? 'Pause' : 'Run';
  };

  const info = adapter.info || {};
  const gpu = [info.vendor, info.architecture, info.description]
    .filter(Boolean).join(' · ') || 'adapter details withheld';
  let gens = 0;
  let t0 = performance.now();

  function frame(now) {
    const enc = device.createCommandEncoder();
    const per = running ? 2 ** ($('life-speed').value - 4) : 0;  // 1/8 … 16
    const steps = per >= 1 ? per : (Math.random() < per ? 1 : 0);
    for (let s = 0; s < steps; s++) {
      const pass = enc.beginComputePass();
      pass.setPipeline(compute);
      pass.setBindGroup(0, groups[step % 2]);
      pass.dispatchWorkgroups(N / 8, N / 8);
      pass.end();
      step++;
      gens++;
    }
    const rp = enc.beginRenderPass({ colorAttachments: [{
      view: ctx.getCurrentTexture().createView(), loadOp: 'clear',
      clearValue: { r: 0.03, g: 0.04, b: 0.07, a: 1 }, storeOp: 'store' }] });
    rp.setPipeline(render);
    rp.setVertexBuffer(0, vbuf);
    rp.setBindGroup(0, groups[step % 2]);
    rp.draw(6, N * N);
    rp.end();
    device.queue.submit([enc.finish()]);
    if (now - t0 > 1000) {
      stat.textContent = `${N}×${N} cells · ${Math.round(gens * 1000 / (now - t0))} ` +
                         `generations/s · generation ${step} · ${gpu}`;
      gens = 0;
      t0 = now;
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  device.lost.then((e) => { stat.textContent = `GPU device lost: ${e.message}`; });
}

// -- Windows voices --------------------------------------------------------
// Chromium drops a speaking utterance that nothing references: it is
// garbage-collected mid-sentence and its boundary/end events never fire.
let utterance = null;

function voices() {
  const sel = $('voice');
  if (!('speechSynthesis' in window)) {
    sel.disabled = true;
    $('voice-note').textContent = 'Speech synthesis is not available here.';
    return;
  }
  const fill = () => {
    const vs = speechSynthesis.getVoices();
    if (!vs.length) return;
    // Local first: those are Windows' own (SAPI/OneCore) voices. "Online"
    // ones are Edge's cloud voices — they send the text to a server.
    vs.sort((a, b) => b.localService - a.localService || a.name.localeCompare(b.name));
    sel.replaceChildren(...vs.map((v, i) => {
      const o = new Option(`${v.name} · ${v.lang}${v.localService ? '' : ' · online'}`, i);
      o.voice = v;
      return o;
    }));
    const local = vs.filter((v) => v.localService).length;
    $('voice-note').textContent = `${local} voice(s) installed in Windows, ` +
      `${vs.length - local} online. Online voices send the text to a speech service.`;
  };
  fill();
  speechSynthesis.addEventListener('voiceschanged', fill);

  $('speak').onclick = () => {
    speechSynthesis.cancel();
    const box = $('say');
    const text = box.textContent.replace(/\s+/g, ' ').trim();
    box.textContent = text;
    const u = utterance = new SpeechSynthesisUtterance(text);
    u.voice = sel.selectedOptions[0]?.voice || null;
    u.rate = Number($('rate').value);
    // Word boundaries come from the speech engine, so this follows the
    // voice as it actually speaks, at any rate.
    u.onboundary = (e) => {
      if (e.name !== 'word') return;
      const end = text.slice(e.charIndex).search(/\s|$/) + e.charIndex;
      box.innerHTML = '';
      box.append(text.slice(0, e.charIndex));
      const m = document.createElement('mark');
      m.textContent = text.slice(e.charIndex, end);
      box.append(m, text.slice(end));
    };
    u.onend = () => { box.textContent = text; };
    speechSynthesis.speak(u);
  };
  $('hush').onclick = () => speechSynthesis.cancel();
}

// -- Eye dropper -----------------------------------------------------------
function dropper() {
  if (!('EyeDropper' in window)) {
    $('pick').disabled = true;
    $('picked').textContent = 'EyeDropper API not available here';
    return;
  }
  $('pick').onclick = async () => {
    try {
      const { sRGBHex } = await new EyeDropper().open();
      $('swatch').style.background = sRGBHex;
      $('picked').textContent = sRGBHex;
      const li = document.createElement('li');
      li.style.background = sRGBHex;
      li.title = sRGBHex;
      $('history').prepend(li);
      while ($('history').children.length > 10) $('history').lastChild.remove();
    } catch {
      $('picked').textContent = 'cancelled';
    }
  };
}

// -- Share sheet -----------------------------------------------------------
function share() {
  const data = { title: 'Unified Base', text: 'Shared from Edge, through the ' +
                 'Windows Share dialog.', url: 'https://bomsaisoftware.com/' };
  if (!navigator.canShare?.(data)) {
    $('share').disabled = true;
    $('share-note').textContent = 'Web Share is not available here.';
    return;
  }
  $('share').onclick = async () => {
    try {
      await navigator.share(data);
      status('shared');
    } catch (e) {
      status(e.name === 'AbortError' ? 'share cancelled' : `share failed: ${e.message}`);
    }
  };
}

// -- Game controllers ------------------------------------------------------
function pads() {
  const box = $('pads');
  const intro = box.innerHTML;
  function tick() {
    const list = [...(navigator.getGamepads?.() || [])].filter(Boolean);
    if (!list.length) {
      if (box.dataset.n !== '0') { box.innerHTML = intro; box.dataset.n = '0'; }
    } else {
      box.dataset.n = String(list.length);
      box.innerHTML = list.map((p) =>
        `<div class="pad"><div class="id">${p.id.replace(/[<>&]/g, '')}</div>` +
        `<div class="btns">${p.buttons.map((b) =>
          `<i class="${b.pressed ? 'on' : ''}"></i>`).join('')}</div>` +
        p.axes.map((a) => `<div class="axis"><i style="left:${(a + 1) * 50}%"></i></div>`)
          .join('') + '</div>').join('');
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

// -- Battery ---------------------------------------------------------------
async function battery() {
  if (!navigator.getBattery) {
    rows($('battery'), [['battery', 'Battery Status API not available here']]);
    return;
  }
  const b = await navigator.getBattery();
  const mins = (s) => (Number.isFinite(s) ? `${Math.round(s / 60)} min` : '—');
  const show = () => rows($('battery'), [
    ['level', `${Math.round(b.level * 100)} %`],
    ['source', b.charging ? 'plugged in' : 'on battery'],
    b.charging && b.chargingTime === 0 ? ['charge', 'full']
      : [b.charging ? 'full in' : 'left', mins(b.charging ? b.chargingTime : b.dischargingTime)],
  ]);
  show();
  for (const ev of ['levelchange', 'chargingchange', 'chargingtimechange',
                    'dischargingtimechange']) b.addEventListener(ev, show);
}

// -- A folder, read-only ---------------------------------------------------
function folder() {
  if (!window.showDirectoryPicker) {
    $('folder').disabled = true;
    rows($('folder-stat'), [['folders', 'File System Access API not available here']]);
    return;
  }
  $('folder').onclick = async () => {
    let dir;
    try {
      dir = await showDirectoryPicker({ mode: 'read' });
    } catch {
      return;                                   // cancelled
    }
    let files = 0, dirs = 0, bytes = 0;
    const big = [];
    const t0 = performance.now();
    for await (const [name, h] of dir.entries()) {
      if (h.kind === 'directory') { dirs++; continue; }
      const f = await h.getFile();
      files++;
      bytes += f.size;
      big.push([f.size, name]);
      if (files >= 2000) break;                 // a walk, not an indexer
    }
    big.sort((a, b) => b[0] - a[0]);
    rows($('folder-stat'), [
      ['folder', dir.name],
      ['contents', `${files} files, ${dirs} folders${files >= 2000 ? ' (first 2000)' : ''}`],
      ['size', fmtBytes(bytes)],
      ['read in', `${Math.round(performance.now() - t0)} ms`],
    ]);
    $('folder-top').replaceChildren(...big.slice(0, 6).map(([size, name]) => {
      const li = document.createElement('li');
      const b = document.createElement('b');
      b.textContent = name;
      li.append(b, ` ${fmtBytes(size)}`);
      return li;
    }));
  };
}

function fmtBytes(n) {
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

// -- go --------------------------------------------------------------------
media();
voices();
dropper();
share();
pads();
for (const [name, fn] of [['platform', platform], ['WebGPU', life], ['battery', battery]]) {
  fn().catch((e) => status(`${name}: ${e.message}`));
}
folder();
status('ready');
