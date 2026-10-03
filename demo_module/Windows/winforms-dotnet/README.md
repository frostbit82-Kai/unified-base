# winforms-dotnet

A .NET Windows Forms app — Windows-only by construction (WinForms does not exist
on Linux): DataGridView, MonthCalendar, TrackBar and ProgressBar beside the
bouncing ball every demo shares.

- **Windows:** `dotnet run`, natively.
- **Linux:** the launcher publishes a self-contained single-file `win-x64` .exe
  with the Linux .NET SDK (`EnableWindowsTargeting`), then runs it through Wine.
  The first start downloads the Windows runtime packs from NuGet (~100 MB).
