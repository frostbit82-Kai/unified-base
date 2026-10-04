# C — Unified Base Windows demo: paint on plain Win32

A small paint program in one C file and the Win32 API: pen, line,
rectangle, ellipse, flood fill and eraser; any colour from the Choose Colour
dialog; open and save BMP files; copy and paste through the clipboard;
eight levels of undo.

| Keys | |
|---|---|
| `Ctrl+N` `Ctrl+O` `Ctrl+S` | new, open, save |
| `Ctrl+Z` `Ctrl+C` `Ctrl+V` | undo, copy, paste |
| `P` `L` `R` `E` `F` `X` | pen, line, rectangle, ellipse, fill, eraser |
| `[` `]` | thinner, wider |

## Demonstrates
- **Common controls, themed**: push-like radio buttons for the tools, a
  trackbar, a status bar. `app.rc` embeds a manifest asking for Common
  Controls 6 — without it every control draws in the Windows 95 style — and
  for per-monitor DPI awareness.
- **Common dialogs**: `ChooseColorW`, `GetOpenFileNameW`,
  `GetSaveFileNameW`. When embedded, Unified Base shows them as usual: their
  owner is the embedded window, which disables just this app.
- **GDI**: a 1600×1000 memory DC is the picture. Wide pens are geometric,
  with round caps; `ExtFloodFill` fills; a shape still being dragged is
  drawn only into the back buffer over the picture, so the rubber band
  never flickers and never touches the image until you let go.
- **BMP by hand**: a `BITMAPFILEHEADER`, a `BITMAPINFOHEADER`, rows padded
  to 4 bytes, `GetDIBits` — and `LoadImageW` to read one back.
- **The clipboard**: `CF_BITMAP` in and out; the clipboard owns what it is
  given.
- **Accelerators**: one `ACCEL` table, `TranslateAcceleratorW` in the
  message loop.
- **No menu bar — on purpose.** Unified Base embeds a window by making it
  a *child* window, and a Win32 child can't have a menu: its `HMENU` slot
  is reinterpreted as the control ID. So every command is a button and a
  key, and the button row wraps when the pane is narrow.

## Build
`paint.exe` ships prebuilt (like `win32-native/app.exe`), so it runs with no
compiler installed. To rebuild after changing `main.c`:

- **zig** (`winget install -e --id zig.zig`, or the tarball on Linux) and
  `make` (`winget install -e --id ezwinports.make`). One `zig cc` recipe
  cross-compiles to Windows from either OS, `.rc` file included.

With no compiler, the Makefile's failed compile is ignored *only while
`paint.exe` exists*, and the launcher runs the prebuilt one.

## Run
Unified Base runs `make`, then `paint.exe`. On Linux, Wine runs it.

Check, no window: `paint.exe --selftest` — draws a rectangle, flood-fills
inside it, undoes, saves a BMP, reloads it and compares pixels.

## Files
- `main.c` — everything
- `app.rc`, `app.manifest` — Common Controls 6 and DPI awareness
- `Makefile` — the zig recipe
- `paint.exe` — prebuilt
