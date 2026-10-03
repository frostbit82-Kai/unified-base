using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Controls.Shapes;
using Avalonia.Media;
using Avalonia.Threading;

namespace UnifiedBaseDemo;

// ---------------------------------------------------------------------------
// Entry point: build the Avalonia app and run the classic desktop lifetime.
// ---------------------------------------------------------------------------
internal static class Program
{
    [STAThread]
    public static void Main(string[] args) =>
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
                  .UsePlatformDetect()
                  .LogToTrace();
}

// ---------------------------------------------------------------------------
// Application: wires up the single main window.
// ---------------------------------------------------------------------------
public class App : Application
{
    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            desktop.MainWindow = new MainWindow();

        base.OnFrameworkInitializationCompleted();
    }
}

// ---------------------------------------------------------------------------
// MainWindow: a code-defined 800x600 window with a Canvas hosting a bouncing,
// hue-shifting ellipse animated by a ~60fps DispatcherTimer.
// ---------------------------------------------------------------------------
public class MainWindow : Window
{
    private const double W = 800;
    private const double H = 600;
    private const double R = 46;                 // ball radius

    private readonly Canvas _canvas = new() { Width = W, Height = H };
    private readonly Ellipse _ball = new() { Width = R * 2, Height = R * 2 };
    private readonly TextBlock _info = new();

    private double _x = 120, _y = 120;
    private double _vx = 4.1, _vy = 3.3;
    private double _hue;
    private int _bounces;

    // fps tracking
    private int _frames;
    private double _fps;
    private DateTime _fpsClock = DateTime.Now;

    public MainWindow()
    {
        Title = "C# (Avalonia) — Unified Base demo";
        Width = W;
        Height = H;
        // Resizable so a host (e.g. Unified Base embedding this window in a tab)
        // can shrink it; the Viewbox below scales the fixed 800x600 scene to fit
        // instead of clipping the sides.
        CanResize = true;
        Background = new LinearGradientBrush
        {
            StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
            EndPoint = new RelativePoint(1, 1, RelativeUnit.Relative),
            GradientStops =
            {
                new GradientStop(Color.Parse("#0f2027"), 0.0),
                new GradientStop(Color.Parse("#203a43"), 0.5),
                new GradientStop(Color.Parse("#2c5364"), 1.0),
            }
        };

        _ball.Effect = new DropShadowEffect
        {
            Color = Colors.Black,
            OffsetX = 0,
            OffsetY = 6,
            BlurRadius = 18,
            Opacity = 0.55
        };

        var title = new TextBlock
        {
            Text = "C# · Avalonia — bouncing ellipse",
            Foreground = new SolidColorBrush(Color.Parse("#e8f6ff")),
            FontSize = 22,
            FontWeight = FontWeight.SemiBold
        };
        Canvas.SetLeft(title, 24);
        Canvas.SetTop(title, 20);

        _info.Foreground = new SolidColorBrush(Color.Parse("#9fd8ef"));
        _info.FontSize = 14;
        _info.FontFamily = new FontFamily("monospace");
        Canvas.SetLeft(_info, 24);
        Canvas.SetTop(_info, 54);

        _canvas.Children.Add(title);
        _canvas.Children.Add(_info);
        _canvas.Children.Add(_ball);
        // Scale the whole scene uniformly to whatever size the window is; the
        // bounce math keeps working in the fixed 800x600 coordinate space.
        Content = new Viewbox { Child = _canvas, Stretch = Stretch.Uniform };

        PlaceBall(_x, _y);
        Recolor();

        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(16) };
        timer.Tick += Tick;
        timer.Start();
    }

    private void Tick(object? sender, EventArgs e)
    {
        _x += _vx;
        _y += _vy;

        bool bounced = false;
        if (_x <= 0)              { _x = 0;              _vx = -_vx; bounced = true; }
        if (_x >= W - R * 2)      { _x = W - R * 2;      _vx = -_vx; bounced = true; }
        if (_y <= 0)              { _y = 0;              _vy = -_vy; bounced = true; }
        if (_y >= H - R * 2)      { _y = H - R * 2;      _vy = -_vy; bounced = true; }
        if (bounced) _bounces++;

        _hue = (_hue + 0.9) % 360;

        PlaceBall(_x, _y);
        Recolor();

        // fps
        _frames++;
        var now = DateTime.Now;
        var elapsed = (now - _fpsClock).TotalSeconds;
        if (elapsed >= 0.5)
        {
            _fps = _frames / elapsed;
            _frames = 0;
            _fpsClock = now;
        }

        _info.Text = $"bounces: {_bounces,-4}  fps: {_fps,5:0.0}  time: {now:HH:mm:ss}";
    }

    private void PlaceBall(double x, double y)
    {
        Canvas.SetLeft(_ball, x);
        Canvas.SetTop(_ball, y);
    }

    private void Recolor()
    {
        var core = FromHsv(_hue, 0.75, 1.0);
        var edge = FromHsv((_hue + 40) % 360, 0.85, 0.55);
        _ball.Fill = new RadialGradientBrush
        {
            GradientOrigin = new RelativePoint(0.35, 0.30, RelativeUnit.Relative),
            Center = new RelativePoint(0.5, 0.5, RelativeUnit.Relative),
            RadiusX = new RelativeScalar(0.6, RelativeUnit.Relative),
            RadiusY = new RelativeScalar(0.6, RelativeUnit.Relative),
            GradientStops =
            {
                new GradientStop(Colors.White, 0.0),
                new GradientStop(core, 0.35),
                new GradientStop(edge, 1.0),
            }
        };
    }

    // Simple HSV -> Color (h in [0,360), s/v in [0,1]).
    private static Color FromHsv(double h, double s, double v)
    {
        double c = v * s;
        double x = c * (1 - Math.Abs((h / 60.0) % 2 - 1));
        double m = v - c;
        double r = 0, g = 0, b = 0;

        switch ((int)(h / 60) % 6)
        {
            case 0: r = c; g = x; break;
            case 1: r = x; g = c; break;
            case 2: g = c; b = x; break;
            case 3: g = x; b = c; break;
            case 4: r = x; b = c; break;
            default: r = c; b = x; break;
        }

        return Color.FromRgb(
            (byte)((r + m) * 255),
            (byte)((g + m) * 255),
            (byte)((b + m) * 255));
    }
}
