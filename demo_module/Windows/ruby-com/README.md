# Ruby — Unified Base Windows demo #2: Windows through COM

COM is how Windows exposes itself to scripting languages, and Ruby has
spoken it since 1.6 through **WIN32OLE**, in the standard library. Every
line this window prints comes from a COM object:

| Button | COM object | Prints |
|---|---|---|
| System report *(on start)* | WMI `winmgmts:` | edition, uptime, model, CPU, memory with a bar, GPUs, battery |
| Drives *(on start)* | `Scripting.FileSystemObject` | each drive's type, file system, label, used/total |
| *(live, from the start)* | WMI **events** | every process starting (+) and stopping (−), with its path |
| Explorer windows | `Shell.Application` | the folders open in File Explorer right now |
| Special folders | `WScript.Shell` | Desktop, Documents, Startup, Fonts … |
| Voices | `SAPI.SpVoice` | the installed speech voices |
| Speak a summary | `SAPI.SpVoice` | speaks one sentence about this PC — only when pressed |

Start or close any program while it runs and watch it appear.

## Demonstrates
- **Late-bound COM from Ruby**: `WIN32OLE.new('ProgID')` and plain method
  calls (`fso.Drives.each`, `d.FreeSpace`) — no type libraries, no codegen.
  `WIN32OLE.codepage = CP_UTF8` keeps names with accents intact.
- **WMI queries and WMI events.** `ExecQuery` is WQL (SQL-ish) over the
  system; `ExecNotificationQuery` subscribes. `__InstanceCreationEvent` and
  `__InstanceDeletionEvent` are subscribed to separately:
  `__InstanceOperationEvent` would also deliver *modification* events — a
  flood, since a process's working set changes every second.
- **Polling without blocking the UI**: a 400 ms timer drains the queues with
  `NextEvent(0)`, where an empty queue raises `wbemErrTimedOut` — the normal
  "nothing new".
- **Asynchronous speech**: `Speak(text, SVSFlagsAsync)` returns at once.
- **CIM datetimes** (`20261004011500.500000-300`) parsed for the uptime.
- The window is Win32 through Fiddle, as in `ruby-lsystem-win`: a Ruby
  block as the window procedure, a read-only multi-line `EDIT` coloured via
  `WM_CTLCOLORSTATIC`, buttons that wrap in a narrow pane, Common Controls 6
  through an activation context.

## Dependencies
- Ruby 3.x for Windows (`winget install -e --id RubyInstallerTeam.Ruby.3.4`).
  No gems. WMI, the FileSystemObject, Shell and SAPI ship with Windows.

## Run
Unified Base runs this automatically (`ruby main.rb`). Windows-only.

Check, no window: `ruby main.rb --selftest` — queries every object, then
starts a process and waits for WMI to report it.

## Files
- `main.rb` — the `Com` class (all of the COM), the Win32 window, `--selftest`
- `app.manifest` — Common Controls 6, activated at run time
