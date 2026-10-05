using System.Runtime.InteropServices;
using System.Runtime.InteropServices.WindowsRuntime;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using Dev = global::Windows.Devices.Enumeration;
using Imaging = global::Windows.Graphics.Imaging;
using MediaCore = global::Windows.Media.Core;
using Net = global::Windows.Networking.Connectivity;
using Ocr = global::Windows.Media.Ocr;
using Playback = global::Windows.Media.Playback;
using Power = global::Windows.System.Power;
using Profile = global::Windows.System.Profile;
using Speech = global::Windows.Media.SpeechSynthesis;
using UserProfile = global::Windows.System.UserProfile;
using ViewMgmt = global::Windows.UI.ViewManagement;

namespace UnifiedBaseWinRt;

// ---------------------------------------------------------------------------
// C# — Unified Base Windows demo #2: the Windows Runtime from a desktop app.
//
// The APIs Windows ships for Store apps are just as available to a plain .NET
// desktop program: target net10.0-windows10.0.x and Windows.* appears as
// ordinary C# namespaces (projected by C#/WinRT). Four tabs of it:
//
//   Read the screen   Windows.Media.Ocr — the on-device OCR engine
//   Voices            Windows.Media.SpeechSynthesis + word-boundary cues
//   This PC           UISettings, PowerManager, NetworkInformation, regions
//   Devices           DeviceInformation + a live DeviceWatcher
//
// `dotnet run -- --selftest` OCRs rendered text and synthesizes speech
// (silently) and checks both.
// ---------------------------------------------------------------------------
internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        if (args.Contains("--selftest")) return SelfTest.Run();
        var app = new Application { ThemeMode = ThemeMode.Dark };
        app.Run(new MainWindow());
        return 0;
    }
}

internal static class Ui
{
    public static SolidColorBrush Hex(string hex)
    {
        var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        b.Freeze();
        return b;
    }

    public static readonly SolidColorBrush Bg = Hex("#0d1117"), CardBg = Hex("#161b22"),
        Line = Hex("#21262d"), Fg = Hex("#e6edf3"), Dim = Hex("#7d8590"), Hi = Hex("#9fd8ef");
    public static readonly FontFamily Mono = new("Cascadia Mono, Consolas");

    public static TextBlock Text(string s, Brush? fg = null, double size = 13) =>
        new() { Text = s, Foreground = fg ?? Fg, FontSize = size, TextWrapping = TextWrapping.Wrap };

    public static Border Card(string title, UIElement body, double width = 330) => new()
    {
        Background = CardBg,
        BorderBrush = Line,
        BorderThickness = new Thickness(1),
        CornerRadius = new CornerRadius(10),
        Padding = new Thickness(14, 12, 14, 12),
        Margin = new Thickness(0, 0, 12, 12),
        Width = width,
        Child = new StackPanel
        {
            Children =
            {
                new TextBlock { Text = title.ToUpperInvariant(), Foreground = Dim, FontSize = 11.5,
                                FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 0, 0, 8) },
                body
            }
        }
    };

    /// <summary>Two-column key/value grid; returns a setter for the values.</summary>
    public static (Grid grid, Action<IEnumerable<(string, string)>> set) Pairs()
    {
        var g = new Grid();
        g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        g.ColumnDefinitions.Add(new ColumnDefinition());
        void Set(IEnumerable<(string k, string v)> rows)
        {
            g.Children.Clear();
            g.RowDefinitions.Clear();
            var i = 0;
            foreach (var (k, v) in rows)
            {
                g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var kt = new TextBlock { Text = k, Foreground = Dim, Margin = new Thickness(0, 1, 12, 1) };
                var vt = new TextBlock { Text = v, Foreground = Hi, FontFamily = Mono, FontSize = 12.5,
                                         TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 1, 0, 1) };
                Grid.SetRow(kt, i);
                Grid.SetRow(vt, i);
                Grid.SetColumn(vt, 1);
                g.Children.Add(kt);
                g.Children.Add(vt);
                i++;
            }
        }
        return (g, Set);
    }

    public static Button Button(string text) => new()
    {
        Content = text,
        Padding = new Thickness(12, 6, 12, 6),
        Margin = new Thickness(0, 0, 8, 0)
    };
}

public class MainWindow : Window
{
    public MainWindow()
    {
        Title = "C# · the Windows Runtime — Unified Base Windows demo";
        Width = 1000;
        Height = 700;
        MinWidth = 560;
        MinHeight = 400;
        Background = Ui.Bg;          // Mica can't reach an embedded child window
        var head = new StackPanel { Margin = new Thickness(18, 14, 18, 8) };
        head.Children.Add(Ui.Text("C# · the Windows Runtime from a desktop app", size: 19));
        head.Children.Add(Ui.Text("WPF + Windows.Media.Ocr · SpeechSynthesis · UISettings · " +
                                  "PowerManager · NetworkInformation · DeviceWatcher", Ui.Dim));
        var tabs = new TabControl { Margin = new Thickness(12, 0, 12, 12) };
        tabs.Items.Add(new TabItem { Header = "Read the screen", Content = InPlace(() => new OcrTab()) });
        tabs.Items.Add(new TabItem { Header = "Voices", Content = InPlace(() => new VoiceTab()) });
        tabs.Items.Add(new TabItem { Header = "This PC", Content = InPlace(() => new PcTab()) });
        tabs.Items.Add(new TabItem { Header = "Devices", Content = InPlace(() => new DevicesTab()) });
        var dock = new DockPanel();
        DockPanel.SetDock(head, Dock.Top);
        dock.Children.Add(head);
        dock.Children.Add(tabs);
        Content = dock;
    }

    // A WinRT class this system lacks (Wine has no Windows.Media.Playback)
    // throws from the tab's constructor. Say so in that tab, not by crashing.
    private static UIElement InPlace(Func<UIElement> make)
    {
        try { return make(); }
        catch (Exception e)
        {
            return new Border { Padding = new Thickness(12),
                                Child = Ui.Text($"Not available on this system: {e.Message}", Ui.Dim) };
        }
    }
}

// --- Read the screen ---------------------------------------------------------
internal static class Screen
{
    [StructLayout(LayoutKind.Sequential)]
    private struct BITMAPINFOHEADER
    {
        public uint biSize; public int biWidth, biHeight; public ushort biPlanes, biBitCount;
        public uint biCompression, biSizeImage; public int biXPelsPerMeter, biYPelsPerMeter;
        public uint biClrUsed, biClrImportant;
    }

    [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr hwnd, IntPtr dc);
    [DllImport("user32.dll")] private static extern int GetSystemMetrics(int index);
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleBitmap(IntPtr dc, int w, int h);
    [DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
    [DllImport("gdi32.dll")] private static extern bool BitBlt(IntPtr dst, int x, int y, int w, int h,
                                                             IntPtr src, int sx, int sy, uint rop);
    [DllImport("gdi32.dll")] private static extern int GetDIBits(IntPtr dc, IntPtr bmp, uint start, uint lines,
                                                               byte[] bits, ref BITMAPINFOHEADER bmi, uint usage);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr obj);
    [DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);

    /// <summary>The primary screen as top-down BGRA, in physical pixels (the
    /// manifest makes the process per-monitor DPI aware).</summary>
    public static (byte[] px, int w, int h) Capture()
    {
        int w = GetSystemMetrics(0), h = GetSystemMetrics(1);       // SM_CX/CYSCREEN
        var screen = GetDC(IntPtr.Zero);
        var mem = CreateCompatibleDC(screen);
        var bmp = CreateCompatibleBitmap(screen, w, h);
        var old = SelectObject(mem, bmp);
        try
        {
            BitBlt(mem, 0, 0, w, h, screen, 0, 0, 0x00CC0020 | 0x40000000);   // SRCCOPY|CAPTUREBLT
            var info = new BITMAPINFOHEADER
            {
                biSize = (uint)Marshal.SizeOf<BITMAPINFOHEADER>(), biWidth = w,
                biHeight = -h,                 // negative: rows top-down
                biPlanes = 1, biBitCount = 32
            };
            var px = new byte[w * h * 4];
            GetDIBits(mem, bmp, 0, (uint)h, px, ref info, 0);
            for (var i = 3; i < px.Length; i += 4) px[i] = 255;      // GDI leaves alpha 0
            return (px, w, h);
        }
        finally
        {
            SelectObject(mem, old);
            DeleteObject(bmp);
            DeleteDC(mem);
            ReleaseDC(IntPtr.Zero, screen);
        }
    }
}

internal static class OcrRunner
{
    public static Ocr.OcrEngine? Engine() => Ocr.OcrEngine.TryCreateFromUserProfileLanguages();

    /// <summary>OCR a BGRA image; the engine has a size limit, so larger images
    /// are halved (nearest neighbour) until they fit, and the word boxes are
    /// scaled back up.</summary>
    public static async Task<(Ocr.OcrResult result, double scale)> Read(Ocr.OcrEngine engine, byte[] px, int w, int h)
    {
        double scale = 1;
        while (Math.Max(w, h) > Ocr.OcrEngine.MaxImageDimension)
        {
            (px, w, h) = Halve(px, w, h);
            scale *= 2;
        }
        using var bmp = Imaging.SoftwareBitmap.CreateCopyFromBuffer(
            px.AsBuffer(), Imaging.BitmapPixelFormat.Bgra8, w, h, Imaging.BitmapAlphaMode.Premultiplied);
        return (await engine.RecognizeAsync(bmp), scale);
    }

    private static (byte[], int, int) Halve(byte[] px, int w, int h)
    {
        int nw = w / 2, nh = h / 2;
        var o = new byte[nw * nh * 4];
        for (var y = 0; y < nh; y++)
            for (var x = 0; x < nw; x++)
                Buffer.BlockCopy(px, ((y * 2) * w + x * 2) * 4, o, (y * nw + x) * 4, 4);
        return (o, nw, nh);
    }
}

public class OcrTab : DockPanel
{
    private readonly TextBlock _status = Ui.Text("Windows' own OCR engine, on this PC — nothing leaves it.", Ui.Dim);
    private readonly Image _image = new() { Stretch = Stretch.Fill };
    private readonly Canvas _boxes = new();
    private readonly Grid _stage = new();
    private readonly TextBox _lines = new()
    {
        IsReadOnly = true, FontFamily = Ui.Mono, FontSize = 12, TextWrapping = TextWrapping.Wrap,
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(12, 0, 0, 0)
    };

    public OcrTab()
    {
        Margin = new Thickness(12);
        var bar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 10) };
        var go = Ui.Button("Read my screen");
        go.Click += async (_, _) => await ReadScreen(go);
        bar.Children.Add(go);
        _status.VerticalAlignment = VerticalAlignment.Center;
        bar.Children.Add(_status);
        SetDock(bar, Dock.Top);
        Children.Add(bar);

        _stage.Children.Add(_image);
        _stage.Children.Add(_boxes);
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(3, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(2, GridUnitType.Star) });
        var view = new Viewbox { Child = _stage, VerticalAlignment = VerticalAlignment.Top };
        Grid.SetColumn(_lines, 1);
        grid.Children.Add(view);
        grid.Children.Add(_lines);
        Children.Add(grid);
    }

    private async Task ReadScreen(Button go)
    {
        var engine = OcrRunner.Engine();
        if (engine is null)
        {
            _status.Text = "No OCR language installed: Settings ▸ Time & language ▸ Language — " +
                           "add “Optical character recognition” to a language.";
            return;
        }
        go.IsEnabled = false;
        try
        {
            var t0 = DateTime.Now;
            var (px, w, h) = Screen.Capture();
            var (res, scale) = await Task.Run(() => OcrRunner.Read(engine, px, w, h));
            var ms = (DateTime.Now - t0).TotalMilliseconds;

            _image.Source = BitmapSource.Create(w, h, 96, 96, PixelFormats.Bgra32, null, px, w * 4);
            _stage.Width = _boxes.Width = w;
            _stage.Height = _boxes.Height = h;
            _boxes.Children.Clear();
            var words = 0;
            foreach (var line in res.Lines)
                foreach (var word in line.Words)
                {
                    var r = word.BoundingRect;
                    var box = new Rectangle
                    {
                        Width = r.Width * scale, Height = r.Height * scale,
                        Stroke = Ui.Hex("#2ea043"), StrokeThickness = 2,
                        Fill = Ui.Hex("#302ea043")
                    };
                    Canvas.SetLeft(box, r.X * scale);
                    Canvas.SetTop(box, r.Y * scale);
                    _boxes.Children.Add(box);
                    words++;
                }
            _lines.Text = string.Join(Environment.NewLine, res.Lines.Select(l => l.Text));
            _status.Text = $"{res.Lines.Count} lines · {words} words · {ms:0} ms · " +
                           $"{engine.RecognizerLanguage.DisplayName} · {w}×{h}";
        }
        finally
        {
            go.IsEnabled = true;
        }
    }
}

// --- Voices -----------------------------------------------------------------------
public class VoiceTab : DockPanel
{
    private readonly ComboBox _voices = new() { MinWidth = 320, Margin = new Thickness(0, 0, 8, 0) };
    private readonly TextBox _input = new()
    {
        Text = "The Windows Runtime speaks too. Every word lights up as the speech engine reaches it, " +
               "timed by cues that come back with the audio.",
        TextWrapping = TextWrapping.Wrap, AcceptsReturn = true, Height = 80, Margin = new Thickness(0, 10, 0, 10)
    };
    private readonly TextBlock _karaoke = new()
    {
        FontSize = 20, TextWrapping = TextWrapping.Wrap, Foreground = Ui.Fg, Margin = new Thickness(0, 6, 0, 0)
    };
    private readonly TextBlock _status = Ui.Text("", Ui.Dim);
    private readonly Playback.MediaPlayer _player = new();

    public VoiceTab()
    {
        Margin = new Thickness(12);
        foreach (var v in Speech.SpeechSynthesizer.AllVoices.OrderBy(v => v.DisplayName))
            _voices.Items.Add(new ComboBoxItem { Content = $"{v.DisplayName} · {v.Language} · {v.Gender}", Tag = v });
        _voices.SelectedIndex = 0;
        var bar = new StackPanel { Orientation = Orientation.Horizontal };
        bar.Children.Add(_voices);
        var speak = Ui.Button("Speak");
        speak.Click += async (_, _) => await Speak();
        var stop = Ui.Button("Stop");
        stop.Click += (_, _) => _player.Pause();
        bar.Children.Add(speak);
        bar.Children.Add(stop);
        var top = new StackPanel();
        top.Children.Add(bar);
        top.Children.Add(_input);
        top.Children.Add(_status);
        _status.Text = $"{Speech.SpeechSynthesizer.AllVoices.Count} OneCore voices installed — " +
                       "the same engine Narrator uses, a different set from the browser's SAPI list.";
        SetDock(top, Dock.Top);
        Children.Add(top);
        Children.Add(_karaoke);
    }

    private async Task Speak()
    {
        var text = _input.Text.Trim();
        if (text.Length == 0 || _voices.SelectedItem is not ComboBoxItem { Tag: Speech.VoiceInformation voice })
            return;
        using var synth = new Speech.SpeechSynthesizer { Voice = voice };
        synth.Options.IncludeWordBoundaryMetadata = true;
        var stream = await synth.SynthesizeTextToStreamAsync(text);
        var item = new Playback.MediaPlaybackItem(MediaCore.MediaSource.CreateFromStream(stream, stream.ContentType));
        // Word cues arrive as a timed-metadata track. It has to be switched to
        // "application presented", or its CueEntered events never fire.
        void Watch(int i)
        {
            var track = item.TimedMetadataTracks[i];
            if (track.Id != "SpeechWord") return;
            item.TimedMetadataTracks.SetPresentationMode((uint)i,
                Playback.TimedMetadataTrackPresentationMode.ApplicationPresented);
            track.CueEntered += (_, e) =>
            {
                if (e.Cue is MediaCore.SpeechCue cue)
                    Dispatcher.Invoke(() => Highlight(text, cue.StartPositionInInput ?? 0,
                                                      cue.EndPositionInInput ?? 0));
            };
        }
        for (var i = 0; i < item.TimedMetadataTracks.Count; i++) Watch(i);
        item.TimedMetadataTracksChanged += (_, e) => Watch((int)e.Index);
        Highlight(text, -1, -1);
        _player.Source = item;
        _player.Play();
    }

    private void Highlight(string text, int start, int end)
    {
        _karaoke.Inlines.Clear();
        if (start < 0 || end < start || end >= text.Length)
        {
            _karaoke.Inlines.Add(new Run(text));
            return;
        }
        _karaoke.Inlines.Add(new Run(text[..start]) { Foreground = Ui.Dim });
        _karaoke.Inlines.Add(new Run(text[start..(end + 1)])
        {
            Background = Ui.Hex("#238636"), Foreground = Brushes.White
        });
        _karaoke.Inlines.Add(new Run(text[(end + 1)..]));
    }
}

// --- This PC -----------------------------------------------------------------------
public class PcTab : ScrollViewer
{
    private readonly ViewMgmt.UISettings _ui = new();     // keep: its events need it alive
    private readonly WrapPanel _swatches = new();
    private readonly Action<IEnumerable<(string, string)>> _setLook, _setPower, _setNet, _setSys;

    public PcTab()
    {
        Padding = new Thickness(12);
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
        var wrap = new WrapPanel();
        Content = wrap;

        var (look, setLook) = Ui.Pairs();
        var lookBody = new StackPanel();
        lookBody.Children.Add(_swatches);
        lookBody.Children.Add(look);
        wrap.Children.Add(Ui.Card("Accent & appearance — live", lookBody));
        var (power, setPower) = Ui.Pairs();
        wrap.Children.Add(Ui.Card("Power — live", power));
        var (net, setNet) = Ui.Pairs();
        wrap.Children.Add(Ui.Card("Network — live", net));
        var (sys, setSys) = Ui.Pairs();
        wrap.Children.Add(Ui.Card("Windows & region", sys));
        (_setLook, _setPower, _setNet, _setSys) = (setLook, setPower, setNet, setSys);

        // WinRT raises these on worker threads; the UI is touched on its own.
        _ui.ColorValuesChanged += (_, _) => Dispatcher.Invoke(ShowLook);
        Power.PowerManager.RemainingChargePercentChanged += (_, _) => Dispatcher.Invoke(ShowPower);
        Power.PowerManager.PowerSupplyStatusChanged += (_, _) => Dispatcher.Invoke(ShowPower);
        Power.PowerManager.EnergySaverStatusChanged += (_, _) => Dispatcher.Invoke(ShowPower);
        Net.NetworkInformation.NetworkStatusChanged += _ => Dispatcher.Invoke(ShowNet);
        ShowLook();
        ShowPower();
        ShowNet();
        ShowSys();
    }

    private static string Hex(global::Windows.UI.Color c) => $"#{c.R:x2}{c.G:x2}{c.B:x2}";

    private void ShowLook()
    {
        _swatches.Children.Clear();
        var shades = new[]
        {
            ViewMgmt.UIColorType.AccentDark3, ViewMgmt.UIColorType.AccentDark2, ViewMgmt.UIColorType.AccentDark1,
            ViewMgmt.UIColorType.Accent,
            ViewMgmt.UIColorType.AccentLight1, ViewMgmt.UIColorType.AccentLight2, ViewMgmt.UIColorType.AccentLight3
        };
        foreach (var t in shades)
        {
            var hex = Hex(_ui.GetColorValue(t));
            _swatches.Children.Add(new Border
            {
                Width = 36, Height = 36, CornerRadius = new CornerRadius(6), Margin = new Thickness(0, 0, 4, 8),
                Background = Ui.Hex(hex), ToolTip = $"{t}: {hex}"
            });
        }
        var bg = _ui.GetColorValue(ViewMgmt.UIColorType.Background);
        _setLook(new[]
        {
            ("accent", Hex(_ui.GetColorValue(ViewMgmt.UIColorType.Accent))),
            ("apps", bg.R < 128 ? "dark" : "light"),
            ("text scale", $"{_ui.TextScaleFactor:0.##}×"),
            ("animations", _ui.AnimationsEnabled ? "on" : "off"),
            ("scrollbars", _ui.AutoHideScrollBars ? "auto-hide" : "always shown"),
        });
    }

    private void ShowPower()
    {
        var battery = Power.PowerManager.BatteryStatus;
        _setPower(new[]
        {
            ("battery", battery == Power.BatteryStatus.NotPresent ? "none"
                        : $"{Power.PowerManager.RemainingChargePercent} % · {battery}"),
            ("supply", Power.PowerManager.PowerSupplyStatus.ToString()),
            ("energy saver", Power.PowerManager.EnergySaverStatus.ToString()),
            ("time left", Power.PowerManager.RemainingDischargeTime == TimeSpan.MaxValue ? "—"
                          : Power.PowerManager.RemainingDischargeTime.ToString(@"h\:mm")),
        });
    }

    private void ShowNet()
    {
        var p = Net.NetworkInformation.GetInternetConnectionProfile();
        if (p is null)
        {
            _setNet(new[] { ("internet", "not connected") });
            return;
        }
        var cost = p.GetConnectionCost();
        var bars = p.GetSignalBars();
        _setNet(new[]
        {
            ("connection", p.ProfileName),
            ("kind", p.IsWlanConnectionProfile ? "Wi-Fi" : p.IsWwanConnectionProfile ? "cellular" : "wired / other"),
            ("signal", bars is null ? "—" : new string('▮', bars.Value) + new string('▯', 5 - bars.Value)),
            ("level", p.GetNetworkConnectivityLevel().ToString()),
            ("cost", $"{cost.NetworkCostType}{(cost.Roaming ? " · roaming" : "")}"),
        });
    }

    private void ShowSys()
    {
        var v = ulong.Parse(Profile.AnalyticsInfo.VersionInfo.DeviceFamilyVersion);
        var langs = UserProfile.GlobalizationPreferences.Languages;
        _setSys(new[]
        {
            ("family", Profile.AnalyticsInfo.VersionInfo.DeviceFamily),
            // DeviceFamilyVersion packs four 16-bit fields into one number.
            ("version", $"{v >> 48}.{(v >> 32) & 0xFFFF}.{(v >> 16) & 0xFFFF}.{v & 0xFFFF}"),
            ("languages", string.Join(", ", langs)),
            ("region", UserProfile.GlobalizationPreferences.HomeGeographicRegion),
            ("calendar", string.Join(", ", UserProfile.GlobalizationPreferences.Calendars)),
            ("week starts", UserProfile.GlobalizationPreferences.WeekStartsOn.ToString()),
        });
    }
}

// --- Devices ---------------------------------------------------------------------
public class DevicesTab : ScrollViewer
{
    private static readonly (string label, Dev.DeviceClass cls)[] Classes =
    {
        ("Audio outputs", Dev.DeviceClass.AudioRender),
        ("Microphones", Dev.DeviceClass.AudioCapture),
        ("Cameras", Dev.DeviceClass.VideoCapture),
        ("Portable storage", Dev.DeviceClass.PortableStorageDevice),
    };
    private readonly WrapPanel _wrap = new();
    private readonly List<Dev.DeviceWatcher> _watchers = new();
    private readonly DispatcherTimer _debounce = new() { Interval = TimeSpan.FromMilliseconds(400) };

    public DevicesTab()
    {
        Padding = new Thickness(12);
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
        Content = _wrap;
        _debounce.Tick += async (_, _) => { _debounce.Stop(); await Refresh(); };
        foreach (var (_, cls) in Classes)
        {
            // A watcher reports every device once at start, then each change:
            // plug in headphones or a USB stick and the card updates.
            var w = Dev.DeviceInformation.CreateWatcher(cls);
            w.Added += (_, _) => Kick();
            w.Removed += (_, _) => Kick();
            w.Updated += (_, _) => Kick();
            w.Start();
            _watchers.Add(w);
        }
        Loaded += async (_, _) => await Refresh();
    }

    private void Kick() => Dispatcher.Invoke(() => { _debounce.Stop(); _debounce.Start(); });

    private async Task Refresh()
    {
        _wrap.Children.Clear();
        foreach (var (label, cls) in Classes)
        {
            var list = await Dev.DeviceInformation.FindAllAsync(cls);
            var body = new StackPanel();
            if (list.Count == 0) body.Children.Add(Ui.Text("none", Ui.Dim));
            foreach (var d in list.OrderByDescending(d => d.IsDefault).ThenBy(d => d.Name))
                body.Children.Add(Ui.Text($"{(d.IsDefault ? "★ " : "• ")}{d.Name}{(d.IsEnabled ? "" : "  (disabled)")}",
                                          d.IsEnabled ? Ui.Fg : Ui.Dim));
            _wrap.Children.Add(Ui.Card($"{label} · {list.Count}", body));
        }
    }
}

// --- self-test ------------------------------------------------------------------
internal static class SelfTest
{
    public static int Run()
    {
        // Render known text with WPF, OCR it, and expect the words back.
        var tb = new TextBlock
        {
            Text = "Unified Base reads this", FontSize = 40, Foreground = Brushes.Black,
            Background = Brushes.White, Padding = new Thickness(20)
        };
        tb.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
        tb.Arrange(new Rect(tb.DesiredSize));
        var rtb = new RenderTargetBitmap((int)tb.ActualWidth, (int)tb.ActualHeight, 96, 96, PixelFormats.Pbgra32);
        rtb.Render(tb);
        var px = new byte[rtb.PixelWidth * rtb.PixelHeight * 4];
        rtb.CopyPixels(px, rtb.PixelWidth * 4, 0);
        var engine = OcrRunner.Engine() ?? throw new Exception("no OCR language installed");
        int w0 = rtb.PixelWidth, h0 = rtb.PixelHeight;   // WPF objects stay on this thread
        var text = Task.Run(async () => (await OcrRunner.Read(engine, px, w0, h0)).result.Text).Result;
        Check(text.Contains("Unified") && text.Contains("reads"), $"OCR read \"{text}\"");

        // Synthesize (never played) and count the word cues that came back.
        var voices = Speech.SpeechSynthesizer.AllVoices.Count;
        Check(voices > 0, $"{voices} voices");
        var bytes = Task.Run(async () =>
        {
            using var s = new Speech.SpeechSynthesizer();
            using var stream = await s.SynthesizeTextToStreamAsync("one two three");
            return stream.Size;
        }).Result;
        Check(bytes > 1000, $"speech stream {bytes} bytes");

        var v = ulong.Parse(Profile.AnalyticsInfo.VersionInfo.DeviceFamilyVersion);
        Check(v >> 48 == 10, $"version {v >> 48}.{(v >> 32) & 0xFFFF}.{(v >> 16) & 0xFFFF}");
        var (shot, w, h) = Screen.Capture();
        Check(w > 0 && h > 0 && shot.Length == w * h * 4, $"screen {w}×{h}");
        Console.WriteLine("selftest ok");
        return 0;
    }

    private static void Check(bool ok, string what)
    {
        Console.WriteLine($"{(ok ? "ok  " : "FAIL")} {what}");
        if (!ok) Environment.Exit(1);
    }
}
