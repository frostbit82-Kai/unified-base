#!/usr/bin/env python3
"""Python - Unified Base demo.

A zero-dependency tkinter GUI: a ball bounces smoothly (~60fps) around a
Canvas, a title label sits on top, and a button cycles the ball's color.
Standard library only - no pip installs, so it launches instantly.
"""

import tkinter as tk

WIDTH, HEIGHT = 640, 420
RADIUS = 26
FRAME_MS = 16  # ~60 frames per second

# A friendly rotation of ball colors the button steps through.
COLORS = [
    "#4f8cff",  # blue
    "#ff5d73",  # coral
    "#39d98a",  # green
    "#ffc857",  # amber
    "#b980f0",  # violet
    "#ff8f4c",  # orange
]

BG = "#0f1220"
PANEL = "#171a2b"
INK = "#e8ecff"
SUBTLE = "#8b93b8"


class BouncingBall:
    def __init__(self, root):
        self.root = root
        root.title("Python - Unified Base demo")
        root.configure(bg=BG)
        root.minsize(WIDTH, HEIGHT + 96)

        # Title bar.
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(
            header,
            text="Python - Unified Base demo",
            font=("DejaVu Sans", 18, "bold"),
            fg=INK,
            bg=BG,
        ).pack(side="left")
        tk.Label(
            header,
            text="tkinter - standard library only",
            font=("DejaVu Sans", 10),
            fg=SUBTLE,
            bg=BG,
        ).pack(side="left", padx=(12, 0), pady=(6, 0))

        # Canvas the ball lives on.
        self.canvas = tk.Canvas(
            root,
            width=WIDTH,
            height=HEIGHT,
            bg=PANEL,
            highlightthickness=0,
        )
        self.canvas.pack(padx=16, pady=6)

        self.color_index = 0
        self.ball = self.canvas.create_oval(
            0, 0, RADIUS * 2, RADIUS * 2,
            fill=COLORS[self.color_index],
            outline="",
        )
        # A soft trailing glow drawn behind the ball.
        self.glow = self.canvas.create_oval(
            0, 0, RADIUS * 2, RADIUS * 2,
            outline=COLORS[self.color_index],
            width=2,
        )
        self.canvas.tag_lower(self.glow, self.ball)

        self.x, self.y = 60.0, 80.0
        self.dx, self.dy = 3.4, 2.6
        self.bounces = 0

        # Footer: bounce counter + color button.
        footer = tk.Frame(root, bg=BG)
        footer.pack(fill="x", padx=16, pady=(6, 14))
        self.counter = tk.Label(
            footer,
            text="Bounces: 0",
            font=("DejaVu Sans Mono", 11),
            fg=SUBTLE,
            bg=BG,
        )
        self.counter.pack(side="left")

        self.button = tk.Button(
            footer,
            text="Change color",
            font=("DejaVu Sans", 11, "bold"),
            fg="#0f1220",
            bg=COLORS[self.color_index],
            activebackground=INK,
            relief="flat",
            padx=18,
            pady=8,
            cursor="hand2",
            command=self.change_color,
        )
        self.button.pack(side="right")

        self._place_ball()
        self.animate()

    def change_color(self):
        self.color_index = (self.color_index + 1) % len(COLORS)
        color = COLORS[self.color_index]
        self.canvas.itemconfig(self.ball, fill=color)
        self.canvas.itemconfig(self.glow, outline=color)
        self.button.configure(bg=color)

    def _place_ball(self):
        self.canvas.coords(
            self.ball,
            self.x, self.y, self.x + RADIUS * 2, self.y + RADIUS * 2,
        )
        # Glow sits slightly larger and centered on the ball.
        self.canvas.coords(
            self.glow,
            self.x - 4, self.y - 4,
            self.x + RADIUS * 2 + 4, self.y + RADIUS * 2 + 4,
        )

    def animate(self):
        self.x += self.dx
        self.y += self.dy

        bounced = False
        if self.x <= 0:
            self.x = 0
            self.dx = abs(self.dx)
            bounced = True
        elif self.x + RADIUS * 2 >= WIDTH:
            self.x = WIDTH - RADIUS * 2
            self.dx = -abs(self.dx)
            bounced = True

        if self.y <= 0:
            self.y = 0
            self.dy = abs(self.dy)
            bounced = True
        elif self.y + RADIUS * 2 >= HEIGHT:
            self.y = HEIGHT - RADIUS * 2
            self.dy = -abs(self.dy)
            bounced = True

        if bounced:
            self.bounces += 1
            self.counter.configure(text=f"Bounces: {self.bounces}")

        self._place_ball()
        self.root.after(FRAME_MS, self.animate)


def main():
    root = tk.Tk()
    BouncingBall(root)
    root.mainloop()


if __name__ == "__main__":
    main()
