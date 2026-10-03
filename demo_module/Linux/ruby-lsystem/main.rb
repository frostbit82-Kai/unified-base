#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Ruby — Unified Base demo #2: an L-system (Lindenmayer system) plotter.
#
# An L-system grows a drawing instruction string by repeatedly rewriting
# characters through a rule table, then a turtle walks that string. It is a
# showcase for what Ruby is actually pleasant at: string rewriting, Structs,
# blocks, and Enumerable — the graphics are just the output.
#
# Pick a system, drag the depth slider, watch the string explode from a handful
# of characters into tens of thousands and the curve fill in.

require 'tk'

CANVAS_W = 720
CANVAS_H = 520
BG       = '#0d1117'

# axiom  : starting string
# rules  : character => replacement, applied simultaneously each generation
# angle  : degrees turned by + and -
# heading: initial direction in degrees (0 = east, -90 = north)
# max    : depth cap that keeps the segment count sane for a canvas
System = Struct.new(:name, :axiom, :rules, :angle, :heading, :max, :palette)

SYSTEMS = [
  System.new('Koch snowflake', 'F--F--F', { 'F' => 'F+F--F+F' },
             60, 0, 5, %w[#7ee787 #56d364 #2ea043]),
  System.new('Dragon curve', 'FX', { 'X' => 'X+YF+', 'Y' => '-FX-Y' },
             90, 0, 14, %w[#79c0ff #58a6ff #1f6feb]),
  System.new('Sierpinski arrowhead', 'A', { 'A' => 'B-A-B', 'B' => 'A+B+A' },
             60, 0, 8, %w[#ffa657 #f0883e #db6d28]),
  System.new('Fractal plant', 'X', { 'X' => 'F+[[X]-X]-F[-FX]+X', 'F' => 'FF' },
             25, -90, 6, %w[#7ee787 #56d364 #238636]),
  System.new('Hilbert curve', 'A', { 'A' => '+BF-AFA-FB+', 'B' => '-AF+BFB+FA-' },
             90, 0, 7, %w[#d2a8ff #bc8cff #8957e5])
].freeze

# Rewrite the axiom `depth` times. `gsub` with a hash does the whole generation
# in one pass — every character is replaced from the ORIGINAL string, which is
# exactly the simultaneous-rewrite semantics an L-system calls for.
def expand(system, depth)
  pattern = Regexp.union(system.rules.keys)
  depth.times.reduce(system.axiom) { |s, _| s.gsub(pattern, system.rules) }
end

# Walk the string, emitting [x1, y1, x2, y2] segments in turtle space.
# F and A/B move forward; + and - turn; [ and ] push and pop state.
def segments(str, angle_deg, heading_deg)
  x = y = 0.0
  heading = heading_deg * Math::PI / 180
  step = angle_deg * Math::PI / 180
  stack = []
  out = []
  str.each_char do |c|
    case c
    when 'F', 'G', 'A', 'B'
      nx = x + Math.cos(heading)
      ny = y + Math.sin(heading)
      out << [x, y, nx, ny]
      x, y = nx, ny
    when '+' then heading += step
    when '-' then heading -= step
    when '[' then stack.push([x, y, heading])
    when ']' then x, y, heading = stack.pop
    end
  end
  out
end

# Scale/translate segments to fill the canvas with a margin, preserving aspect.
def fit(segs, width, height, margin = 24)
  xs = segs.flat_map { |s| [s[0], s[2]] }
  ys = segs.flat_map { |s| [s[1], s[3]] }
  span_x = [xs.max - xs.min, 1e-9].max
  span_y = [ys.max - ys.min, 1e-9].max
  scale = [(width - 2 * margin) / span_x, (height - 2 * margin) / span_y].min
  dx = (width - span_x * scale) / 2 - xs.min * scale
  dy = (height - span_y * scale) / 2 - ys.min * scale
  segs.map { |x1, y1, x2, y2|
    [x1 * scale + dx, y1 * scale + dy, x2 * scale + dx, y2 * scale + dy]
  }
end

# `ruby main.rb --selftest` checks the rewriting/turtle math without opening a
# window — the only part of this file that can be wrong in a subtle way.
if ARGV.include?('--selftest')
  koch = SYSTEMS.first
  raise 'axiom' unless expand(koch, 0) == 'F--F--F'
  raise 'one generation' unless expand(koch, 1) == 'F+F--F+F--F+F--F+F--F+F--F+F'
  # Rules must apply to the ORIGINAL string each pass, not to their own output:
  # 3 F's -> 12 -> 48, so lengths run 7, 28, 112 (F_count * 8 + separators).
  raise 'growth' unless [1, 2, 3].map { |d| expand(koch, d).length } ==
                        [28, 112, 448]
  dragon = SYSTEMS[1]
  raise 'X/Y are not drawn' unless segments('FXY', 90, 0).size == 1
  raise 'brackets restore state' unless segments('F[+F]F', 25, 0).size == 3
  segs = fit(segments(expand(dragon, 6), dragon.angle, dragon.heading),
             CANVAS_W, CANVAS_H)
  xs = segs.flat_map { |s| [s[0], s[2]] }
  ys = segs.flat_map { |s| [s[1], s[3]] }
  raise 'fit stays on canvas' unless xs.min >= 0 && xs.max <= CANVAS_W &&
                                     ys.min >= 0 && ys.max <= CANVAS_H
  puts "ALL CHECKS PASS (#{segs.size} dragon segments fitted)"
  exit 0
end

root = TkRoot.new { title 'Ruby · L-system plotter — Unified Base demo' }
root.background = BG

TkLabel.new(root) do
  text 'Ruby · L-system plotter'
  font TkFont.new('size' => 15, 'weight' => 'bold')
  background BG
  foreground '#e6edf3'
  pack(pady: [12, 2])
end

controls = TkFrame.new(root) { background BG }.pack(pady: 4)
canvas = TkCanvas.new(root) do
  width CANVAS_W
  height CANVAS_H
  background BG
  highlightthickness 1
  highlightbackground '#30363d'
  pack(padx: 14, pady: 8)
end
status = TkLabel.new(root) do
  font TkFont.new('family' => 'monospace', 'size' => 10)
  background BG
  foreground '#9fd8ef'
  pack(pady: [0, 12])
end

choice = TkVariable.new(SYSTEMS.first.name)
depth  = TkVariable.new(4)

def draw(canvas, status, system, depth)
  t0 = Time.now
  depth = [depth, system.max].min
  str = expand(system, depth)
  segs = fit(segments(str, system.angle, system.heading), CANVAS_W, CANVAS_H)
  canvas.delete('all')
  # Colour by position along the path so the drawing order is visible.
  segs.each_with_index do |(x1, y1, x2, y2), i|
    shade = system.palette[i * system.palette.size / [segs.size, 1].max]
    TkcLine.new(canvas, x1, y1, x2, y2, fill: shade, width: 1)
  end
  ms = ((Time.now - t0) * 1000).round
  status.text = format('%-22s depth %d/%d   %d chars   %d segments   %d ms',
                       system.name, depth, system.max, str.length, segs.size, ms)
end

redraw = lambda do
  system = SYSTEMS.find { |s| s.name == choice.value }
  draw(canvas, status, system, depth.value.to_i)
end

TkOptionMenubutton.new(controls, choice, *SYSTEMS.map(&:name)) do
  background '#21262d'
  foreground '#e6edf3'
  pack(side: 'left', padx: 6)
end
choice.trace('w') { redraw.call }

TkLabel.new(controls) do
  text 'depth'
  background BG
  foreground '#7d8590'
  pack(side: 'left', padx: [12, 4])
end
TkScale.new(controls) do
  from 1
  to 14
  orient 'horizontal'
  length 220
  variable depth
  background BG
  foreground '#e6edf3'
  troughcolor '#21262d'
  highlightthickness 0
  showvalue true
  command { redraw.call }
  pack(side: 'left')
end

redraw.call
Tk.mainloop
