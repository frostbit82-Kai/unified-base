# C# — Unified Base Windows demo: WPF data binding

The Windows twin of `demo_module/Linux/csharp-binding`: the same live service
dashboard, built with **WPF** instead of Avalonia. Ten services update every
600 ms; sort by name, latency, load or errors; pause the feed. Nothing in the
view is assigned after startup: the view models raise `PropertyChanged` and
the bindings do the rest.

## Why a twin
Avalonia's binding model is WPF's, carried across platforms. The view models
here are line for line the Linux demo's (only `IBrush` becomes `Brush`), so
the interesting part is what differs in the view:

| | Avalonia (Linux demo) | WPF (this demo) |
|---|---|---|
| Theme | a bare `AppBuilder` renders templated controls **invisible** until `FluentTheme` is added | always renders (Aero2 built in); `ThemeMode = Dark` (.NET 9+) adds the Windows 11 Fluent look |
| Code-only row template | `FuncDataTemplate<T>(lambda)` | `DataTemplate` + `FrameworkElementFactory` — what XAML compiles to |
| `ProgressBar.Value` binding | one-way | **two-way by default**: bound to a get-only property it throws as the row is built — `Mode = OneWay` |
| Spacing | `StackPanel.Spacing` | no such property — margins, and a `WrapPanel` that keeps buttons reachable in a narrow pane |
| Window background | Fluent paints it | Fluent asks for Mica, which an embedded child window can't have — set explicitly |

Plus a `PerMonitorV2` manifest: WPF is only system-DPI-aware without one,
and a scale change since sign-in leaves the window bitmap-stretched.

## Dependencies
- .NET SDK 10 (`winget install -e --id Microsoft.DotNet.SDK.10`; the tab's
  Install button offers it). WPF ships with the Windows Desktop runtime.

## Run
Unified Base runs this automatically (`dotnet run`). On Linux it publishes a
win-x64 `.exe` and runs it through Wine.

Manual equivalent:

```
dotnet run
```

## Files
- `BindingDemo.csproj` — `net10.0-windows`, `UseWPF`
- `app.manifest` — per-monitor DPI awareness
- `Program.cs` — view models, template, and window, all code-only
