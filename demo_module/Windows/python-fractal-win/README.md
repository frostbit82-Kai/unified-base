# Python — Unified Base Windows demo: Mandelbrot explorer

The Windows twin of `demo_module/Linux/python-fractal`: the same interactive
fractal explorer, the same code. Click to zoom in, right-click to zoom out,
`R` to reset, `S` to cycle palettes.

## Why a twin
Load both and run them side by side: the Linux one through WSL (its tab's
**Runs on ▸ Linux only**, drawn by VcXsrv), this one natively. Same Python,
same Tk, two window systems — compare render times in the status lines.

## What differs on Windows
Two lines, both at the bottom of `main.py`:

- **Per-monitor DPI awareness** (`SetProcessDpiAwareness(2)`, before the
  first Tk window). Without it Windows bitmap-stretches the whole window at
  125 % and up, and the fractal goes soft. The canvas is then scaled by the
  real DPI, so it covers the same area it does at 100 %.
- **Consolas** for the status line: Tk's `monospace` family exists on Linux
  only, and Windows quietly falls back to a proportional font.

Everything else — progressive refinement, cooperative `after()` scheduling,
the hand-rolled PNG encoder — is described in the Linux demo's README.

## Dependencies
None beyond the standard library (tkinter ships with python.org's Python).

## Run
Unified Base runs this automatically. Manual equivalent:

```
py main.py
```

## Files
- `main.py` — the explorer
