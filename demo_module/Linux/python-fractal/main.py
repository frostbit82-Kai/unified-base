#!/usr/bin/env python3
"""Python — Unified Base demo #2: an interactive Mandelbrot explorer.

Zero dependencies (tkinter + stdlib only). The point of this demo is *not*
animation — it's showing how a pure-Python GUI stays responsive while doing
genuinely slow work:

  * progressive refinement — a coarse image appears immediately, then sharpens
    through four passes, so you never stare at a blank window;
  * cooperative scheduling — each pass computes a few rows per `after()` tick,
    so clicks and repaints are still handled mid-render;
  * image plumbing without PIL — pixels are packed into a PNG by hand (zlib +
    a CRC per chunk) and handed to Tk's PhotoImage, then block-upscaled
    with .zoom().

Click to zoom in, right-click to zoom out, R to reset, S to cycle palettes.
"""
import base64
import math
import struct
import time
import tkinter as tk
import zlib

W, H = 640, 480                 # canvas size in pixels
PASSES = (8, 4, 2, 1)           # block size per pass: coarse -> exact
ROWS_PER_TICK = 12              # work slice between UI events
HOME = (-0.6, 0.0, 3.2)         # center x, center y, span across the width


def png_bytes(rgb: bytes, w: int, h: int) -> bytes:
    """Minimal RGB PNG encoder. Tk reads PNG (and base64 of it); it will NOT
    read a base64 PPM, which is the obvious-looking shortcut that doesn't work.
    Each scanline gets a leading filter byte 0, the lot is zlib-deflated, and
    every chunk carries its own CRC32."""
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def palette(kind: int) -> list[tuple[int, int, int]]:
    """256 RGB entries. Index 255 is reserved for points inside the set."""
    out = []
    for i in range(256):
        t = i / 255
        if kind == 0:            # ember
            r, g, b = t ** 0.5, t ** 1.7, t ** 3.2
        elif kind == 1:          # ice
            r, g, b = t ** 3.0, t ** 1.4, t ** 0.6
        else:                    # spectrum
            a = t * 6.28318
            r = 0.5 + 0.5 * math.cos(a)
            g = 0.5 + 0.5 * math.cos(a + 2.094)
            b = 0.5 + 0.5 * math.cos(a + 4.188)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    out[255] = (8, 10, 20)       # inside the set: near-black
    return out


def escape(cr: float, ci: float, max_iter: int) -> int:
    """Iterations before |z| escapes, 255 if it never does.

    The cardioid/period-2 tests skip the two big interior regions outright —
    without them most of a home-view render is spent proving the obvious.
    """
    q = (cr - 0.25) ** 2 + ci * ci
    if q * (q + (cr - 0.25)) <= 0.25 * ci * ci:
        return 255
    if (cr + 1.0) ** 2 + ci * ci <= 0.0625:
        return 255
    zr = zi = 0.0
    for n in range(max_iter):
        zr2, zi2 = zr * zr, zi * zi
        if zr2 + zi2 > 4.0:
            # Smooth (fractional) escape count, so bands don't posterize.
            mu = n + 1 - math.log(math.log(math.sqrt(zr2 + zi2))) / math.log(2)
            # Gamma-curve the escape fraction. Linear scaling crushes every
            # deep-zoom pixel into the palette's first few entries, because
            # max_iter grows far faster than typical escape counts do.
            return max(0, min(254, int(254 * (mu / max_iter) ** 0.35)))
        zi = 2 * zr * zi + ci
        zr = zr2 - zi2 + cr
    return 255


class Explorer:
    def __init__(self, root: tk.Tk):
        self.cx, self.cy, self.span = HOME
        self.pal_kind = 0
        self.pal = palette(0)
        self.photo = None            # keep a reference or Tk drops the image
        self.job = None              # pending after() id, so we can cancel

        root.title("Python · Mandelbrot explorer — Unified Base demo")
        root.configure(bg="#0d1117")
        tk.Label(root, text="Python · tkinter Mandelbrot explorer",
                 bg="#0d1117", fg="#e6edf3",
                 font=("TkDefaultFont", 15, "bold")).pack(pady=(12, 2))
        tk.Label(root, text="click = zoom in    right-click = zoom out    "
                            "R = reset    S = palette",
                 bg="#0d1117", fg="#7d8590").pack()

        self.canvas = tk.Canvas(root, width=W, height=H, bg="#0d1117",
                                highlightthickness=1,
                                highlightbackground="#30363d")
        self.canvas.pack(padx=14, pady=10)
        self.status = tk.Label(root, text="", bg="#0d1117", fg="#9fd8ef",
                               font=("monospace", 10))
        self.status.pack(pady=(0, 12))

        self.canvas.bind("<Button-1>", lambda e: self.zoom(e.x, e.y, 0.4))
        self.canvas.bind("<Button-3>", lambda e: self.zoom(e.x, e.y, 2.5))
        root.bind("r", lambda _e: self.reset())
        root.bind("s", lambda _e: self.cycle_palette())
        self.render()

    # -- view -------------------------------------------------------------
    def reset(self):
        self.cx, self.cy, self.span = HOME
        self.render()

    def cycle_palette(self):
        self.pal_kind = (self.pal_kind + 1) % 3
        self.pal = palette(self.pal_kind)
        self.render()

    def zoom(self, px: int, py: int, factor: float):
        """Re-centre on the clicked point, then scale the span."""
        self.cx += (px / W - 0.5) * self.span
        self.cy += (py / H - 0.5) * self.span * (H / W)
        self.span *= factor
        self.render()

    @property
    def max_iter(self) -> int:
        # Deeper zooms need more iterations to keep detail from flattening out.
        return int(90 + 55 * max(0.0, math.log2(HOME[2] / self.span)))

    # -- rendering --------------------------------------------------------
    def render(self):
        if self.job is not None:
            self.canvas.after_cancel(self.job)
            self.job = None
        self.pass_index = 0
        self.t0 = time.perf_counter()
        self.start_pass()

    def start_pass(self):
        self.block = PASSES[self.pass_index]
        self.pw, self.ph = W // self.block, H // self.block
        self.rows = bytearray()
        self.row = 0
        self.inside = 0          # pixels that never escaped, for the hint below
        self.job = self.canvas.after(1, self.work)

    def work(self):
        """Compute a slice of rows, then yield back to Tk's event loop."""
        mi = self.max_iter
        x0 = self.cx - self.span / 2
        y0 = self.cy - self.span * (H / W) / 2
        dx = self.span / self.pw
        dy = self.span * (H / W) / self.ph
        stop = min(self.row + ROWS_PER_TICK, self.ph)
        for py in range(self.row, stop):
            ci = y0 + py * dy
            row = bytearray()
            for px in range(self.pw):
                n = escape(x0 + px * dx, ci, mi)
                self.inside += n == 255
                row += bytes(self.pal[n])
            self.rows += row
        self.row = stop

        if self.row < self.ph:
            self.job = self.canvas.after(1, self.work)
            return
        self.show()
        self.pass_index += 1
        if self.pass_index < len(PASSES):
            self.job = self.canvas.after(1, self.start_pass)
        else:
            self.job = None

    def show(self):
        """Hand the raw pixels to Tk as a PNG, upscaled to fill the canvas."""
        data = base64.b64encode(png_bytes(bytes(self.rows), self.pw, self.ph))
        img = tk.PhotoImage(data=data)
        if self.block > 1:
            img = img.zoom(self.block)      # nearest-neighbour block upscale
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=img)
        self.photo = img
        ms = (time.perf_counter() - self.t0) * 1000
        zoom = HOME[2] / self.span
        # Zooming into the middle of the set paints a uniform black rectangle;
        # say so rather than leaving the user staring at an empty canvas.
        hint = ("   all inside the set — right-click to zoom out"
                if self.inside == self.pw * self.ph else "")
        self.status.config(
            text=f"c {self.cx:+.8f} {self.cy:+.8f}  zoom {zoom:,.0f}x  "
                 f"iter {self.max_iter}  pass {self.block}px  {ms:.0f} ms{hint}")


if __name__ == "__main__":
    root = tk.Tk()
    Explorer(root)
    root.mainloop()
