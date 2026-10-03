// Rust — Unified Base demo
// A bouncing, color-cycling glow ball rendered into a software framebuffer
// with minifb. One real X11 window (640x480) that Unified Base can embed.
// Safe Rust: no unwrap on window/buffer operations, graceful exit on error.

use std::thread::sleep;
use std::time::{Duration, Instant};

use minifb::{Key, Window, WindowOptions};

const WIDTH: usize = 640;
const HEIGHT: usize = 480;
const RADIUS: f32 = 30.0; // solid ball radius
const GLOW: f32 = 26.0; // extra soft-glow radius on top of RADIUS

// Pack 8-bit channels into minifb's 0RGB u32 format.
#[inline]
fn pack(r: u8, g: u8, b: u8) -> u32 {
    ((r as u32) << 16) | ((g as u32) << 8) | (b as u32)
}

// Build a static vertical gradient background (dark navy -> deep violet).
fn build_background() -> Vec<u32> {
    let mut bg = vec![0u32; WIDTH * HEIGHT];
    for y in 0..HEIGHT {
        let t = y as f32 / HEIGHT as f32;
        let r = (8.0 + t * 18.0) as u8;
        let g = (10.0 + t * 8.0) as u8;
        let b = (24.0 + t * 30.0) as u8;
        let c = pack(r, g, b);
        let row = y * WIDTH;
        for x in 0..WIDTH {
            bg[row + x] = c;
        }
    }
    bg
}

// Smooth RGB from a phase, using offset sines -> gentle rainbow cycle.
fn cycle_color(phase: f32) -> (f32, f32, f32) {
    let r = 0.5 + 0.5 * (phase).sin();
    let g = 0.5 + 0.5 * (phase + 2.094_395).sin(); // +120 deg
    let b = 0.5 + 0.5 * (phase + 4.188_790).sin(); // +240 deg
    (r, g, b)
}

fn main() {
    let background = build_background();
    let mut buffer = background.clone();

    let mut window = match Window::new(
        "Rust — Unified Base demo",
        WIDTH,
        HEIGHT,
        WindowOptions::default(),
    ) {
        Ok(w) => w,
        Err(e) => {
            eprintln!("rust-bouncer: could not open window: {e}");
            return;
        }
    };

    // Ball state (pixels, and pixels-per-frame velocity).
    let mut x = WIDTH as f32 * 0.5;
    let mut y = HEIGHT as f32 * 0.4;
    let mut vx = 3.4_f32;
    let mut vy = 2.6_f32;
    let mut phase = 0.0_f32;

    let frame_time = Duration::from_micros(16_666); // ~60 fps

    while window.is_open() && !window.is_key_down(Key::Escape) {
        let start = Instant::now();

        // --- physics ---
        x += vx;
        y += vy;
        if x - RADIUS < 0.0 {
            x = RADIUS;
            vx = vx.abs();
        } else if x + RADIUS > WIDTH as f32 {
            x = WIDTH as f32 - RADIUS;
            vx = -vx.abs();
        }
        if y - RADIUS < 0.0 {
            y = RADIUS;
            vy = vy.abs();
        } else if y + RADIUS > HEIGHT as f32 {
            y = HEIGHT as f32 - RADIUS;
            vy = -vy.abs();
        }
        phase += 0.03;

        // --- fade previous frame toward the background (motion trail) ---
        // cur = cur*(13/16) + bg*(3/16)  -> soft, cheap decay
        for i in 0..buffer.len() {
            let c = buffer[i];
            let b = background[i];
            let cr = (c >> 16) & 0xff;
            let cg = (c >> 8) & 0xff;
            let cb = c & 0xff;
            let br = (b >> 16) & 0xff;
            let bg_ = (b >> 8) & 0xff;
            let bb = b & 0xff;
            let nr = (cr * 13 + br * 3) >> 4;
            let ng = (cg * 13 + bg_ * 3) >> 4;
            let nb = (cb * 13 + bb * 3) >> 4;
            buffer[i] = (nr << 16) | (ng << 8) | nb;
        }

        // --- draw glowing ball (additive over the trail) ---
        let (cr, cg, cb) = cycle_color(phase);
        let reach = RADIUS + GLOW;
        let x0 = (x - reach).floor().max(0.0) as usize;
        let x1 = ((x + reach).ceil() as usize).min(WIDTH);
        let y0 = (y - reach).floor().max(0.0) as usize;
        let y1 = ((y + reach).ceil() as usize).min(HEIGHT);

        for py in y0..y1 {
            let row = py * WIDTH;
            let dy = py as f32 - y;
            for px in x0..x1 {
                let dx = px as f32 - x;
                let d = (dx * dx + dy * dy).sqrt();
                if d >= reach {
                    continue;
                }
                // Core is near-full brightness; glow falls off smoothly.
                let intensity = if d <= RADIUS {
                    1.0 - 0.25 * (d / RADIUS)
                } else {
                    let t = 1.0 - (d - RADIUS) / GLOW;
                    0.75 * t * t
                };

                let add_r = (cr * 255.0 * intensity) as u32;
                let add_g = (cg * 255.0 * intensity) as u32;
                let add_b = (cb * 255.0 * intensity) as u32;

                let idx = row + px;
                let c = buffer[idx];
                let nr = (((c >> 16) & 0xff) + add_r).min(255);
                let ng = (((c >> 8) & 0xff) + add_g).min(255);
                let nb = ((c & 0xff) + add_b).min(255);
                buffer[idx] = (nr << 16) | (ng << 8) | nb;
            }
        }

        // Present the frame; bail out cleanly if the window is gone.
        if let Err(e) = window.update_with_buffer(&buffer, WIDTH, HEIGHT) {
            eprintln!("rust-bouncer: draw failed: {e}");
            break;
        }

        // Frame limiter (~60 fps) without relying on version-specific APIs.
        let elapsed = start.elapsed();
        if elapsed < frame_time {
            sleep(frame_time - elapsed);
        }
    }
}
