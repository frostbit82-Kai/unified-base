# Ruby — Unified Base Windows demo: L-system plotter on Win32

The Windows twin of `demo_module/Linux/ruby-lsystem`: pick one of five
Lindenmayer systems (Koch snowflake, dragon curve, Sierpinski arrowhead,
fractal plant, Hilbert curve) and drag the depth slider. The status line
reports the grown string's length, the segment count and the draw time.

## What differs on Windows
The L-system half of `main.rb` — the systems table, `expand`, `segments`,
`fit` and `--selftest` — is the Linux file's, unchanged. The window is not:

- **No Tk.** The `tk` gem is a C extension: on Windows it needs RubyInstaller's
  MSYS2 devkit and Tcl/Tk headers to build. This twin needs nothing but Ruby,
  because it talks to Win32 directly through **Fiddle** (Ruby's own FFI, in
  the standard library).
- **A window procedure that is a Ruby block.** `Fiddle::Importer#bind` turns
  the block into a C function pointer for `RegisterClassExW`. Fiddle runs it
  with its own `self`, and a Ruby exception must never unwind into user32,
  so the block reaches the plotter through a local and rescues everything.
- **Real Windows controls**: a `COMBOBOX` and a `msctls_trackbar32`, themed.
  `ruby.exe` has no Common Controls 6 manifest, so at startup the script
  builds an *activation context* from `app.manifest` and activates it before
  comctl32 loads — the loader then picks the themed v6 from WinSxS.
- **GDI in bulk.** Each change is drawn once into an offscreen bitmap; the
  whole curve goes out as one `PolyPolyline` per colour band, with points
  packed by `Array#pack('l*')`. A 16k-segment dragon is three native calls.
  `WM_PAINT` only copies the bitmap.
- Per-monitor DPI aware, so it is sharp at 125 %.

## Dependencies
- Ruby 3.x for Windows (`winget install -e --id RubyInstallerTeam.Ruby.3.4`).
  No gems.

## Run
Unified Base runs this automatically (`ruby main.rb`). Windows-only; on
Linux it points you to the Tk original.

Logic check, no window: `ruby main.rb --selftest`

## Files
- `main.rb` — the L-system (as on Linux) and the Win32 window via Fiddle
- `app.manifest` — Common Controls 6, activated at run time
