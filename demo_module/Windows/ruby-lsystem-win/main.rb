#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Ruby — Unified Base Windows demo: the L-system plotter, on Win32.
#
# The Windows twin of demo_module/Linux/ruby-lsystem. The L-system half —
# SYSTEMS, expand, segments, fit, and the self-test — is the Linux file's,
# unchanged. The window is not: the `tk` gem is a C extension that needs a
# compiler and Tcl/Tk dev files on Windows, so this one talks to Win32
# directly through Fiddle, which ships with Ruby. A window class whose
# window procedure is a Ruby block, a real combo box and trackbar, and GDI:
# the whole curve goes out in one PolyPolyline call per colour.

require 'fiddle'
require 'fiddle/import'

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

abort 'This twin draws with Win32 — on Linux, run demo_module/Linux/ruby-lsystem.' unless Gem.win_platform?

# Common Controls 6 for a process without a manifest of its own: build an
# activation context from app.manifest and activate it *before* comctl32
# loads below — the loader then picks the themed v6 from WinSxS.
module ActCtx
  extend Fiddle::Importer
  dlload 'kernel32.dll'
  extern 'void* CreateActCtxW(void*)'
  extern 'int ActivateActCtx(void*, void*)'
end
manifest = "#{File.expand_path('app.manifest', __dir__).tr('/', '\\')}\0".encode('UTF-16LE')
ctx = ActCtx.CreateActCtxW([56, 0, Fiddle::Pointer[manifest].to_i, 0, 0, 0, 0, 0, 0].pack('LLQSSx4QQQQ'))
ActCtx.ActivateActCtx(ctx, "\0" * 8) unless [0, -1, 2**64 - 1].include?(ctx.to_i)

# ---------------------------------------------------------------------------
# Win32 through Fiddle. Fiddle::Importer reads C prototypes; handles are void*
# (a Fiddle::Pointer back, an Integer or nil going in), strings go in as
# UTF-16LE byte strings with a terminating NUL.
# ---------------------------------------------------------------------------
module Win
  extend Fiddle::Importer
  dlload 'user32.dll', 'gdi32.dll', 'kernel32.dll', 'comctl32.dll'

  extern 'int SetProcessDpiAwarenessContext(intptr_t)'
  extern 'void* GetModuleHandleW(void*)'
  extern 'unsigned short RegisterClassExW(void*)'
  extern 'void* CreateWindowExW(unsigned int, void*, void*, unsigned int, int, int, int, int, void*, void*, void*, void*)'
  extern 'intptr_t DefWindowProcW(void*, unsigned int, uintptr_t, intptr_t)'
  extern 'int GetMessageW(void*, void*, unsigned int, unsigned int)'
  extern 'int TranslateMessage(void*)'
  extern 'intptr_t DispatchMessageW(void*)'
  extern 'void PostQuitMessage(int)'
  extern 'void* LoadCursorW(void*, uintptr_t)'
  extern 'int ShowWindow(void*, int)'
  extern 'intptr_t SendMessageW(void*, unsigned int, uintptr_t, intptr_t)'
  extern 'int MoveWindow(void*, int, int, int, int, int)'
  extern 'int GetClientRect(void*, void*)'
  extern 'int InvalidateRect(void*, void*, int)'
  extern 'void* BeginPaint(void*, void*)'
  extern 'int EndPaint(void*, void*)'
  extern 'unsigned int GetDpiForWindow(void*)'
  extern 'unsigned int GetDpiForSystem()'
  extern 'int InitCommonControlsEx(void*)'
  extern 'void* CreateCompatibleDC(void*)'
  extern 'void* CreateCompatibleBitmap(void*, int, int)'
  extern 'void* SelectObject(void*, void*)'
  extern 'int DeleteObject(void*)'
  extern 'int DeleteDC(void*)'
  extern 'int BitBlt(void*, int, int, int, int, void*, int, int, unsigned int)'
  extern 'void* CreateSolidBrush(unsigned int)'
  extern 'int FillRect(void*, void*, void*)'
  extern 'void* CreatePen(int, int, unsigned int)'
  extern 'int PolyPolyline(void*, void*, void*, unsigned int)'
  extern 'int SetBkMode(void*, int)'
  extern 'unsigned int SetTextColor(void*, unsigned int)'
  extern 'int TextOutW(void*, int, int, void*, int)'
  extern 'void* CreateFontW(int, int, int, int, int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, void*)'
  extern 'void* GetDC(void*)'
  extern 'int ReleaseDC(void*, void*)'

  WM_DESTROY = 0x0002
  WM_SIZE = 0x0005
  WM_PAINT = 0x000F
  WM_ERASEBKGND = 0x0014
  WM_SETFONT = 0x0030
  WM_COMMAND = 0x0111
  WM_HSCROLL = 0x0114
  WM_CTLCOLORSTATIC = 0x0138
  CB_ADDSTRING = 0x0143
  CB_GETCURSEL = 0x0147
  CB_SETCURSEL = 0x014E
  CBN_SELCHANGE = 1
  TBM_GETPOS = 0x0400
  TBM_SETPOS = 0x0405
  TBM_SETRANGE = 0x0406
  WS_OVERLAPPEDWINDOW = 0x00CF0000
  WS_CLIPCHILDREN = 0x02000000
  WS_CHILD = 0x40000000
  WS_VISIBLE = 0x10000000
  WS_VSCROLL = 0x00200000
  CBS_DROPDOWNLIST = 0x0003
  SRCCOPY = 0x00CC0020

  def self.w(str) = (str + "\0").encode('UTF-16LE')

  # COLORREF is 0x00BBGGRR — '#rrggbb' back to front.
  def self.rgb(hex)
    r, g, b = hex.delete('#').scan(/../).map(&:hex)
    r | (g << 8) | (b << 16)
  end
end

# ---------------------------------------------------------------------------
class Plotter
  ID_SYSTEM = 101
  ID_DEPTH = 102

  def initialize
    Win.SetProcessDpiAwarenessContext(-4) # per-monitor v2: real pixels
    icc = [8, 0x4].pack('LL')               # ICC_BAR_CLASSES: the trackbar
    Win.InitCommonControlsEx(icc)
    @system = SYSTEMS[1]
    @depth = 10
    @status = ''
    @bmp = nil
    @bg_brush = Win.CreateSolidBrush(Win.rgb(BG))
    # The window procedure is this block. Fiddle hands it to Windows as a C
    # function pointer; the constant keeps it alive for as long as Windows
    # may call it. A Ruby exception must never unwind into user32. Fiddle
    # runs the block with its own `self`, so the plotter is a local here.
    plotter = self
    @proc = Win.bind('intptr_t wndproc(void*, unsigned int, uintptr_t, intptr_t)') do |hwnd, msg, wp, lp|
      plotter.send(:handle, hwnd, msg, wp, lp)
    rescue StandardError => e
      warn "#{e.class}: #{e.message}"
      Win.DefWindowProcW(hwnd, msg, wp, lp)
    end
    create_window
  end

  def run
    msg = "\0" * 48 # MSG
    while Win.GetMessageW(msg, nil, 0, 0) > 0
      Win.TranslateMessage(msg)
      Win.DispatchMessageW(msg)
    end
  end

  private

  def create_window
    inst = Win.GetModuleHandleW(nil)
    @class_name = Win.w('UbRubyLSystem')
    wc = [80, 3, @proc.to_i, 0, 0, inst.to_i, 0, Win.LoadCursorW(nil, 32_512).to_i,
          0, 0, Fiddle::Pointer[@class_name].to_i, 0].pack('LLQllQQQQQQQ')
    Win.RegisterClassExW(wc)
    s = Win.GetDpiForSystem / 96.0
    @hwnd = Win.CreateWindowExW(0, @class_name, Win.w('Ruby · L-system plotter — Unified Base Windows demo'),
                                Win::WS_OVERLAPPEDWINDOW | Win::WS_CLIPCHILDREN,
                                -0x80000000, -0x80000000, (780 * s).to_i, (680 * s).to_i,
                                nil, nil, inst, nil)
    @font = Win.CreateFontW(-(13 * s).to_i, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, Win.w('Segoe UI'))
    @mono = Win.CreateFontW(-(13 * s).to_i, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, Win.w('Consolas'))
    @title_font = Win.CreateFontW(-(20 * s).to_i, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 5, 0, Win.w('Segoe UI'))
    @combo = child('COMBOBOX', Win::CBS_DROPDOWNLIST | Win::WS_VSCROLL, ID_SYSTEM)
    SYSTEMS.each { |sys| Win.SendMessageW(@combo, Win::CB_ADDSTRING, 0, Fiddle::Pointer[Win.w(sys.name)].to_i) }
    Win.SendMessageW(@combo, Win::CB_SETCURSEL, SYSTEMS.index(@system), 0)
    @slider = child('msctls_trackbar32', 0, ID_DEPTH)
    Win.SendMessageW(@slider, Win::TBM_SETRANGE, 1, (14 << 16) | 1)
    Win.SendMessageW(@slider, Win::TBM_SETPOS, 1, @depth)
    Win.ShowWindow(@hwnd, 5)
  end

  def child(cls, style, id)
    h = Win.CreateWindowExW(0, Win.w(cls), nil, Win::WS_CHILD | Win::WS_VISIBLE | style,
                            0, 0, 10, 10, @hwnd, id, nil, nil)
    Win.SendMessageW(h, Win::WM_SETFONT, @font.to_i, 1)
    h
  end

  def scale = Win.GetDpiForWindow(@hwnd) / 96.0

  def client_size
    rc = "\0" * 16
    Win.GetClientRect(@hwnd, rc)
    rc.unpack('l4')[2, 2]
  end

  def handle(hwnd, msg, wp, lp)
    case msg
    when Win::WM_SIZE
      layout
      render
      0
    when Win::WM_COMMAND
      if (wp & 0xFFFF) == ID_SYSTEM && (wp >> 16) == Win::CBN_SELCHANGE
        @system = SYSTEMS[Win.SendMessageW(@combo, Win::CB_GETCURSEL, 0, 0)]
        render
      end
      0
    when Win::WM_HSCROLL
      depth = Win.SendMessageW(@slider, Win::TBM_GETPOS, 0, 0)
      if depth != @depth
        @depth = depth
        render
      end
      0
    when Win::WM_CTLCOLORSTATIC # the trackbar asks for its background
      @bg_brush.to_i
    when Win::WM_ERASEBKGND then 1
    when Win::WM_PAINT
      ps = "\0" * 72
      dc = Win.BeginPaint(hwnd, ps)
      w, h = client_size
      if @bmp
        mem = Win.CreateCompatibleDC(dc)
        old = Win.SelectObject(mem, @bmp)
        Win.BitBlt(dc, 0, 0, w, h, mem, 0, 0, Win::SRCCOPY)
        Win.SelectObject(mem, old)
        Win.DeleteDC(mem)
      end
      Win.EndPaint(hwnd, ps)
      0
    when Win::WM_DESTROY
      Win.PostQuitMessage(0)
      0
    else
      Win.DefWindowProcW(hwnd, msg, wp, lp)
    end
  end

  def layout
    s = scale
    Win.MoveWindow(@combo, (16 * s).to_i, (52 * s).to_i, (220 * s).to_i, (300 * s).to_i, 1)
    Win.MoveWindow(@slider, (300 * s).to_i, (50 * s).to_i, (260 * s).to_i, (30 * s).to_i, 1)
  end

  # Draw the whole client area into a bitmap once per change; WM_PAINT then
  # only copies it. A 16k-segment dragon is one PolyPolyline per colour.
  def render
    w, h = client_size
    return if w < 50 || h < 120

    s = scale
    t0 = Time.now
    depth = [@depth, @system.max].min
    str = expand(@system, depth)
    top = (92 * s).to_i
    bottom = h - (30 * s).to_i
    segs = fit(segments(str, @system.angle, @system.heading), w, bottom - top)

    dc = Win.GetDC(@hwnd)
    mem = Win.CreateCompatibleDC(dc)
    bmp = Win.CreateCompatibleBitmap(dc, w, h)
    Win.ReleaseDC(@hwnd, dc)
    old_bmp = Win.SelectObject(mem, bmp)
    Win.FillRect(mem, [0, 0, w, h].pack('l4'), @bg_brush)
    Win.SetBkMode(mem, 1)

    # Colour by position along the path: one pen and one call per band.
    bands = @system.palette.size
    per = (segs.size.to_f / bands).ceil.clamp(1, nil)
    segs.each_slice(per).with_index do |band, i|
      pen = Win.CreatePen(0, [1, s.round].max, Win.rgb(@system.palette[i]))
      old_pen = Win.SelectObject(mem, pen)
      pts = band.flat_map { |x1, y1, x2, y2| [x1.round, y1.round + top, x2.round, y2.round + top] }.pack('l*')
      Win.PolyPolyline(mem, pts, ([2] * band.size).pack('L*'), band.size)
      Win.SelectObject(mem, old_pen)
      Win.DeleteObject(pen)
    end
    ms = ((Time.now - t0) * 1000).round
    @status = format('%-22s depth %d/%d   %s chars   %s segments   %d ms',
                     @system.name, depth, @system.max, group(str.length), group(segs.size), ms)

    text(mem, @title_font, 'Ruby · L-system plotter · Win32 through Fiddle', (16 * s).to_i, (12 * s).to_i, '#e6edf3')
    text(mem, @font, 'depth', (252 * s).to_i, (56 * s).to_i, '#7d8590')
    text(mem, @mono, @status, (16 * s).to_i, bottom + (6 * s).to_i, '#9fd8ef')
    Win.SelectObject(mem, old_bmp)
    Win.DeleteDC(mem)
    Win.DeleteObject(@bmp) if @bmp
    @bmp = bmp
    Win.InvalidateRect(@hwnd, nil, 0)
  end

  def text(dc, font, str, x, y, color)
    old = Win.SelectObject(dc, font)
    Win.SetTextColor(dc, Win.rgb(color))
    wide = str.encode('UTF-16LE')
    Win.TextOutW(dc, x, y, wide, wide.bytesize / 2)
    Win.SelectObject(dc, old)
  end

  def group(n) = n.to_s.reverse.scan(/\d{1,3}/).join(',').reverse
end

Plotter.new.run
