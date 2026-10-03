# C# — Unified Base demo #2: Avalonia data binding

A live service dashboard. Ten services update every 600 ms; sort by name,
latency, load, or errors; pause the feed. Nothing in the view is assigned after
startup — the view models raise `PropertyChanged` and the bindings do the rest.

## Demonstrates
Where the first C# demo animates a shape on a Canvas, this is Avalonia's
binding engine:

- **INotifyPropertyChanged** — a small `Observable` base with
  `[CallerMemberName]`, so setters name their own property.
- **Derived properties** — changing `Latency` also raises `LatencyText`,
  `Health`, and `HealthBrush`; a computed value that isn't announced never
  updates on screen.
- **ObservableCollection** — reports items added, removed, and *moved*, so
  sorting is `Move()` calls and the list re-renders itself.
- **Per-item change subscription** — the summary re-derives on any row change,
  because a collection reports structural edits, not in-place mutations.
- **FuncDataTemplate** — one code-defined row template; each control binds to a
  property of its `ServiceVM`, including `IBrush` for the status colour.

### Gotcha worth knowing
A bare `AppBuilder` gives you **no theme**, and templated controls
(`ItemsControl`, `ProgressBar`, `Button`) have no `ControlTemplate` without one:
they lay out at the correct size and paint nothing at all. `Styles.Add(new
FluentTheme())` in `App.Initialize()` is what makes them appear. (The first C#
demo escapes this only because it draws primitives on a Canvas.)

## Dependencies
- .NET SDK 10 (`sudo apt install dotnet-sdk-10.0`); NuGet restores Avalonia.

## Run
Unified Base runs this automatically (`dotnet run --project Demo.csproj`).

Manual equivalent:

```
dotnet run
```

## Files
- `Demo.csproj` — Avalonia + Fluent theme package references
- `Program.cs` — view models, templates, and window, all code-only (no `.axaml`)
