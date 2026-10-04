# Web — Unified Base Windows demo #2: Edge on Windows

One page, nine cards. Each is a web platform feature that reaches into
Windows itself. Unified Base embeds it in Edge.

| Card | Feature | Windows underneath |
|---|---|---|
| Platform | User-Agent Client Hints | tells Windows 11 from 10 (`platformVersion` ≥ 13) — the UA string froze at "Windows NT 10.0" |
| Theme & accessibility | live `matchMedia` queries | dark mode, **contrast themes** (`forced-colors`), Animation effects; the page restyles itself too |
| WebGPU | Game of Life in a WGSL **compute shader**, 128×128, ping-pong buffers | Direct3D 12; reports generations/s and the GPU |
| Windows voices | `speechSynthesis`, word-by-word highlighting from boundary events | the voices installed in Windows (David, Zira, Mark …) |
| Eye dropper | `EyeDropper` | any pixel on any monitor, outside the browser too |
| Share sheet | `navigator.share` | Windows' own Share dialog |
| Game controllers | Gamepad API | XInput (Xbox) pads |
| Battery | Battery Status API | the laptop's battery, live |
| A folder | File System Access, read-only | the native folder picker; sizes, the largest files |

## Demonstrates
- **Feature detection, not browser sniffing** — every card checks for its
  API first and says plainly when it is missing, so the page also runs in
  Firefox or a plain Chromium.
- **A real GPU pipeline in ~80 lines** — one WGSL module with a vertex,
  fragment and compute entry point; an explicit bind-group layout so the
  read-write buffer is visible to compute only; two bind groups swapping
  input/output each generation; instanced quads that collapse dead cells to
  nothing. A 128-cell grid keeps `u32` wrap-around a clean torus.
- **One Chromium trap, handled:** an utterance nothing references can be
  garbage-collected mid-sentence, and its events stop — the speaking one is
  kept in a variable.
- **Privacy where it matters** — online voices are labelled (they send the
  text to a server); the folder walk is read-only and stops at 2000 files.

## Dependencies
- Node.js + npm (`npm install` pulls Vite).
- Microsoft Edge (ships with Windows). WebGPU needs a GPU Edge supports;
  without one the card says so.

## Run
Unified Base runs `npm run dev` and embeds Edge at the printed URL.

Manual equivalent:

```
npm install && npm run dev
```

## Files
- `index.html` — the nine cards
- `src/main.js` — one function per card, plus the WGSL shader
- `src/style.css` — dark/light/contrast-theme aware styling
