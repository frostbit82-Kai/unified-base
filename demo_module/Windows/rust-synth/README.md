# Rust — Unified Base Windows demo #2: a synth on raw Win32

A two-octave polyphonic synthesizer: play it from the keyboard or drag
across the keys, watch the waveform on a live oscilloscope. Four waveforms,
ten voices, an attack-decay-sustain-release envelope.

| Input | Does |
|---|---|
| `Z S X D C V G B H N J M` | lower octave (the tracker layout: bottom letter row, black keys above) |
| `Q 2 W 3 E R 5 T 6 Y 7 U I` | upper octave |
| click / drag on the keys | play, gliding note to note |
| `F1`–`F4` or the buttons | sine, triangle, saw, square |
| `↑` / `↓` | octave up / down |

## Demonstrates
No GUI framework and no audio crate — `windows-sys` bindings and nothing else:

- **A Win32 program in Rust**: a window class, a `wndproc`, a message loop.
  App state lives in a `thread_local!` `RefCell`, borrowed only briefly,
  because a Win32 call made mid-borrow can send a message straight back into
  `wndproc`.
- **GDI, double-buffered**: every frame is drawn into an offscreen bitmap
  and copied in one `BitBlt` — no flicker. Sizes follow `GetDpiForWindow`,
  so the window is sharp at 125 % and fills whatever pane it is given.
- **Streaming audio through winmm**: `waveOutOpen` with `CALLBACK_EVENT`; a
  worker thread waits on the event, refills each buffer the driver has
  finished, and queues it again. Four 512-sample buffers: about 46 ms in
  flight. The status line's *streamed* seconds count up in real time — the
  stream's heartbeat, visible even in silence.
- **The usual unsafe traps, handled**: the driver holds raw pointers to
  the sample buffers and headers, so neither may move once queued;
  `WAVEHDR` is a packed struct, so its flag is read through a raw pointer,
  volatile, since the driver writes it from another thread.
- **DSP in plain Rust** (`dsp.rs`, no Windows in it): phase accumulators,
  linear ADSR, quietest-voice stealing, a `tanh` soft clip so ten voices
  bend instead of cracking, and an oscilloscope that triggers on a rising
  zero crossing so a steady note stands still.
- Releasing every note when focus leaves: the key-ups would never arrive.

## Dependencies
- Rust with the GNU toolchain (`winget install -e --id Rustlang.Rust.GNU`):
  no Visual Studio needed. `windows-sys` is pinned to 0.59 — from 0.60 it
  links through raw-dylib, which on the GNU toolchain needs MinGW's
  `dlltool` on PATH.

## Run
Unified Base runs `cargo build --release`, then the binary. Windows-only.

Manual equivalent:

```
cargo run --release
```

Check, no window, no sound: `cargo run --release -- --selftest` — times
A4's zero crossings (440.0 Hz), checks the release ends in silence, the
voice cap, and the chord's soft clip.

## Files
- `Cargo.toml` — `windows-sys` and the API slices used
- `src/dsp.rs` — the synth, and its self-test
- `src/main.rs` — window, painting, input, and the waveOut stream
