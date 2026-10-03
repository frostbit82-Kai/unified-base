using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Controls.Primitives;
using Avalonia.Controls.Templates;
using Avalonia.Data;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Themes.Fluent;
using Avalonia.Threading;

namespace UnifiedBaseBinding;

// ---------------------------------------------------------------------------
// The first C# demo animates a shape. This one shows what Avalonia's engine is
// actually for: a view that never touches its data directly. Nothing below
// assigns text or colour to a control after startup — the view model raises
// PropertyChanged and the bindings do the rest.
// ---------------------------------------------------------------------------
internal static class Program
{
    [STAThread]
    public static void Main(string[] args) =>
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>().UsePlatformDetect().LogToTrace();
}

public class App : Application
{
    public override void Initialize()
    {
        // Templated controls (ItemsControl, ProgressBar, Button) render nothing
        // without a theme to supply their ControlTemplates — a bare AppBuilder
        // gives you correctly-sized but invisible controls.
        Styles.Add(new FluentTheme());
        RequestedThemeVariant = Avalonia.Styling.ThemeVariant.Dark;
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            desktop.MainWindow = new MainWindow();
        base.OnFrameworkInitializationCompleted();
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

    public IBrush HealthBrush => Health switch
    {
        "critical" => new SolidColorBrush(Color.Parse("#ff7b72")),
        "warn" => new SolidColorBrush(Color.Parse("#f0883e")),
        _ => new SolidColorBrush(Color.Parse("#7ee787"))
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
        Title = "C# · data binding — Unified Base demo";
        Width = 840;
        Height = 600;
        MinWidth = 520;
        MinHeight = 360;
        CanResize = true;                       // so a host pane can shrink it
        DataContext = _vm;
        Background = new SolidColorBrush(Color.Parse("#0d1117"));

        Content = new DockPanel { Margin = new Thickness(18) }
            .With(Header(), Dock.Top)
            .With(Controls(), Dock.Top)
            .With(new ScrollViewer { Content = Rows() }, Dock.Top, fill: true);

        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(600) };
        timer.Tick += (_, _) => _vm.Tick();
        timer.Start();
    }

    private Control Header()
    {
        var title = new TextBlock
        {
            Text = "C# · Avalonia data binding",
            FontSize = 19,
            FontWeight = FontWeight.SemiBold,
            Foreground = new SolidColorBrush(Color.Parse("#e6edf3"))
        };
        var sub = new TextBlock
        {
            Text = "INotifyPropertyChanged · ObservableCollection · DataTemplates",
            Foreground = new SolidColorBrush(Color.Parse("#7d8590")),
            Margin = new Thickness(0, 2, 0, 12)
        };
        return new StackPanel { Children = { title, sub } };
    }

    private Control Controls()
    {
        var bar = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
            Margin = new Thickness(0, 0, 0, 12)
        };

        foreach (var (label, key) in new[]
                 { ("name", "name"), ("latency", "latency"), ("load", "load"), ("errors", "errors") })
        {
            var b = Button($"sort: {label}");
            b.Click += (_, _) => _vm.SortBy(key);
            bar.Children.Add(b);
        }

        var pause = Button("Pause");
        pause.Bind(ContentControl.ContentProperty, new Binding(nameof(DashboardVM.PauseLabel)));
        pause.Click += (_, _) => _vm.Paused = !_vm.Paused;
        bar.Children.Add(pause);

        var summary = Muted();
        summary.Bind(TextBlock.TextProperty, new Binding(nameof(DashboardVM.Summary)));
        var avg = Muted();
        avg.Bind(TextBlock.TextProperty, new Binding(nameof(DashboardVM.AvgLatency)));
        var tick = Muted();
        tick.Bind(TextBlock.TextProperty, new Binding(nameof(DashboardVM.TickText)));
        bar.Children.Add(Spacer());
        bar.Children.Add(summary);
        bar.Children.Add(avg);
        bar.Children.Add(tick);
        return bar;
    }

    /// <summary>The list. One template describes a row; it is never mutated
    /// from code — each control binds to a property of its ServiceVM.</summary>
    private Control Rows() => new ItemsControl
    {
        ItemsSource = _vm.Services,
        ItemTemplate = new FuncDataTemplate<ServiceVM>((_, _) =>
        {
            var name = new TextBlock
            {
                Width = 110,
                FontWeight = FontWeight.SemiBold,
                Foreground = new SolidColorBrush(Color.Parse("#e6edf3")),
                VerticalAlignment = VerticalAlignment.Center
            };
            name.Bind(TextBlock.TextProperty, new Binding(nameof(ServiceVM.Name)));

            var region = Muted();
            region.Width = 90;
            region.Bind(TextBlock.TextProperty, new Binding(nameof(ServiceVM.Region)));

            var health = new TextBlock
            {
                Width = 74,
                VerticalAlignment = VerticalAlignment.Center
            };
            health.Bind(TextBlock.TextProperty, new Binding(nameof(ServiceVM.Health)));
            health.Bind(TextBlock.ForegroundProperty, new Binding(nameof(ServiceVM.HealthBrush)));

            var bar = new ProgressBar
            {
                Minimum = 0,
                Maximum = 100,
                Width = 240,
                Height = 10,
                VerticalAlignment = VerticalAlignment.Center,
                Foreground = new SolidColorBrush(Color.Parse("#2ea043")),
                Background = new SolidColorBrush(Color.Parse("#21262d"))
            };
            bar.Bind(RangeBase.ValueProperty, new Binding(nameof(ServiceVM.LoadPercent)));

            var latency = new TextBlock
            {
                Width = 80,
                TextAlignment = TextAlignment.Right,
                FontFamily = new FontFamily("monospace"),
                Foreground = new SolidColorBrush(Color.Parse("#9fd8ef")),
                VerticalAlignment = VerticalAlignment.Center
            };
            latency.Bind(TextBlock.TextProperty, new Binding(nameof(ServiceVM.LatencyText)));

            var errors = Muted();
            errors.Width = 64;
            errors.TextAlignment = TextAlignment.Right;
            errors.Bind(TextBlock.TextProperty, new Binding(nameof(ServiceVM.ErrorText)));

            return new Border
            {
                Background = new SolidColorBrush(Color.Parse("#161b22")),
                BorderBrush = new SolidColorBrush(Color.Parse("#21262d")),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(12, 9),
                Margin = new Thickness(0, 0, 0, 6),
                Child = new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 10,
                    Children = { name, region, health, bar, latency, errors }
                }
            };
        }, true)
    };

    // -- small helpers so the layout code above stays readable ---------------
    private static Button Button(string text) => new()
    {
        Content = text,
        Padding = new Thickness(12, 6),
        Background = new SolidColorBrush(Color.Parse("#21262d")),
        Foreground = new SolidColorBrush(Color.Parse("#e6edf3")),
        BorderBrush = new SolidColorBrush(Color.Parse("#30363d")),
        CornerRadius = new CornerRadius(8)
    };

    private static TextBlock Muted() => new()
    {
        Foreground = new SolidColorBrush(Color.Parse("#7d8590")),
        VerticalAlignment = VerticalAlignment.Center
    };

    private static Control Spacer() => new Panel { Width = 20 };
}

internal static class DockExtensions
{
    /// <summary>DockPanel.Children.Add + SetDock in one call.</summary>
    public static DockPanel With(this DockPanel panel, Control child, Dock dock,
                                 bool fill = false)
    {
        DockPanel.SetDock(child, dock);
        panel.Children.Add(child);
        if (fill) panel.LastChildFill = true;
        return panel;
    }
}
