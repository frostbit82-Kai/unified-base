using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Media;
using System.Windows.Threading;

namespace UnifiedBaseBinding;

// ---------------------------------------------------------------------------
// The Windows twin of demo_module/Linux/csharp-binding: the same live service
// dashboard, the same view models, rebuilt in WPF — the toolkit the binding
// model Avalonia follows came from. As there, nothing below assigns text or
// colour to a control after startup: the view models raise PropertyChanged
// and the bindings do the rest. Code-only, like the Avalonia demo, so the two
// read side by side.
// ---------------------------------------------------------------------------
internal static class Program
{
    [STAThread]
    public static void Main()
    {
        // WPF's own Fluent theme, new in .NET 9 — the counterpart of the
        // FluentTheme the Avalonia demo has to add. WPF never renders
        // controls blank without one (Aero2 is built in), but this is what
        // makes them look like Windows 11.
        var app = new Application { ThemeMode = ThemeMode.Dark };
        app.Run(new MainWindow());
    }
}

/// <summary>Raises PropertyChanged; every bindable type here derives from it.</summary>
public abstract class Observable : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        Raise(name);
    }

    protected void Raise([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

internal static class Palette
{
    public static SolidColorBrush Hex(string hex)
    {
        var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        b.Freeze();     // frozen brushes are shared across threads and cheap
        return b;
    }

    public static readonly SolidColorBrush Bg = Hex("#0d1117"), Card = Hex("#161b22"),
        Line = Hex("#21262d"), Fg = Hex("#e6edf3"), Dim = Hex("#7d8590"),
        Mono = Hex("#9fd8ef"), Green = Hex("#2ea043"), Ok = Hex("#7ee787"),
        Warn = Hex("#f0883e"), Bad = Hex("#ff7b72");
}

/// <summary>One row. Latency/load change on a timer; the UI follows.</summary>
public sealed class ServiceVM : Observable
{
    private double _latency;
    private double _load;
    private int _errors;

    public ServiceVM(string name, string region)
    {
        Name = name;
        Region = region;
    }

    public string Name { get; }
    public string Region { get; }

    public double Latency
    {
        get => _latency;
        // Anything derived from a changed property must be announced too, or
        // the bindings that read it will never update.
        set { Set(ref _latency, value); Raise(nameof(LatencyText)); Raise(nameof(Health)); Raise(nameof(HealthBrush)); }
    }

    public double Load
    {
        get => _load;
        set { Set(ref _load, value); Raise(nameof(LoadPercent)); Raise(nameof(Health)); Raise(nameof(HealthBrush)); }
    }

    public int Errors
    {
        get => _errors;
        set { Set(ref _errors, value); Raise(nameof(ErrorText)); }
    }

    public string LatencyText => $"{Latency,5:0} ms";
    public string ErrorText => Errors == 0 ? "—" : $"{Errors} err";
    public double LoadPercent => Load * 100;

    public string Health =>
        Latency > 220 || Load > 0.9 ? "critical" :
        Latency > 120 || Load > 0.7 ? "warn" : "ok";

    public Brush HealthBrush => Health switch
    {
        "critical" => Palette.Bad,
        "warn" => Palette.Warn,
        _ => Palette.Ok
    };
}

/// <summary>Top-level view model: the collection plus figures derived from it.</summary>
public sealed class DashboardVM : Observable
{
    private static readonly string[] Names =
    {
        "auth", "billing", "search", "media-cdn", "webhooks",
        "reports", "notifier", "gateway", "scheduler", "indexer"
    };
    private static readonly string[] Regions =
        { "us-east", "eu-west", "ap-south", "us-west" };

    private readonly Random _rnd = new(11);
    private bool _paused;
    private int _ticks;

    public DashboardVM()
    {
        for (var i = 0; i < Names.Length; i++)
        {
            var s = new ServiceVM(Names[i], Regions[i % Regions.Length])
            {
                Latency = 40 + _rnd.NextDouble() * 120,
                Load = 0.2 + _rnd.NextDouble() * 0.6,
            };
            // Re-derive the summary whenever any row changes: an
            // ObservableCollection reports items added or removed, never items
            // that mutated in place.
            s.PropertyChanged += (_, _) => RaiseSummary();
            Services.Add(s);
        }
    }

    public ObservableCollection<ServiceVM> Services { get; } = new();

    public bool Paused
    {
        get => _paused;
        set { Set(ref _paused, value); Raise(nameof(PauseLabel)); }
    }

    public string PauseLabel => Paused ? "Resume" : "Pause";
    public string Summary =>
        $"{Services.Count(s => s.Health == "ok")} ok · " +
        $"{Services.Count(s => s.Health == "warn")} warn · " +
        $"{Services.Count(s => s.Health == "critical")} critical";
    public string AvgLatency =>
        Services.Count == 0 ? "—" : $"{Services.Average(s => s.Latency):0} ms avg";
    public string TickText => $"tick {_ticks}";

    private void RaiseSummary()
    {
        Raise(nameof(Summary));
        Raise(nameof(AvgLatency));
    }

    /// <summary>One simulated sample per service — a random walk, clamped.</summary>
    public void Tick()
    {
        if (Paused) return;
        _ticks++;
        foreach (var s in Services)
        {
            s.Latency = Math.Clamp(s.Latency + (_rnd.NextDouble() - 0.48) * 26, 12, 400);
            s.Load = Math.Clamp(s.Load + (_rnd.NextDouble() - 0.5) * 0.08, 0.02, 1.0);
            if (_rnd.NextDouble() < 0.04) s.Errors += _rnd.Next(1, 4);
        }
        Raise(nameof(TickText));
    }

    /// <summary>Reorder in place. The ItemsControl re-renders from the
    /// collection's change notifications — no view code runs here.</summary>
    public void SortBy(string key)
    {
        var sorted = key switch
        {
            "latency" => Services.OrderByDescending(s => s.Latency).ToList(),
            "load" => Services.OrderByDescending(s => s.Load).ToList(),
            "errors" => Services.OrderByDescending(s => s.Errors).ToList(),
            _ => Services.OrderBy(s => s.Name).ToList()
        };
        for (var i = 0; i < sorted.Count; i++)
        {
            var from = Services.IndexOf(sorted[i]);
            if (from != i) Services.Move(from, i);
        }
    }
}

public class MainWindow : Window
{
    private readonly DashboardVM _vm = new();

    public MainWindow()
    {
        Title = "C# · data binding — Unified Base Windows demo";
        Width = 840;
        Height = 600;
        MinWidth = 520;
        MinHeight = 360;
        DataContext = _vm;
        Background = Palette.Bg;      // Fluent would otherwise ask for Mica,
                                      // which an embedded child can't have
        var dock = new DockPanel { Margin = new Thickness(18), LastChildFill = true };
        Dock(dock, Header());
        Dock(dock, Controls());
        dock.Children.Add(new ScrollViewer
        {
            Content = Rows(),
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto
        });
        Content = dock;

        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(600) };
        timer.Tick += (_, _) => _vm.Tick();
        timer.Start();
    }

    private static void Dock(DockPanel panel, UIElement child)
    {
        DockPanel.SetDock(child, System.Windows.Controls.Dock.Top);
        panel.Children.Add(child);
    }

    private static UIElement Header() => new StackPanel
    {
        Children =
        {
            new TextBlock
            {
                Text = "C# · WPF data binding",
                FontSize = 19,
                FontWeight = FontWeights.SemiBold,
                Foreground = Palette.Fg
            },
            new TextBlock
            {
                Text = "INotifyPropertyChanged · ObservableCollection · DataTemplates — Windows",
                Foreground = Palette.Dim,
                Margin = new Thickness(0, 2, 0, 12)
            }
        }
    };

    private UIElement Controls()
    {
        // A WrapPanel, not Avalonia's StackPanel: WPF's StackPanel has no
        // Spacing, and wrapping keeps every button reachable in a narrow pane.
        var bar = new WrapPanel { Margin = new Thickness(0, 0, 0, 12) };
        foreach (var key in new[] { "name", "latency", "load", "errors" })
        {
            var b = Button($"sort: {key}");
            b.Click += (_, _) => _vm.SortBy(key);
            bar.Children.Add(b);
        }

        var pause = Button("Pause");
        pause.SetBinding(ContentControl.ContentProperty, new Binding(nameof(DashboardVM.PauseLabel)));
        pause.Click += (_, _) => _vm.Paused = !_vm.Paused;
        bar.Children.Add(pause);

        foreach (var path in new[] { nameof(DashboardVM.Summary), nameof(DashboardVM.AvgLatency),
                                     nameof(DashboardVM.TickText) })
        {
            var t = new TextBlock
            {
                Foreground = Palette.Dim,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(12, 0, 0, 0)
            };
            t.SetBinding(TextBlock.TextProperty, new Binding(path));
            bar.Children.Add(t);
        }
        return bar;
    }

    /// <summary>The list. One template describes a row; it is never mutated
    /// from code — each element binds to a property of its ServiceVM.</summary>
    private UIElement Rows() => new ItemsControl
    {
        ItemsSource = _vm.Services,
        ItemTemplate = RowTemplate()
    };

    /// <summary>A code-only DataTemplate. WPF builds templates from
    /// FrameworkElementFactory (XAML compiles to the same thing); Avalonia
    /// takes a lambda instead.</summary>
    private static DataTemplate RowTemplate()
    {
        static FrameworkElementFactory Text(double width, string path, Brush fg)
        {
            var t = new FrameworkElementFactory(typeof(TextBlock));
            t.SetValue(WidthProperty, width);
            t.SetValue(TextBlock.ForegroundProperty, fg);
            t.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
            t.SetValue(MarginProperty, new Thickness(0, 0, 10, 0));
            t.SetBinding(TextBlock.TextProperty, new Binding(path));
            return t;
        }

        var row = new FrameworkElementFactory(typeof(StackPanel));
        row.SetValue(StackPanel.OrientationProperty, Orientation.Horizontal);

        var name = Text(110, nameof(ServiceVM.Name), Palette.Fg);
        name.SetValue(TextBlock.FontWeightProperty, FontWeights.SemiBold);
        row.AppendChild(name);
        row.AppendChild(Text(90, nameof(ServiceVM.Region), Palette.Dim));

        var health = Text(74, nameof(ServiceVM.Health), Palette.Fg);
        health.SetBinding(TextBlock.ForegroundProperty, new Binding(nameof(ServiceVM.HealthBrush)));
        row.AppendChild(health);

        var bar = new FrameworkElementFactory(typeof(ProgressBar));
        bar.SetValue(RangeBase.MaximumProperty, 100.0);
        bar.SetValue(WidthProperty, 240.0);
        bar.SetValue(HeightProperty, 10.0);
        bar.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
        bar.SetValue(MarginProperty, new Thickness(0, 0, 10, 0));
        bar.SetValue(ForegroundProperty, Palette.Green);
        bar.SetValue(BackgroundProperty, Palette.Line);
        // RangeBase.Value binds TwoWay by default, and a TwoWay binding to a
        // get-only property throws as the row is built. Avalonia's doesn't.
        bar.SetBinding(RangeBase.ValueProperty,
                       new Binding(nameof(ServiceVM.LoadPercent)) { Mode = BindingMode.OneWay });
        row.AppendChild(bar);

        var latency = Text(80, nameof(ServiceVM.LatencyText), Palette.Mono);
        latency.SetValue(TextBlock.TextAlignmentProperty, TextAlignment.Right);
        latency.SetValue(TextBlock.FontFamilyProperty, new FontFamily("Cascadia Mono, Consolas"));
        row.AppendChild(latency);

        var errors = Text(64, nameof(ServiceVM.ErrorText), Palette.Dim);
        errors.SetValue(TextBlock.TextAlignmentProperty, TextAlignment.Right);
        row.AppendChild(errors);

        var card = new FrameworkElementFactory(typeof(Border));
        card.SetValue(Border.BackgroundProperty, Palette.Card);
        card.SetValue(Border.BorderBrushProperty, Palette.Line);
        card.SetValue(Border.BorderThicknessProperty, new Thickness(1));
        card.SetValue(Border.CornerRadiusProperty, new CornerRadius(8));
        card.SetValue(Border.PaddingProperty, new Thickness(12, 9, 12, 9));
        card.SetValue(MarginProperty, new Thickness(0, 0, 0, 6));
        card.AppendChild(row);
        return new DataTemplate(typeof(ServiceVM)) { VisualTree = card };
    }

    private static Button Button(string text) => new()
    {
        Content = text,
        Padding = new Thickness(12, 6, 12, 6),
        Margin = new Thickness(0, 0, 8, 6)
    };
}
