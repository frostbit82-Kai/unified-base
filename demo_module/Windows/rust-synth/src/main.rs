//! Rust — Unified Base Windows demo #2: a polyphonic synth on raw Win32.
//!
//! No GUI framework, no audio crate: a window class and a message loop from
//! user32, double-buffered GDI drawing, and sound streamed through winmm's
//! waveOut from a worker thread. dsp.rs is the synth; this file is Windows.
//!
//! Play: the bottom letter row (Z S X D C V G B H N J M) is the lower
//! octave, the top row (Q 2 W 3 E R 5 T 6 Y 7 U I) the upper one — the
//! tracker layout — or click and drag across the keys. F1–F4 pick the
//! waveform, ↑/↓ shift the octave.
//!
//! `rust-synth --selftest` checks pitch, envelope and voice handling
//! without opening a window or making a sound.

mod dsp;

use dsp::{Synth, Wave};
use std::cell::RefCell;
use std::collections::HashSet;
use std::ptr::{null, null_mut};
use std::sync::{Arc, Mutex};
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::Graphics::Gdi::*;
use windows_sys::Win32::Media::Audio::*;
use windows_sys::Win32::Media::MMSYSERR_NOERROR;
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::{CreateEventW, WaitForSingleObject};
use windows_sys::Win32::UI::HiDpi::*;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::*;
use windows_sys::Win32::UI::WindowsAndMessaging::*;

/// (virtual key, semitone above the keyboard's lowest C).
const KEYMAP: [(u8, u8); 25] = [
    (b'Z', 0), (b'S', 1), (b'X', 2), (b'D', 3), (b'C', 4), (b'V', 5), (b'G', 6),
    (b'B', 7), (b'H', 8), (b'N', 9), (b'J', 10), (b'M', 11),
    (b'Q', 12), (b'2', 13), (b'W', 14), (b'3', 15), (b'E', 16), (b'R', 17), (b'5', 18),
    (b'T', 19), (b'6', 20), (b'Y', 21), (b'7', 22), (b'U', 23), (b'I', 24),
];
const SEMITONES: u8 = 25; // two octaves and the top C
const BUFFERS: usize = 4; // waveOut queue: 4 × 512 samples ≈ 46 ms
const FRAMES: usize = 512;

struct App {
    synth: Arc<Mutex<Synth>>,
    audio: Arc<Mutex<String>>, // set by the audio thread: format or error
    held: HashSet<u8>,         // semitones down, from keys or the mouse
    mouse: Option<u8>,
    octave: i32,               // lowest C is MIDI 12 × (octave + 1)
}

thread_local! {
    static APP: RefCell<Option<App>> = const { RefCell::new(None) };
}

/// Short borrows only: a Win32 call made while borrowed can send a message
/// straight back into wndproc, which would then find the RefCell taken.
fn with<R>(f: impl FnOnce(&mut App) -> R) -> Option<R> {
    APP.with(|a| a.borrow_mut().as_mut().map(f))
}

impl App {
    fn note(&self, semi: u8) -> u8 {
        (12 * (self.octave + 1) + semi as i32).clamp(0, 127) as u8
    }

    fn press(&mut self, semi: u8) {
        if self.held.insert(semi) {
            let n = self.note(semi);
            self.synth.lock().unwrap().note_on(n);
        }
    }

    fn release(&mut self, semi: u8) {
        if self.held.remove(&semi) {
            let n = self.note(semi);
            self.synth.lock().unwrap().note_off(n);
        }
    }

    fn release_all(&mut self) {
        self.held.clear();
        self.mouse = None;
        self.synth.lock().unwrap().all_off();
    }
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}

fn rgb(hex: u32) -> COLORREF {
    // COLORREF is 0x00BBGGRR — the reverse of how colours are usually written.
    ((hex & 0xFF) << 16) | (hex & 0xFF00) | ((hex >> 16) & 0xFF)
}

// --- audio -------------------------------------------------------------------
/// Stream the synth into the default output device until the process ends.
/// waveOut signals an event each time a buffer finishes; the finished buffer
/// is refilled and queued again, so the card never runs dry.
fn audio_thread(synth: Arc<Mutex<Synth>>, status: Arc<Mutex<String>>) {
    unsafe {
        let event = CreateEventW(null(), 0, 0, null());
        let fmt = WAVEFORMATEX {
            wFormatTag: WAVE_FORMAT_PCM as u16,
            nChannels: 1,
            nSamplesPerSec: dsp::RATE as u32,
            nAvgBytesPerSec: dsp::RATE as u32 * 2,
            nBlockAlign: 2,
            wBitsPerSample: 16,
            cbSize: 0,
        };
        let mut out: HWAVEOUT = null_mut();
        let r = waveOutOpen(&mut out, WAVE_MAPPER, &fmt, event as usize, 0, CALLBACK_EVENT);
        if r != MMSYSERR_NOERROR {
            *status.lock().unwrap() = format!("no audio output (waveOutOpen error {r})");
            return;
        }
        *status.lock().unwrap() =
            format!("{} kHz · 16-bit · {BUFFERS} × {FRAMES} samples", dsp::RATE / 1000.0);
        // Neither the sample buffers nor the headers may move once queued:
        // the driver holds raw pointers to both.
        let mut data: Vec<Box<[i16; FRAMES]>> = (0..BUFFERS).map(|_| Box::new([0i16; FRAMES])).collect();
        let mut hdrs: Box<[WAVEHDR]> = (0..BUFFERS).map(|_| std::mem::zeroed()).collect();
        let hsize = std::mem::size_of::<WAVEHDR>() as u32;
        for (h, d) in hdrs.iter_mut().zip(data.iter_mut()) {
            h.lpData = d.as_mut_ptr() as *mut u8;
            h.dwBufferLength = (FRAMES * 2) as u32;
            waveOutPrepareHeader(out, h, hsize);
            synth.lock().unwrap().render(&mut d[..]);
            waveOutWrite(out, h, hsize);
        }
        loop {
            WaitForSingleObject(event, 100);
            for (h, d) in hdrs.iter_mut().zip(data.iter_mut()) {
                // The driver sets WHDR_DONE from its own thread, hence volatile.
                // WAVEHDR is packed, so no reference to the field; a raw
                // pointer is fine — dwFlags sits at offset 24 of a heap block.
                if std::ptr::read_volatile(std::ptr::addr_of!(h.dwFlags)) & WHDR_DONE != 0 {
                    h.dwFlags &= !WHDR_DONE;
                    synth.lock().unwrap().render(&mut d[..]);
                    waveOutWrite(out, h, hsize);
                }
            }
        }
    }
}

// --- layout -------------------------------------------------------------------
struct Layout {
    scale: f32,
    header: RECT,
    waves: Vec<(Wave, RECT)>,
    scope: RECT,
    keys: Vec<(u8, RECT, bool)>, // semitone, rect, black
}

fn is_black(semi: u8) -> bool {
    matches!(semi % 12, 1 | 3 | 6 | 8 | 10)
}

fn layout(hwnd: HWND) -> Layout {
    let mut rc: RECT = unsafe { std::mem::zeroed() };
    unsafe { GetClientRect(hwnd, &mut rc) };
    let s = unsafe { GetDpiForWindow(hwnd) } as f32 / 96.0;
    let px = |v: f32| (v * s) as i32;
    let (w, h) = (rc.right, rc.bottom);
    let m = px(16.0);
    let header = RECT { left: m, top: m, right: w - m, bottom: m + px(52.0) };
    let mut waves = Vec::new();
    let bw = px(96.0);
    for (i, wave) in Wave::ALL.iter().enumerate() {
        let l = m + i as i32 * (bw + px(8.0));
        waves.push((*wave, RECT { left: l, top: header.bottom + px(6.0), right: l + bw, bottom: header.bottom + px(36.0) }));
    }
    let scope_top = header.bottom + px(48.0);
    let kb_top = scope_top + ((h - scope_top) as f32 * 0.42) as i32;
    let scope = RECT { left: m, top: scope_top, right: w - m, bottom: kb_top - m };
    let whites: Vec<u8> = (0..SEMITONES).filter(|&k| !is_black(k)).collect();
    let ww = (w - 2 * m) as f32 / whites.len() as f32;
    let mut keys = Vec::new();
    for (i, &k) in whites.iter().enumerate() {
        let l = m + (i as f32 * ww) as i32;
        keys.push((k, RECT { left: l, top: kb_top, right: m + ((i + 1) as f32 * ww) as i32 - 2, bottom: h - m }, false));
    }
    for k in (0..SEMITONES).filter(|&k| is_black(k)) {
        let i = whites.iter().position(|&x| x == k - 1).unwrap() as f32 + 1.0;
        let c = m + (i * ww) as i32;
        keys.push((k, RECT { left: c - (ww * 0.32) as i32, top: kb_top, right: c + (ww * 0.32) as i32,
                             bottom: kb_top + ((h - m - kb_top) as f32 * 0.6) as i32 }, true));
    }
    Layout { scale: s, header, waves, scope, keys }
}

fn inside(r: &RECT, x: i32, y: i32) -> bool {
    x >= r.left && x < r.right && y >= r.top && y < r.bottom
}

/// The key under a point: black keys sit on top, so they're tested first.
fn key_at(l: &Layout, x: i32, y: i32) -> Option<u8> {
    let mut keys: Vec<_> = l.keys.iter().collect();
    keys.sort_by_key(|(_, _, black)| !*black);
    keys.into_iter().find(|(_, r, _)| inside(r, x, y)).map(|(k, _, _)| *k)
}

// --- painting -----------------------------------------------------------------
unsafe fn fill(dc: HDC, r: &RECT, color: u32) {
    let b = CreateSolidBrush(rgb(color));
    FillRect(dc, r, b);
    DeleteObject(b);
}

unsafe fn text(dc: HDC, s: &str, r: &RECT, color: u32, flags: u32) {
    let w: Vec<u16> = s.encode_utf16().collect();
    let mut r = *r;
    SetTextColor(dc, rgb(color));
    DrawTextW(dc, w.as_ptr(), w.len() as i32, &mut r, flags);
}

unsafe fn font(px: i32, weight: i32) -> HFONT {
    let face = wide("Segoe UI");
    CreateFontW(-px, 0, 0, 0, weight, 0, 0, 0, DEFAULT_CHARSET as u32, 0, 0,
                CLEARTYPE_QUALITY as u32, 0, face.as_ptr())
}

unsafe fn paint(hwnd: HWND) {
    let mut ps: PAINTSTRUCT = std::mem::zeroed();
    let screen = BeginPaint(hwnd, &mut ps);
    let mut rc: RECT = std::mem::zeroed();
    GetClientRect(hwnd, &mut rc);
    // Draw into an offscreen bitmap, then copy it in one go: no flicker.
    let dc = CreateCompatibleDC(screen);
    let bmp = CreateCompatibleBitmap(screen, rc.right.max(1), rc.bottom.max(1));
    let old_bmp = SelectObject(dc, bmp);
    SetBkMode(dc, TRANSPARENT as i32);
    fill(dc, &rc, 0x0D1117);

    let l = layout(hwnd);
    let px = |v: f32| (v * l.scale) as i32;
    let (held, wave, voices, octave, audio, scope, secs) = with(|a| {
        let s = a.synth.lock().unwrap();
        (a.held.clone(), s.wave, s.voices(), a.octave, a.audio.lock().unwrap().clone(), s.scope(600),
         s.frames as f32 / dsp::RATE)
    })
    .unwrap();

    let big = font(px(19.0), 600);
    let small = font(px(13.0), 400);
    let old_font = SelectObject(dc, big);
    text(dc, "Rust · a synth on raw Win32", &l.header, 0xE6EDF3, DT_LEFT | DT_TOP | DT_SINGLELINE);
    SelectObject(dc, small);
    let mut sub = l.header;
    sub.top += px(28.0);
    text(dc, &format!("waveOut · GDI · {} · octave {} · {} voice(s) · {} · streamed {:.0} s   —   keys Z…M / Q…I, F1–F4 wave, ↑↓ octave",
                      wave.name(), octave, voices, audio, secs),
         &sub, 0x7D8590, DT_LEFT | DT_TOP | DT_SINGLELINE | DT_END_ELLIPSIS);

    for (i, (w, r)) in l.waves.iter().enumerate() {
        let on = *w == wave;
        fill(dc, r, if on { 0x238636 } else { 0x21262D });
        text(dc, &format!("F{} {}", i + 1, w.name()), r, 0xE6EDF3, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }

    // Oscilloscope.
    fill(dc, &l.scope, 0x010409);
    let (sw, sh) = (l.scope.right - l.scope.left, l.scope.bottom - l.scope.top);
    let mid = l.scope.top + sh / 2;
    let grid = CreatePen(PS_SOLID, 1, rgb(0x21262D));
    let old_pen = SelectObject(dc, grid);
    MoveToEx(dc, l.scope.left, mid, null_mut());
    LineTo(dc, l.scope.right, mid);
    let trace = CreatePen(PS_SOLID, px(2.0), rgb(0x58A6FF));
    SelectObject(dc, trace);
    let pts: Vec<POINT> = scope
        .iter()
        .enumerate()
        .map(|(i, &v)| POINT {
            x: l.scope.left + (i as i32 * sw) / scope.len() as i32,
            y: mid - (v * (sh as f32 * 0.45)) as i32,
        })
        .collect();
    Polyline(dc, pts.as_ptr(), pts.len() as i32);
    SelectObject(dc, old_pen);
    DeleteObject(grid);
    DeleteObject(trace);

    // Keyboard: white keys, then black ones over them.
    for (k, r, black) in l.keys.iter().filter(|k| !k.2).chain(l.keys.iter().filter(|k| k.2)) {
        let down = held.contains(k);
        let color = match (black, down) {
            (_, true) => 0x2EA043,
            (true, false) => 0x161B22,
            (false, false) => 0xE6EDF3,
        };
        fill(dc, r, color);
        if *black {
            let key = KEYMAP.iter().find(|m| m.1 == *k).map(|m| m.0 as char).unwrap_or(' ');
            let mut lab = *r;
            lab.bottom -= px(6.0);
            text(dc, &key.to_string(), &lab, if down { 0xFFFFFF } else { 0x7D8590 },
                 DT_CENTER | DT_BOTTOM | DT_SINGLELINE);
        } else {
            let mut lab = *r;
            lab.bottom -= px(6.0);
            let name = ["C", "D", "E", "F", "G", "A", "B"][[0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6][*k as usize % 12]];
            let key = KEYMAP.iter().find(|m| m.1 == *k).map(|m| m.0 as char).unwrap_or(' ');
            let ink = if down { 0xFFFFFF } else { 0x57606A };
            text(dc, &key.to_string(), &lab, ink, DT_CENTER | DT_BOTTOM | DT_SINGLELINE);
            lab.bottom -= px(18.0);
            text(dc, name, &lab, ink, DT_CENTER | DT_BOTTOM | DT_SINGLELINE);
        }
    }

    SelectObject(dc, old_font);
    DeleteObject(big);
    DeleteObject(small);
    BitBlt(screen, 0, 0, rc.right, rc.bottom, dc, 0, 0, SRCCOPY);
    SelectObject(dc, old_bmp);
    DeleteObject(bmp);
    DeleteDC(dc);
    EndPaint(hwnd, &ps);
}

// --- messages -------------------------------------------------------------------
fn xy(lparam: LPARAM) -> (i32, i32) {
    ((lparam & 0xFFFF) as i16 as i32, ((lparam >> 16) & 0xFFFF) as i16 as i32)
}

unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    match msg {
        WM_PAINT => {
            paint(hwnd);
            0
        }
        WM_ERASEBKGND => 1, // paint covers everything; erasing first flickers
        WM_TIMER => {
            InvalidateRect(hwnd, null(), 0);
            0
        }
        WM_KEYDOWN | WM_KEYUP => {
            let vk = wparam as u16;
            let down = msg == WM_KEYDOWN;
            if down && lparam & (1 << 30) != 0 {
                return 0; // auto-repeat: the key was already down
            }
            if let Some(&(_, semi)) = KEYMAP.iter().find(|m| m.0 as u16 == vk) {
                with(|a| if down { a.press(semi) } else { a.release(semi) });
            } else if down {
                match vk {
                    VK_F1..=VK_F4 => {
                        with(|a| a.synth.lock().unwrap().wave = Wave::ALL[(vk - VK_F1) as usize]);
                    }
                    VK_UP | VK_DOWN => {
                        with(|a| {
                            a.release_all();
                            a.octave = (a.octave + if vk == VK_UP { 1 } else { -1 }).clamp(1, 7);
                        });
                    }
                    _ => return DefWindowProcW(hwnd, msg, wparam, lparam),
                }
            }
            0
        }
        WM_LBUTTONDOWN => {
            SetFocus(hwnd); // embedded, a click is how the keyboard arrives
            let (x, y) = xy(lparam);
            let l = layout(hwnd);
            if let Some((w, _)) = l.waves.iter().find(|(_, r)| inside(r, x, y)) {
                with(|a| a.synth.lock().unwrap().wave = *w);
            } else if let Some(k) = key_at(&l, x, y) {
                with(|a| {
                    a.mouse = Some(k);
                    a.press(k);
                });
                SetCapture(hwnd); // keep getting moves and the release off-window
            }
            0
        }
        WM_MOUSEMOVE => {
            // Dragging across the keys glides from note to note.
            let (x, y) = xy(lparam);
            let k = key_at(&layout(hwnd), x, y);
            with(|a| {
                if let Some(cur) = a.mouse {
                    if k.is_some() && k != Some(cur) {
                        a.release(cur);
                        a.mouse = k;
                        a.press(k.unwrap());
                    }
                }
            });
            0
        }
        WM_LBUTTONUP => {
            with(|a| {
                if let Some(cur) = a.mouse.take() {
                    a.release(cur);
                }
            });
            ReleaseCapture();
            0
        }
        // Focus gone mid-chord: the key-ups will never come, so stop now.
        WM_KILLFOCUS => {
            with(|a| a.release_all());
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

fn main() {
    if std::env::args().any(|a| a == "--selftest") {
        match dsp::selftest() {
            Ok(r) => println!("selftest ok: {r}"),
            Err(e) => {
                eprintln!("selftest FAILED: {e}");
                std::process::exit(1);
            }
        }
        return;
    }
    unsafe {
        // Real pixels at any display scale; layout() scales by the window's DPI.
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        let synth = Arc::new(Mutex::new(Synth::new()));
        let audio = Arc::new(Mutex::new("opening audio…".to_string()));
        {
            let (s, st) = (synth.clone(), audio.clone());
            std::thread::spawn(move || audio_thread(s, st));
        }
        APP.with(|a| {
            *a.borrow_mut() = Some(App { synth, audio, held: HashSet::new(), mouse: None, octave: 3 })
        });

        let inst = GetModuleHandleW(null());
        let class = wide("UnifiedBaseRustSynth");
        let wc = WNDCLASSW {
            style: CS_HREDRAW | CS_VREDRAW,
            lpfnWndProc: Some(wndproc),
            hInstance: inst,
            hCursor: LoadCursorW(null_mut(), IDC_ARROW),
            lpszClassName: class.as_ptr(),
            ..std::mem::zeroed()
        };
        RegisterClassW(&wc);
        let s = GetDpiForSystem() as f32 / 96.0;
        let title = wide("Rust · synth on raw Win32 — Unified Base Windows demo");
        let hwnd = CreateWindowExW(0, class.as_ptr(), title.as_ptr(), WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                   CW_USEDEFAULT, CW_USEDEFAULT, (900.0 * s) as i32, (560.0 * s) as i32,
                                   null_mut(), null_mut(), inst, null());
        SetTimer(hwnd, 1, 33, None); // ~30 fps for the scope
        let mut msg: MSG = std::mem::zeroed();
        while GetMessageW(&mut msg, null_mut(), 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}
