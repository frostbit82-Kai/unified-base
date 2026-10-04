#!/usr/bin/env ruby
# frozen_string_literal: true
#
# Ruby — Unified Base Windows demo #2: Windows through COM.
#
# COM is how Windows exposes itself to scripting languages, and Ruby has
# spoken it since 1.6 through WIN32OLE (in the box). Everything this window
# prints comes from a COM object:
#
#   WMI (winmgmts)               the system report, and *events*: a live feed
#                                of processes starting and stopping
#   Scripting.FileSystemObject   drives, their type, file system and space
#   Shell.Application            the Explorer windows open right now
#   WScript.Shell                the special folders
#   SAPI.SpVoice                 the installed voices; speaks on request
#
# The window itself is Win32 through Fiddle, as in ruby-lsystem-win.
# `ruby main.rb --selftest` queries every object and catches a real
# process-start event, without opening a window.

require 'fiddle'
require 'fiddle/import'
require 'time'
require 'win32ole'

WIN32OLE.codepage = WIN32OLE::CP_UTF8 # COM strings are UTF-16; hand them over as UTF-8

# -- COM ----------------------------------------------------------------------
class Com
  DRIVE_TYPES = %w[unknown removable fixed network optical RAM].freeze

  def initialize
    @wmi = WIN32OLE.connect('winmgmts:{impersonationLevel=impersonate}!\\\\.\\root\\cimv2')
    @fso = WIN32OLE.new('Scripting.FileSystemObject')
    @shell = WIN32OLE.new('Shell.Application')
    @wsh = WIN32OLE.new('WScript.Shell')
    @voice = nil # created on first use: loading SAPI is the slow part
  end

  def rows(query)
    out = []
    @wmi.ExecQuery(query).each { |r| out << r }
    out
  end

  def bar(frac, width = 20)
    filled = (frac.clamp(0, 1) * width).round
    ('█' * filled) + ('░' * (width - filled))
  end

  def gb(bytes) = format('%.1f GB', bytes.to_f / 1024**3)

  def system_report
    os = rows('SELECT * FROM Win32_OperatingSystem').first
    cs = rows('SELECT * FROM Win32_ComputerSystem').first
    cpu = rows('SELECT * FROM Win32_Processor').first
    gpus = rows('SELECT * FROM Win32_VideoController')
    bat = rows('SELECT * FROM Win32_Battery').first
    total = os.TotalVisibleMemorySize.to_i * 1024
    free = os.FreePhysicalMemory.to_i * 1024
    # WMI datetimes are CIM strings: 20261004011500.500000-300
    up = (Time.now - Time.strptime(os.LastBootUpTime[0, 14], '%Y%m%d%H%M%S')).to_i
    lines = []
    lines << "#{os.Caption} #{os.OSArchitecture} · #{os.Version} · " \
             "up #{up / 86_400} d #{up / 3600 % 24} h #{up / 60 % 60} min"
    lines << format('%-9s %s %s', 'Computer', cs.Manufacturer, cs.Model)
    lines << format('%-9s %s · %d cores / %d threads · %d MHz max', 'CPU', cpu.Name.strip,
                    cpu.NumberOfCores, cpu.NumberOfLogicalProcessors, cpu.MaxClockSpeed)
    lines << format('%-9s %s of %s used  %s %d %%', 'Memory', gb(total - free), gb(total),
                    bar((total - free).fdiv(total)), ((total - free) * 100.0 / total).round)
    gpus.each do |g|
      res = g.CurrentHorizontalResolution ? " · #{g.CurrentHorizontalResolution}×#{g.CurrentVerticalResolution}" : ''
      lines << format('%-9s %s%s · driver %s', 'GPU', g.Name, res, g.DriverVersion)
    end
    if bat
      on_ac = [2, 6, 7, 8, 9].include?(bat.BatteryStatus.to_i)
      lines << format('%-9s %d %% · %s', 'Battery', bat.EstimatedChargeRemaining, on_ac ? 'on AC power' : 'on battery')
    end
    lines
  end

  def drives
    out = []
    @fso.Drives.each do |d|
      type = DRIVE_TYPES[d.DriveType] || '?'
      unless d.IsReady
        out << format('%s:  %-9s (not ready)', d.DriveLetter, type)
        next
      end
      total = d.TotalSize.to_f
      used = total - d.FreeSpace.to_f
      out << format('%s:  %-9s %-6s %-14s %9s of %9s  %s', d.DriveLetter, type, d.FileSystem,
                    d.VolumeName.to_s[0, 14], gb(used), gb(total), bar(used / total))
    end
    out
  end

  def explorer_windows
    out = []
    @shell.Windows.each do |w|
      next unless w.FullName.to_s.downcase.end_with?('explorer.exe')
      out << "#{w.LocationName}  —  #{w.Document.Folder.Self.Path rescue w.LocationURL}"
    end
    out.empty? ? ['(no File Explorer windows open — open one and ask again)'] : out
  end

  def special_folders
    %w[Desktop MyDocuments Startup Fonts SendTo Templates].map do |f|
      format('%-12s %s', f, @wsh.SpecialFolders(f))
    end
  end

  def voice
    @voice ||= WIN32OLE.new('SAPI.SpVoice')
  end

  def voices
    out = []
    voice.GetVoices.each { |v| out << v.GetDescription }
    out
  end

  # SVSFlagsAsync = 1: return at once, speech plays on SAPI's own thread.
  def speak(text) = voice.Speak(text, 1)

  def stop_speaking = @voice&.Speak('', 3) # SVSFPurgeBeforeSpeak | async

  # Two event subscriptions — creation and deletion. __InstanceOperationEvent
  # would also deliver *modification* events: a flood, since a process's
  # working set changes every second. WITHIN 1 = WMI checks once a second.
  def watch_processes
    q = "SELECT * FROM %s WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'"
    @started = @wmi.ExecNotificationQuery(format(q, '__InstanceCreationEvent'))
    @stopped = @wmi.ExecNotificationQuery(format(q, '__InstanceDeletionEvent'))
  end

  def unwatch = @started = @stopped = nil

  def watching? = !@started.nil?

  # Drain whatever events have arrived. NextEvent(0) never waits: an empty
  # queue raises wbemErrTimedOut, which is the normal "nothing new".
  def process_events(wait_ms = 0)
    out = []
    [[@started, '+'], [@stopped, '-']].each do |src, sign|
      next unless src

      loop do
        ev = begin
          src.NextEvent(wait_ms)
        rescue WIN32OLE::RuntimeError
          break
        end
        p = ev.TargetInstance
        out << format('%s  %s %-24s pid %-6d %s', Time.now.strftime('%H:%M:%S'), sign, p.Name,
                      p.ProcessId, sign == '+' ? p.ExecutablePath.to_s : '')
      end
    end
    out
  end

  def summary
    os = rows('SELECT Caption FROM Win32_OperatingSystem').first
    cpu = rows('SELECT NumberOfLogicalProcessors FROM Win32_Processor').first
    "This is #{os.Caption.sub('Microsoft ', '')}, with #{cpu.NumberOfLogicalProcessors} logical processors " \
      "and #{@fso.Drives.Count} drives. Ruby read all of that through COM."
  end
end

# -- self-test ----------------------------------------------------------------
if ARGV.include?('--selftest')
  com = Com.new
  sys = com.system_report
  raise 'system report' unless sys.first =~ /Windows/ && sys.any? { |l| l.start_with?('CPU') }
  raise 'drives' unless com.drives.any? { |l| l.start_with?('C:') }
  raise 'explorer windows' unless com.explorer_windows.is_a?(Array)
  raise 'special folders' unless com.special_folders.first =~ /Desktop\s+\S/
  raise 'voices' if com.voices.empty?
  com.watch_processes
  sleep 0.5
  pid = Process.spawn('cmd.exe', '/c', 'ping -n 3 127.0.0.1 >NUL')
  seen = nil
  15.times do
    seen = com.process_events(300).find { |l| l.include?("pid #{pid}") }
    break if seen
  end
  Process.wait(pid)
  raise "no creation event for pid #{pid}" unless seen
  puts sys, "event: #{seen.strip}", "ALL CHECKS PASS (#{com.voices.size} voices)"
  exit 0
end

abort 'This demo drives Windows through COM — run it on Windows.' unless Gem.win_platform?

# -- Win32 through Fiddle -------------------------------------------------------
# Common Controls 6 for a process without a manifest: an activation context
# from app.manifest, active before comctl32 loads (see ruby-lsystem-win).
module ActCtx
  extend Fiddle::Importer
  dlload 'kernel32.dll'
  extern 'void* CreateActCtxW(void*)'
  extern 'int ActivateActCtx(void*, void*)'
end
manifest = "#{File.expand_path('app.manifest', __dir__).tr('/', '\\')}\0".encode('UTF-16LE')
ctx = ActCtx.CreateActCtxW([56, 0, Fiddle::Pointer[manifest].to_i, 0, 0, 0, 0, 0, 0].pack('LLQSSx4QQQQ'))
ActCtx.ActivateActCtx(ctx, "\0" * 8) unless [0, -1, 2**64 - 1].include?(ctx.to_i)

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
  extern 'int SetWindowTextW(void*, void*)'
  extern 'unsigned int GetDpiForWindow(void*)'
  extern 'unsigned int GetDpiForSystem()'
  extern 'uintptr_t SetTimer(void*, uintptr_t, unsigned int, void*)'
  extern 'int InitCommonControlsEx(void*)'
  extern 'void* CreateSolidBrush(unsigned int)'
  extern 'unsigned int SetTextColor(void*, unsigned int)'
  extern 'unsigned int SetBkColor(void*, unsigned int)'
  extern 'void* CreateFontW(int, int, int, int, int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, unsigned int, void*)'

  WM_DESTROY = 0x0002
  WM_SIZE = 0x0005
  WM_SETFONT = 0x0030
  WM_GETTEXTLENGTH = 0x000E
  WM_COMMAND = 0x0111
  WM_TIMER = 0x0113
  WM_CTLCOLORSTATIC = 0x0138
  EM_SETSEL = 0x00B1
  EM_REPLACESEL = 0x00C2
  EM_SETLIMITTEXT = 0x00C5
  BN_CLICKED = 0
  WS_OVERLAPPEDWINDOW = 0x00CF0000
  WS_CLIPCHILDREN = 0x02000000
  WS_CHILD = 0x40000000
  WS_VISIBLE = 0x10000000
  WS_VSCROLL = 0x00200000
  ES_MULTILINE = 0x0004
  ES_AUTOVSCROLL = 0x0040
  ES_READONLY = 0x0800
  WS_EX_CLIENTEDGE = 0x0200

  def self.w(str) = "#{str}\0".encode('UTF-16LE')
end

class ComWindow
  BUTTONS = [
    [201, 'System report', 120], [202, 'Drives', 80], [203, 'Explorer windows', 140],
    [204, 'Special folders', 130], [205, 'Voices', 80], [206, 'Speak a summary', 140],
    [207, 'Stop watching', 120], [208, 'Clear', 70]
  ].freeze

  def initialize(com)
    @com = com
    Win.SetProcessDpiAwarenessContext(-4)
    Win.InitCommonControlsEx([8, 0xFF].pack('LL'))
    @bg = Win.CreateSolidBrush(0x17110d) # #0d1117 as 0x00BBGGRR
    me = self # Fiddle runs the block with its own self
    @proc = Win.bind('intptr_t wndproc(void*, unsigned int, uintptr_t, intptr_t)') do |h, m, wp, lp|
      me.send(:handle, h, m, wp, lp)
    rescue StandardError => e
      warn "#{e.class}: #{e.message}"
      Win.DefWindowProcW(h, m, wp, lp)
    end
    create
  end

  def run
    msg = "\0" * 48
    while Win.GetMessageW(msg, nil, 0, 0) > 0
      Win.TranslateMessage(msg)
      Win.DispatchMessageW(msg)
    end
  end

  private

  def create
    inst = Win.GetModuleHandleW(nil)
    @cls = Win.w('UbRubyCom')
    wc = [80, 3, @proc.to_i, 0, 0, inst.to_i, 0, Win.LoadCursorW(nil, 32_512).to_i,
          @bg.to_i, 0, Fiddle::Pointer[@cls].to_i, 0].pack('LLQllQQQQQQQ')
    Win.RegisterClassExW(wc)
    s = Win.GetDpiForSystem / 96.0
    @hwnd = Win.CreateWindowExW(0, @cls, Win.w('Ruby · Windows through COM — Unified Base Windows demo'),
                                Win::WS_OVERLAPPEDWINDOW | Win::WS_CLIPCHILDREN,
                                -0x80000000, -0x80000000, (940 * s).to_i, (640 * s).to_i,
                                nil, nil, inst, nil)
    @ui_font = Win.CreateFontW(-(12 * s).to_i, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, Win.w('Segoe UI'))
    @mono = Win.CreateFontW(-(12 * s).to_i, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, Win.w('Consolas'))
    @buttons = BUTTONS.map do |id, text, _w|
      b = Win.CreateWindowExW(0, Win.w('BUTTON'), Win.w(text), Win::WS_CHILD | Win::WS_VISIBLE,
                              0, 0, 10, 10, @hwnd, id, nil, nil)
      Win.SendMessageW(b, Win::WM_SETFONT, @ui_font.to_i, 1)
      b
    end
    @out = Win.CreateWindowExW(Win::WS_EX_CLIENTEDGE, Win.w('EDIT'), nil,
                               Win::WS_CHILD | Win::WS_VISIBLE | Win::WS_VSCROLL | Win::ES_MULTILINE |
                               Win::ES_AUTOVSCROLL | Win::ES_READONLY, 0, 0, 10, 10, @hwnd, 300, nil, nil)
    Win.SendMessageW(@out, Win::WM_SETFONT, @mono.to_i, 1)
    Win.SendMessageW(@out, Win::EM_SETLIMITTEXT, 0, 0) # 0 = as large as it gets
    Win.ShowWindow(@hwnd, 5)
    section('Windows through COM — every line below came from a COM object') do
      ['Click a button for more. Start or close any program to see it here.']
    end
    run_action(201)
    run_action(202)
    @com.watch_processes
    section('Processes starting (+) and stopping (-) — WMI events, live') { [] }
    Win.SetTimer(@hwnd, 1, 400, nil)
  end

  def append(text)
    len = Win.SendMessageW(@out, Win::WM_GETTEXTLENGTH, 0, 0)
    if len > 400_000 # keep the control light: drop the old text
      Win.SetWindowTextW(@out, Win.w(''))
      len = 0
    end
    Win.SendMessageW(@out, Win::EM_SETSEL, len, len)
    wide = Win.w(text.gsub("\n", "\r\n")) # an EDIT control wants CRLF
    Win.SendMessageW(@out, Win::EM_REPLACESEL, 0, Fiddle::Pointer[wide].to_i)
  end

  def section(title)
    t0 = Time.now
    lines = yield
    ms = ((Time.now - t0) * 1000).round
    append("\n── #{title} #{"(#{ms} ms) " if ms.positive?}".ljust(78, '─') + "\n")
    lines.each { |l| append("#{l}\n") }
  rescue WIN32OLE::RuntimeError => e
    append("  COM error: #{e.message.lines.first}")
  end

  def run_action(id)
    case id
    when 201 then section('System — WMI') { @com.system_report }
    when 202 then section('Drives — Scripting.FileSystemObject') { @com.drives }
    when 203 then section('Explorer windows — Shell.Application') { @com.explorer_windows }
    when 204 then section('Special folders — WScript.Shell') { @com.special_folders }
    when 205 then section('Voices — SAPI.SpVoice') { @com.voices }
    when 206
      text = @com.summary
      section('Speaking — SAPI.SpVoice') { ["\"#{text}\""] }
      @com.speak(text)
    when 207
      if @com.watching?
        @com.unwatch
        section('Stopped watching processes') { [] }
      else
        @com.watch_processes
        section('Watching processes again') { [] }
      end
      Win.SetWindowTextW(@buttons[6], Win.w(@com.watching? ? 'Stop watching' : 'Watch processes'))
    when 208 then Win.SetWindowTextW(@out, Win.w(''))
    end
  end

  def layout
    rc = "\0" * 16
    Win.GetClientRect(@hwnd, rc)
    w, h = rc.unpack('l4')[2, 2]
    s = Win.GetDpiForWindow(@hwnd) / 96.0
    m = (8 * s).to_i
    bh = (28 * s).to_i
    x = m
    y = m
    BUTTONS.each_with_index do |(_, _, bw), i| # a flow that wraps in narrow panes
      bw = (bw * s).to_i
      if x + bw > w - m && x > m
        x = m
        y += bh + (4 * s).to_i
      end
      Win.MoveWindow(@buttons[i], x, y, bw, bh, 1)
      x += bw + (4 * s).to_i
    end
    y += bh + m
    Win.MoveWindow(@out, m, y, w - 2 * m, h - y - m, 1)
  end

  def handle(hwnd, msg, wp, lp)
    case msg
    when Win::WM_SIZE
      layout
      0
    when Win::WM_COMMAND
      run_action(wp & 0xFFFF) if (wp >> 16) == Win::BN_CLICKED && (wp & 0xFFFF).between?(201, 208)
      0
    when Win::WM_TIMER
      @com.process_events.each { |l| append("#{l}\n") }
      0
    when Win::WM_CTLCOLORSTATIC # a read-only EDIT asks here for its colours
      Win.SetTextColor(wp, 0xf3ede6)
      Win.SetBkColor(wp, 0x17110d)
      @bg.to_i
    when Win::WM_DESTROY
      @com.stop_speaking
      Win.PostQuitMessage(0)
      0
    else
      Win.DefWindowProcW(hwnd, msg, wp, lp)
    end
  end
end

ComWindow.new(Com.new).run
