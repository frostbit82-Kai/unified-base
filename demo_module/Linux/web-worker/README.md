# Web — Unified Base demo #2: workers & the main thread

The same prime sieve, run two ways, with the UI thread's own frame time charted
live. Press **Run in worker** and the chart stays green; press **Run on main
thread** and the page freezes solid for the duration. The slider sets how much
work (up to 48 million numbers).

## Demonstrates
Demo #1 is a canvas particle field. This one is the browser's threading model:

- **Module Web Worker** — declared as `new Worker(new URL('./worker.js',
  import.meta.url), { type: 'module' })`, the form Vite can bundle (a bare
  `'./worker.js'` string breaks in a production build).
- **Transferable ArrayBuffers** — the sieve's `Uint8Array` buffer is *handed
  over* rather than copied; ~23 MB moves with zero copying and the worker's view
  is detached afterwards.
- **Shared workload module** — `sieve.js` is imported by both threads, so the
  two paths run byte-identical code and only the thread differs.
- **Honest measurement** — frame times are sampled with `requestAnimationFrame`,
  the first frames are discarded as page-load cost, and each verdict reports
  only the worst frame *within its own job window*.
- **Live SVG** — 120 bars rebuilt per frame as one string, cheaper than mutating
  120 DOM nodes, with a dashed 60 fps reference line.

## Dependencies
- Node.js + npm (`npm install` pulls Vite)

## Run
Unified Base runs `npm run dev` and embeds a browser at the printed URL.

Manual equivalent:

```
npm install && npm run dev
```

## Files
- `index.html` — markup, loaded by Vite as the entry
- `src/main.js` — rAF heartbeat, chart, both run paths
- `src/worker.js` — the worker thread
- `src/sieve.js` — the workload, shared by both threads
- `src/style.css` — styling
