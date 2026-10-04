# Rust — Unified Base Windows demo: multithreaded path tracer

The Windows twin of `demo_module/Linux/rust-raytracer`: reflective spheres,
a checkered floor, soft shadows, rendered progressively across every core.
The same code — `minifb` draws its window with Win32 here and X11 on Linux.

Keys: **arrows** orbit · **W/S** zoom · **Space** toggles auto-orbit · **R**
resets · **Esc** quits.

## Why a twin
Same source, same compiler, two operating systems' thread schedulers and
window systems: load both and compare the samples-per-second in the title
bars. The Linux README covers `std::thread::scope`, `chunks_mut` and the
progressive accumulation.

## Building on Windows without Visual Studio
Rust on Windows defaults to the MSVC toolchain, whose linker comes with
Visual Studio's C++ build tools — a multi-gigabyte install. The **GNU**
toolchain needs none of it: it links with a MinGW it carries itself.

- `winget install -e --id Rustlang.Rust.GNU` (the tab's Install hint), or
- rustup: `rustup-init -y --default-host x86_64-pc-windows-gnu`

## Run
Unified Base runs `cargo build --release`, then the binary.

Manual equivalent:

```
cargo run --release
```

## Files
- `Cargo.toml` — one dependency (`minifb`)
- `src/main.rs` — vectors, scene, camera, threading, render loop
