# Python — Unified Base demo #2: Mandelbrot explorer

An interactive fractal explorer in pure tkinter. Click to zoom in, right-click
to zoom out, `R` to reset, `S` to cycle palettes. The status bar shows the
center, zoom factor, iteration limit, current refinement pass, and render time.

## Demonstrates
Not animation — *staying responsive while doing slow work*:

- **Progressive refinement** — four passes (8px → 4px → 2px → 1px blocks), so a
  usable image appears in milliseconds and sharpens from there.
- **Cooperative scheduling** — each pass computes ~12 rows per `after()` tick,
  so the UI keeps handling clicks and repaints mid-render.
- **Image plumbing with no third-party libs** — pixels are packed into a PNG by
  hand (zlib + a CRC32 per chunk) and handed to `PhotoImage`, then block-scaled
  with `.zoom()`. (Tk will not read a base64 PPM — the obvious shortcut fails.)
- **Adaptive quality** — the iteration limit scales with zoom depth, and escape
  counts are gamma-curved so deep zooms don't collapse into one palette entry.
- **Interior shortcuts** — cardioid and period-2 bulb tests skip the two big
  interior regions instead of iterating them to the limit.

## Dependencies
None beyond the standard library (needs tkinter: `sudo apt install python3-tk`).

## Run
Unified Base runs this automatically. Manual equivalent:

```
python3 main.py
```

## Files
- `main.py` — everything: PNG encoder, palettes, escape-time kernel, Tk UI
