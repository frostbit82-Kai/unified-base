// Web (Vite) — Unified Base demo
// Interactive particle field: particles chase the mouse, drift when idle.
// Pure vanilla JS on a 2D canvas — no framework, no network.

const canvas = document.getElementById('fx');
const ctx = canvas.getContext('2d');
const statsEl = document.getElementById('stats');

let width = 0;
let height = 0;
let dpr = Math.min(window.devicePixelRatio || 1, 2);

// Pointer target — starts at screen center, updates on move.
// `lastMoveAt` gates idle orbit by elapsed time instead of pointerleave:
// reparented/embedded windows fire spurious leave/out events that would
// otherwise keep snapping the swarm back to the center.
const pointer = { x: 0, y: 0, lastMoveAt: -1e9 };
const IDLE_AFTER_MS = 2500;

const HUES = [190, 205, 260, 285, 320];
const COUNT = 140;
const particles = [];

function resize() {
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = window.innerWidth;
  height = window.innerHeight;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = width + 'px';
  canvas.style.height = height + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function makeParticle() {
  const hue = HUES[(Math.random() * HUES.length) | 0];
  return {
    x: Math.random() * width,
    y: Math.random() * height,
    vx: (Math.random() - 0.5) * 0.6,
    vy: (Math.random() - 0.5) * 0.6,
    r: 1.2 + Math.random() * 2.4,
    hue,
    phase: Math.random() * Math.PI * 2,
  };
}

function seed() {
  particles.length = 0;
  for (let i = 0; i < COUNT; i++) particles.push(makeParticle());
}

let frames = 0;
let fps = 0;
let lastFpsAt = performance.now();

function tick(now) {
  frames++;
  if (now - lastFpsAt >= 500) {
    fps = Math.round((frames * 1000) / (now - lastFpsAt));
    frames = 0;
    lastFpsAt = now;
  }

  // Trail: fade previous frame instead of hard clear.
  ctx.fillStyle = 'rgba(7, 10, 18, 0.22)';
  ctx.fillRect(0, 0, width, height);

  // Idle when the mouse hasn't moved recently (time-based, not event-based).
  const tracking = now - pointer.lastMoveAt < IDLE_AFTER_MS;
  if (!tracking) {
    const t = now * 0.0004;
    pointer.x = width / 2 + Math.cos(t) * width * 0.22;
    pointer.y = height / 2 + Math.sin(t * 1.3) * height * 0.2;
  }

  ctx.globalCompositeOperation = 'lighter';

  for (const p of particles) {
    const dx = pointer.x - p.x;
    const dy = pointer.y - p.y;
    const dist2 = dx * dx + dy * dy + 40;
    const pull = 26 / dist2;

    // Attraction toward the pointer + a little swirl for character.
    p.vx += dx * pull;
    p.vy += dy * pull;
    p.vx += -dy * pull * 0.35;
    p.vy += dx * pull * 0.35;

    // Damping keeps the swarm coherent.
    p.vx *= 0.94;
    p.vy *= 0.94;

    p.x += p.vx;
    p.y += p.vy;

    // Soft wrap around edges.
    if (p.x < -20) p.x = width + 20;
    if (p.x > width + 20) p.x = -20;
    if (p.y < -20) p.y = height + 20;
    if (p.y > height + 20) p.y = -20;

    const speed = Math.hypot(p.vx, p.vy);
    const glow = 0.5 + Math.min(speed * 0.12, 0.5);
    const twinkle = 0.75 + 0.25 * Math.sin(now * 0.005 + p.phase);
    const radius = p.r * (1 + Math.min(speed * 0.05, 0.8));

    ctx.beginPath();
    ctx.fillStyle = `hsla(${p.hue}, 90%, ${58 * twinkle + 12}%, ${glow})`;
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.globalCompositeOperation = 'source-over';

  statsEl.innerHTML =
    `<b>${COUNT}</b> particles &nbsp;·&nbsp; <b>${fps || '—'}</b> fps &nbsp;·&nbsp; ` +
    (tracking ? 'tracking pointer' : 'idle orbit');

  requestAnimationFrame(tick);
}

function onMove(clientX, clientY) {
  pointer.x = clientX;
  pointer.y = clientY;
  pointer.lastMoveAt = performance.now();
}

// Listen for both pointer* and mouse* on document — some embedded/reparented
// browser windows deliver only one of the two families.
window.addEventListener('resize', resize);
document.addEventListener('pointermove', (e) => onMove(e.clientX, e.clientY));
document.addEventListener('pointerdown', (e) => onMove(e.clientX, e.clientY));
document.addEventListener('mousemove', (e) => onMove(e.clientX, e.clientY));

resize();
pointer.x = width / 2;
pointer.y = height / 2;
seed();
requestAnimationFrame(tick);
