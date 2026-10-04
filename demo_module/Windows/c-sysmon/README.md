# C — Unified Base Windows demo #2: a process monitor on plain Win32

A small Task Manager in one C file: every process with its CPU %, memory,
threads and parent, refreshed each second. Click a column to sort (the
header shows the arrow), type to filter by name, double-click a row — or
**Show in Explorer** — to open the program's folder with it selected.
Above the list, CPU (green) and memory (blue) over the last two minutes.

## Demonstrates
- **Toolhelp32**: `CreateToolhelp32Snapshot` lists every process with its
  parent and thread count in one call.
- **CPU per process**: `GetProcessTimes` kernel+user time, differenced
  between samples and divided by wall time × processors. Machine-wide CPU
  is `GetSystemTimes` — where kernel time *includes* idle time.
- **Memory**: `K32GetProcessMemoryInfo`'s working set, through the
  limited-information access Windows grants for other users' processes.
  System services refuse even that to a non-elevated program, so their
  memory and CPU show blank rather than wrong.
- **A virtual ListView** (`LVS_OWNERDATA`): the control stores no rows. It
  asks for each cell as it paints (`LVN_GETDISPINFO`), so 300 processes
  cost only the rows on screen. The selection is kept by *process ID*
  across re-sorts, since a virtual list only knows row numbers.
- **Stable sorting**: ties fall back to name, A to Z, in either direction,
  so rows don't reshuffle every second.
- **Explorer's look**: `SetWindowTheme(list, L"Explorer")`, double-buffered
  list (`LVS_EX_DOUBLEBUFFER`), header sort arrows (`HDF_SORTUP/DOWN`), a
  cue banner in the filter box — all Common Controls 6, via the manifest.
- **The graph**: GDI polygon + polylines into a back buffer.

## Build
`sysmon.exe` ships prebuilt and runs without a compiler. To rebuild:
**zig** (`winget install -e --id zig.zig`) and `make` (`winget install -e
--id ezwinports.make`); one recipe works on both OSes. With no compiler the
failed compile is ignored while `sysmon.exe` exists.

## Run
Unified Base runs `make`, then `sysmon.exe`. On Linux, Wine runs it — and
lists Wine's processes.

Check, no window: `sysmon.exe --selftest` — samples twice, then checks it
sees itself, its memory, that CPU adds up, sorting and filtering.

## Files
- `main.c` — everything
- `app.rc`, `app.manifest` — Common Controls 6 and DPI awareness
- `Makefile` — the zig recipe
- `sysmon.exe` — prebuilt
