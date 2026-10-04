# C# — Unified Base Windows demo #2: the Windows Runtime from a desktop app

The APIs Windows ships for Store apps work just as well from a plain .NET
desktop program. Target `net10.0-windows10.0.19041.0` and `Windows.*` shows
up as ordinary C# namespaces — no packaging, no Store, no XAML islands. This
WPF window uses four corners of it:

| Tab | API | What you see |
|---|---|---|
| Read the screen | `Windows.Media.Ocr` | your screen captured (GDI `BitBlt`), read by Windows' on-device OCR, every word boxed; the text alongside |
| Voices | `Windows.Media.SpeechSynthesis` | the OneCore voices (Narrator's engine), with each word highlighted as it is spoken |
| This PC | `UISettings`, `PowerManager`, `NetworkInformation`, `GlobalizationPreferences`, `AnalyticsInfo` | the full accent palette, text scale, battery and energy saver, Wi-Fi signal and metering, region — live |
| Devices | `DeviceInformation` + `DeviceWatcher` | audio outputs, microphones, cameras, portable storage — plug something in and its card updates |

## Demonstrates
- **C#/WinRT projections**: a versioned target framework is the whole
  setup; the SDK restores `Microsoft.Windows.SDK.NET.Ref` on first build.
- **Win32 and WinRT together**: the screen comes from GDI via P/Invoke
  (`BitBlt` with `CAPTUREBLT`, a top-down DIB), then becomes a WinRT
  `SoftwareBitmap` for the OCR engine. Images over the engine's size limit
  are halved until they fit, and the word boxes scaled back.
- **Word timing from the engine**: with `IncludeWordBoundaryMetadata` the
  speech stream carries a timed-metadata track of word cues. It must be set
  to *application presented*, or `CueEntered` never fires.
- **Threads**: WinRT raises `ColorValuesChanged`, power and network events
  on worker threads; every handler marshals to WPF's dispatcher.
- **Odd encodings, decoded**: `DeviceFamilyVersion` packs four 16-bit
  version fields into one 64-bit number.
- Nothing leaves the PC: OCR and the voices run locally.

## Dependencies
- .NET SDK 10. The first build downloads the Windows SDK projections
  (~25 MB).
- OCR needs a language with *Optical character recognition* installed
  (English has it by default; otherwise Settings ▸ Time & language ▸
  Language). The tab says so if none is.

## Run
Unified Base runs this automatically (`dotnet run`). Windows-only: the
Windows Runtime has no Wine equivalent, so on Linux this module doesn't run.

Manual equivalent:

```
dotnet run
```

Check, no window, no sound: `dotnet run -- --selftest` — renders text with
WPF and expects OCR to read it back, synthesizes speech without playing it,
captures the screen.

## Files
- `WinRtDemo.csproj` — WPF on a versioned Windows target framework
- `app.manifest` — per-monitor DPI awareness (the screen capture is in real pixels)
- `Program.cs` — the four tabs and `--selftest`
