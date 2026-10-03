# clock.rb — Ruby (Tk) analog + digital clock for Unified Base.
# Draws a live analog clock (hour/min/sec hands) on a TkCanvas, redrawing
# once a second via Tk.after, with a digital time label underneath.
require 'tk'

# ---- Palette --------------------------------------------------------------
BG      = '#0f1220'   # window / canvas background
FACE    = '#171a2e'   # clock face fill
RIM     = '#3b4272'   # face rim
TICK    = '#8b93c9'   # minute ticks
HOUR_T  = '#e6e9ff'   # hour numerals / big ticks
HAND_H  = '#c7d2ff'   # hour hand
HAND_M  = '#8ab4ff'   # minute hand
HAND_S  = '#ff5d73'   # second hand
HUB     = '#ffd36e'   # centre hub
ACCENT  = '#8ab4ff'

SIZE = 320                 # canvas is SIZE x SIZE
CX   = SIZE / 2.0          # centre x
CY   = SIZE / 2.0          # centre y
R    = SIZE / 2.0 - 18     # clock radius

root = TkRoot.new
root.title 'Ruby (Tk) — Unified Base demo'
root.background = BG
root.resizable(false, false)

TkLabel.new(root) do
  text     'Ruby Tk Clock'
  font     TkFont.new('Helvetica 15 bold')
  foreground ACCENT
  background BG
  pack('pady' => [12, 0])
end

canvas = TkCanvas.new(root) do
  width  SIZE
  height SIZE
  background BG
  highlightthickness 0
  pack('padx' => 18, 'pady' => 10)
end

digital = TkLabel.new(root) do
  font       TkFont.new('Courier 20 bold')
  foreground HOUR_T
  background BG
  pack('pady' => [0, 4])
end

date_lbl = TkLabel.new(root) do
  font       TkFont.new('Helvetica 10')
  foreground TICK
  background BG
  pack('pady' => [0, 14])
end

# Convert a clock angle (0 = 12 o'clock, growing clockwise) + length to (x, y).
def hand_point(cx, cy, frac, length)
  ang = (frac * 2 * Math::PI) - (Math::PI / 2)  # -90deg so 0 points up
  [cx + length * Math.cos(ang), cy + length * Math.sin(ang)]
end

# Draw the static face once (rim, ticks, numerals). Hands are drawn per tick.
def draw_face(canvas)
  canvas.create(TkcOval, CX - R, CY - R, CX + R, CY + R,
                'fill' => FACE, 'outline' => RIM, 'width' => 3)

  60.times do |i|
    big  = (i % 5).zero?
    r1   = R - (big ? 16 : 8)
    x1, y1 = hand_point(CX, CY, i / 60.0, r1)
    x2, y2 = hand_point(CX, CY, i / 60.0, R - 3)
    canvas.create(TkcLine, x1, y1, x2, y2,
                  'fill' => (big ? HOUR_T : TICK), 'width' => (big ? 3 : 1))
  end

  (1..12).each do |h|
    x, y = hand_point(CX, CY, h / 12.0, R - 34)
    canvas.create(TkcText, x, y, 'text' => h.to_s, 'fill' => HOUR_T,
                  'font' => TkFont.new('Helvetica 13 bold'))
  end
end

draw_face(canvas)

# Redraw the three hands + hub, tag them so we can wipe them each frame.
def draw_hands(canvas)
  canvas.delete('hands')
  now  = Time.now
  secs = now.sec + now.subsec.to_f            # smooth-ish seconds
  mins = now.min + secs / 60.0
  hrs  = (now.hour % 12) + mins / 60.0

  hx, hy = hand_point(CX, CY, hrs  / 12.0, R * 0.52)
  mx, my = hand_point(CX, CY, mins / 60.0, R * 0.75)
  sx, sy = hand_point(CX, CY, secs / 60.0, R * 0.82)
  # Small counterweight tail on the second hand.
  tx, ty = hand_point(CX, CY, (secs / 60.0) + 0.5, R * 0.18)

  canvas.create(TkcLine, CX, CY, hx, hy, 'fill' => HAND_H, 'width' => 7,
                'capstyle' => 'round', 'tags' => 'hands')
  canvas.create(TkcLine, CX, CY, mx, my, 'fill' => HAND_M, 'width' => 4,
                'capstyle' => 'round', 'tags' => 'hands')
  canvas.create(TkcLine, tx, ty, sx, sy, 'fill' => HAND_S, 'width' => 2,
                'capstyle' => 'round', 'tags' => 'hands')
  canvas.create(TkcOval, CX - 6, CY - 6, CX + 6, CY + 6,
                'fill' => HUB, 'outline' => BG, 'width' => 2, 'tags' => 'hands')
end

# One tick: refresh hands + text labels, then re-arm for ~1s later.
tick = proc do
  draw_hands(canvas)
  now = Time.now
  digital.text  = now.strftime('%H:%M:%S')
  date_lbl.text = now.strftime('%A, %d %B %Y')
  Tk.after(1000, &tick)
end

tick.call
Tk.mainloop
