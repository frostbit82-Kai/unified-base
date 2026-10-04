# Web — Unified Base Windows demo: workers & the main thread

The Windows twin of `demo_module/Linux/web-worker`: the same prime sieve run
in a Web Worker and on the main thread, with the UI thread's frame time
charted live. **Run in worker** keeps the chart green; **Run on main thread**
freezes the page for the duration.

## Why a twin
On Linux the page runs in Chromium; here Unified Base embeds **Microsoft
Edge** (`--app` mode, a throwaway profile, no sign-in or sync). Same code,
same Vite, two engines' builds and two schedulers — load both and compare
the frame-time chart and the sieve's run time. The code is unchanged apart
from the title; the Linux README explains workers, transferable
ArrayBuffers and the measurement.

## Dependencies
- Node.js + npm (`winget install -e --id OpenJS.NodeJS`; the tab's Install
  button offers it). `npm install` pulls Vite.
- Microsoft Edge (ships with Windows).

## Run
Unified Base runs `npm run dev` and embeds Edge at the printed URL.

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
