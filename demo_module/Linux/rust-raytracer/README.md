# Rust — Unified Base demo #2: multithreaded path tracer

A ray-traced scene — reflective spheres, checkered ground, shadows, sky
gradient — rendered progressively across every core. It starts still so the
image visibly converges; the title bar reports threads, samples per pixel, and
frame time.

Keys: **arrows** orbit · **W/S** zoom · **Space** toggles auto-orbit · **R**
resets · **Esc** quits. Any camera movement restarts accumulation.

## Demonstrates
Demo #1 bounces a ball in a window. This one is Rust doing what Rust is for:

- **`std::thread::scope`** — workers borrow the scene and camera by reference.
  No `Arc`, no cloning, no `'static` bound, because the scope guarantees the
  threads finish before the borrow ends.
- **`chunks_mut` for data parallelism** — the accumulation buffer is split into
  disjoint row bands, one per thread. Non-overlap is proven at compile time
  rather than promised in a comment.
- **Progressive accumulation** — one jittered sample per pixel per frame summed
  into an f32 buffer, then averaged and gamma-corrected. Usable immediately,
  clean after a few hundred samples.
- **No dependencies beyond the window** — the only crate is `minifb`. Sampling
  jitter comes from an inline integer hash, so frames stay reproducible and
  there's no `rand` in the tree.
- **`available_parallelism`** — thread count comes from the machine, not a
  hardcoded number.

## Dependencies
- Rust toolchain (`cargo`). First build fetches `minifb`.

## Run
Unified Base builds and runs this automatically (`cargo build && cargo run`).

Manual equivalent:

```
cargo run --release
```

Release matters — a debug build is roughly an order of magnitude slower.

## Files
- `Cargo.toml` — one dependency, optimised release profile
- `src/main.rs` — vectors, scene, camera, threading, and the render loop
