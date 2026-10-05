# C# (Avalonia) — Unified Base demo

A code-only (no `.axaml`) Avalonia GUI demo: an 800x600 window with a Canvas
holding a bouncing, hue-shifting ellipse animated at ~60fps by a `DispatcherTimer`,
plus a live bounce counter, FPS readout, and clock. Demonstrates a real, embeddable
X11 window from a C#/.NET app.

## Dependencies

- **.NET SDK 8** (`dotnet` on PATH)
- Avalonia + Avalonia.Desktop `11.1.0` — fetched automatically by `dotnet restore`
  (declared in `Demo.csproj`; no manual install needed)

## Run

Unified Base runs this automatically: it detects `Demo.csproj` (runtime `csharp`),
then runs `dotnet build` followed by `dotnet run --project Demo.csproj`.

To run it by hand:

```bash
dotnet restore
dotnet run --project Demo.csproj
```

## Files

- `Demo.csproj` — `WinExe`, `net8.0`, Avalonia package references
- `Program.cs` — entry point, `App`, and the code-defined `MainWindow`
