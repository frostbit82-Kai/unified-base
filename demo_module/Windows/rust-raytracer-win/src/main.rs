//! Rust — Unified Base Windows demo: twin of demo_module/Linux/rust-raytracer.
//!
//! Demo #1 bounces a ball. This one is about what Rust is actually for: raw
//! compute, spread across every core, with the borrow checker proving the
//! parallel writes don't overlap.
//!
//! * `std::thread::scope` — worker threads borrow the scene and camera by
//!   reference. No `Arc`, no cloning, no `'static` bound, because the scope
//!   guarantees they finish before the borrow ends.
//! * `chunks_mut` — the accumulation buffer is split into disjoint row bands,
//!   one per thread. Non-overlap is a compile-time fact, not a convention.
//! * Progressive accumulation — one jittered sample per pixel per frame, added
//!   into an f32 buffer. The image is usable instantly and converges as you
//!   watch; moving the camera resets the accumulation.
//!
//! Keys: arrows orbit · W/S zoom · Space toggles the auto-orbit (on at
//! start) · R resets.
//! Any camera movement restarts accumulation, so the sample count drops to 1
//! and climbs again once you stop.

use minifb::{Key, Window, WindowOptions};
use std::time::Instant;

const W: usize = 720;
const H: usize = 480;
const MAX_BOUNCES: u32 = 3;

// ---------------------------------------------------------------------------
// Vectors
// ---------------------------------------------------------------------------
#[derive(Clone, Copy, Debug)]
struct V3 {
    x: f32,
    y: f32,
    z: f32,
}

fn v(x: f32, y: f32, z: f32) -> V3 {
    V3 { x, y, z }
}

impl V3 {
    fn add(self, o: V3) -> V3 { v(self.x + o.x, self.y + o.y, self.z + o.z) }
    fn sub(self, o: V3) -> V3 { v(self.x - o.x, self.y - o.y, self.z - o.z) }
    fn mul(self, k: f32) -> V3 { v(self.x * k, self.y * k, self.z * k) }
    fn dot(self, o: V3) -> f32 { self.x * o.x + self.y * o.y + self.z * o.z }
    fn cross(self, o: V3) -> V3 {
        v(self.y * o.z - self.z * o.y,
          self.z * o.x - self.x * o.z,
          self.x * o.y - self.y * o.x)
    }
    fn len(self) -> f32 { self.dot(self).sqrt() }
    fn norm(self) -> V3 {
        let l = self.len();
        if l > 0.0 { self.mul(1.0 / l) } else { self }
    }
    /// Mirror this direction about `n`.
    fn reflect(self, n: V3) -> V3 { self.sub(n.mul(2.0 * self.dot(n))) }
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------
#[derive(Clone, Copy)]
struct Sphere {
    center: V3,
    radius: f32,
    albedo: V3,
    reflect: f32,
}

struct Scene {
    spheres: Vec<Sphere>,
    light: V3,
}

impl Scene {
    fn demo() -> Scene {
        Scene {
            spheres: vec![
                Sphere { center: v(0.0, 1.0, 0.0),   radius: 1.0,  albedo: v(0.85, 0.30, 0.28), reflect: 0.28 },
                Sphere { center: v(2.3, 0.75, -1.0), radius: 0.75, albedo: v(0.32, 0.62, 0.92), reflect: 0.55 },
                Sphere { center: v(-2.1, 0.6, -0.6), radius: 0.6,  albedo: v(0.45, 0.80, 0.45), reflect: 0.15 },
                Sphere { center: v(0.6, 0.38, 1.9),  radius: 0.38, albedo: v(0.95, 0.78, 0.35), reflect: 0.75 },
                Sphere { center: v(-1.1, 0.3, 1.6),  radius: 0.3,  albedo: v(0.85, 0.85, 0.90), reflect: 0.9  },
            ],
            light: v(-4.0, 6.0, 5.0),
        }
    }

    /// Nearest hit along the ray: (distance, normal, albedo, reflectivity).
    fn hit(&self, o: V3, d: V3) -> Option<(f32, V3, V3, f32)> {
        let mut best: Option<(f32, V3, V3, f32)> = None;

        for s in &self.spheres {
            let oc = o.sub(s.center);
            let b = oc.dot(d);
            let c = oc.dot(oc) - s.radius * s.radius;
            let disc = b * b - c;
            if disc <= 0.0 {
                continue;
            }
            let sq = disc.sqrt();
            let t = if -b - sq > 1e-3 { -b - sq } else { -b + sq };
            if t <= 1e-3 {
                continue;
            }
            if best.map_or(true, |(bt, _, _, _)| t < bt) {
                let n = o.add(d.mul(t)).sub(s.center).mul(1.0 / s.radius);
                best = Some((t, n, s.albedo, s.reflect));
            }
        }

        // Checkered ground plane at y = 0.
        if d.y.abs() > 1e-4 {
            let t = -o.y / d.y;
            if t > 1e-3 && best.map_or(true, |(bt, _, _, _)| t < bt) {
                let p = o.add(d.mul(t));
                if p.x.abs() < 24.0 && p.z.abs() < 24.0 {
                    let checker = ((p.x.floor() as i32 + p.z.floor() as i32) & 1) == 0;
                    let albedo = if checker { v(0.83, 0.83, 0.86) } else { v(0.16, 0.18, 0.22) };
                    best = Some((t, v(0.0, 1.0, 0.0), albedo, 0.22));
                }
            }
        }
        best
    }

    fn in_shadow(&self, p: V3, l: V3) -> bool {
        let dir = l.sub(p).norm();
        match self.hit(p.add(dir.mul(1e-3)), dir) {
            Some((t, _, _, _)) => t < l.sub(p).len(),
            None => false,
        }
    }

    /// Sky gradient for rays that escape.
    fn sky(d: V3) -> V3 {
        let t = 0.5 * (d.y + 1.0);
        v(0.05, 0.06, 0.09).mul(1.0 - t).add(v(0.22, 0.34, 0.52).mul(t))
    }

    fn trace(&self, o: V3, d: V3, depth: u32) -> V3 {
        let Some((t, n, albedo, reflect)) = self.hit(o, d) else {
            return Scene::sky(d);
        };
        let p = o.add(d.mul(t));
        let to_light = self.light.sub(p).norm();

        let mut lambert = n.dot(to_light).max(0.0);
        if self.in_shadow(p, self.light) {
            lambert *= 0.15;
        }
        let spec = {
            let h = to_light.sub(d).norm();
            n.dot(h).max(0.0).powf(48.0)
        };

        let ambient = 0.12 + 0.10 * (n.y * 0.5 + 0.5);
        let mut color = albedo
            .mul(ambient + 0.9 * lambert)
            .add(v(1.0, 0.97, 0.9).mul(spec * 0.35));

        if reflect > 0.0 && depth < MAX_BOUNCES {
            let r = d.reflect(n).norm();
            let bounced = self.trace(p.add(r.mul(1e-3)), r, depth + 1);
            color = color.mul(1.0 - reflect).add(bounced.mul(reflect));
        }
        color
    }
}

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------
#[derive(Clone, Copy)]
struct Camera {
    yaw: f32,
    pitch: f32,
    dist: f32,
}

impl Camera {
    fn eye(&self) -> V3 {
        v(self.dist * self.yaw.cos() * self.pitch.cos(),
          1.6 + self.dist * self.pitch.sin(),
          self.dist * self.yaw.sin() * self.pitch.cos())
    }

    /// Ray through pixel (px, py) with a sub-pixel offset for antialiasing.
    fn ray(&self, px: usize, py: usize, jx: f32, jy: f32) -> (V3, V3) {
        let eye = self.eye();
        let target = v(0.0, 0.9, 0.0);
        let fwd = target.sub(eye).norm();
        let right = fwd.cross(v(0.0, 1.0, 0.0)).norm();
        let up = right.cross(fwd);

        let aspect = W as f32 / H as f32;
        let fov = 0.9_f32;
        let sx = ((px as f32 + jx) / W as f32 * 2.0 - 1.0) * aspect * fov;
        let sy = (1.0 - (py as f32 + jy) / H as f32 * 2.0) * fov;
        let dir = fwd.add(right.mul(sx)).add(up.mul(sy)).norm();
        (eye, dir)
    }
}

/// Cheap deterministic hash → [0,1). Avoids pulling in the `rand` crate and
/// keeps every frame reproducible for a given (pixel, sample).
fn hash01(mut x: u32) -> f32 {
    x ^= x >> 16;
    x = x.wrapping_mul(0x7feb_352d);
    x ^= x >> 15;
    x = x.wrapping_mul(0x846c_a68b);
    x ^= x >> 16;
    (x >> 8) as f32 / 16_777_216.0
}

fn to_u32(c: V3, samples: f32) -> u32 {
    // Average, then gamma-correct (sqrt ≈ gamma 2.2) so midtones aren't muddy.
    let f = |x: f32| {
        let v = (x / samples).max(0.0).min(1.0).sqrt();
        (v * 255.0 + 0.5) as u32
    };
    (f(c.x) << 16) | (f(c.y) << 8) | f(c.z)
}

fn main() {
    let scene = Scene::demo();
    let mut cam = Camera { yaw: 2.2, pitch: 0.30, dist: 7.0 };

    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    let rows_per_band = (H + threads - 1) / threads;

    let mut accum = vec![v(0.0, 0.0, 0.0); W * H];
    let mut buffer = vec![0u32; W * H];
    let mut samples = 0.0f32;
    // On by default: embedded in a launcher pane this is the first thing you
    // see, and a still image reads as a frozen module. Space stops the orbit,
    // and then the accumulation converges — which is the other thing worth
    // watching.
    let mut orbit = true;

    let mut window = Window::new(
        "Rust · path tracer — Unified Base Windows demo",
        W,
        H,
        WindowOptions { resize: false, ..WindowOptions::default() },
    )
    .expect("could not open a window");
    window.set_target_fps(60);

    let mut last_title = Instant::now();

    while window.is_open() && !window.is_key_down(Key::Escape) {
        // --- input: any camera change invalidates the accumulated image ---
        let mut moved = false;
        let nudge = |c: &mut Camera, dy: f32, dp: f32, dd: f32| {
            c.yaw += dy;
            c.pitch = (c.pitch + dp).clamp(0.05, 1.35);
            c.dist = (c.dist + dd).clamp(3.0, 16.0);
        };
        if window.is_key_down(Key::Left)  { nudge(&mut cam, -0.03, 0.0, 0.0); moved = true; }
        if window.is_key_down(Key::Right) { nudge(&mut cam,  0.03, 0.0, 0.0); moved = true; }
        if window.is_key_down(Key::Up)    { nudge(&mut cam, 0.0,  0.02, 0.0); moved = true; }
        if window.is_key_down(Key::Down)  { nudge(&mut cam, 0.0, -0.02, 0.0); moved = true; }
        if window.is_key_down(Key::W)     { nudge(&mut cam, 0.0, 0.0, -0.12); moved = true; }
        if window.is_key_down(Key::S)     { nudge(&mut cam, 0.0, 0.0,  0.12); moved = true; }
        if window.is_key_pressed(Key::Space, minifb::KeyRepeat::No) { orbit = !orbit; }
        if window.is_key_pressed(Key::R, minifb::KeyRepeat::No) {
            cam = Camera { yaw: 2.2, pitch: 0.30, dist: 7.0 };
            moved = true;
        }
        if orbit {
            cam.yaw += 0.004;
            moved = true;
        }
        if moved {
            accum.iter_mut().for_each(|p| *p = v(0.0, 0.0, 0.0));
            samples = 0.0;
        }

        // --- render one sample per pixel, split across the cores ---
        let frame_start = Instant::now();
        let seed = samples as u32;
        let cam_ref = &cam;
        let scene_ref = &scene;

        std::thread::scope(|s| {
            // Each band is a disjoint &mut slice, so the threads cannot alias.
            for (band, rows) in accum.chunks_mut(rows_per_band * W).enumerate() {
                s.spawn(move || {
                    let y0 = band * rows_per_band;
                    for (i, px) in rows.iter_mut().enumerate() {
                        let x = i % W;
                        let y = y0 + i / W;
                        let h = (y as u32).wrapping_mul(9781).wrapping_add(x as u32)
                            .wrapping_mul(6151).wrapping_add(seed.wrapping_mul(31));
                        let (jx, jy) = if seed == 0 {
                            (0.5, 0.5)          // first pass: pixel centres, no noise
                        } else {
                            (hash01(h), hash01(h ^ 0x9e37_79b9))
                        };
                        let (o, d) = cam_ref.ray(x, y, jx, jy);
                        *px = px.add(scene_ref.trace(o, d, 0));
                    }
                });
            }
        });
        samples += 1.0;

        for (out, c) in buffer.iter_mut().zip(accum.iter()) {
            *out = to_u32(*c, samples);
        }
        let ms = frame_start.elapsed().as_secs_f64() * 1000.0;

        window.update_with_buffer(&buffer, W, H).expect("buffer update failed");

        if last_title.elapsed().as_millis() > 250 {
            last_title = Instant::now();
            window.set_title(&format!(
                "Rust · path tracer — {}×{} · {} threads · {:.0} spp · {:.0} ms/frame · {} · arrows+W/S move, space pauses orbit",
                W, H, threads, samples, ms,
                if orbit { "orbiting" } else { "converging" }
            ));
        }
    }
}
