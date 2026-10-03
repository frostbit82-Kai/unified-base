# win32-native

A plain Win32 API program (C, GDI, common controls) — no framework, no runtime.

- **Windows:** runs natively.
- **Linux:** runs through Wine. Wine draws real X11 windows, so it embeds into
  a pane exactly like a Linux app.

`app.exe` is prebuilt. `make` rebuilds it from `main.c` when you change it
(MinGW-w64 on Linux, MSYS2 gcc on Windows).
