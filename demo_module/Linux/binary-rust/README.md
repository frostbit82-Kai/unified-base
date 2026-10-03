# Rust — Unified Base demo

Native-binary GUI demo: a color-cycling glow ball bouncing inside a 640x480
software framebuffer window (built with the `minifb` crate), rendered pixel-by-pixel
each frame at ~60fps. It opens one real X11 window, so Unified Base can embed it in a tab.

## Dependencies

- Rust toolchain: `cargo` + `rustc` (e.g. `rustup`, or `sudo apt install cargo rustc`)
- X11 dev headers for the window backend:
  `sudo apt install libxkbcommon-dev xorg-dev`
- The `minifb = "0.27"` crate is fetched automatically by cargo on the first build.

## Run

Unified Base runs this automatically: it detects `Cargo.toml` (runtime "binary"),
runs `cargo build --release`, then launches `target/release/rust-bouncer`.

Manual equivalent:

```sh
cargo build --release
./target/release/rust-bouncer
```

Press `Esc` or close the window to exit.
