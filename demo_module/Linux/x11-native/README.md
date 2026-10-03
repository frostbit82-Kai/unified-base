# x11-native

Raw Xlib in C — a program that only exists on Linux.

- **Linux:** runs natively and embeds like any X11 app.
- **Windows:** the launcher sees an ELF binary, marks the module Linux-only and
  runs it inside WSL; WSLg puts its window on the Windows desktop.

The X libraries are statically linked, so the prebuilt `x11-native` needs only
glibc — no `libx11` inside the WSL distro. `make` rebuilds it (needs
`libx11-dev`).
