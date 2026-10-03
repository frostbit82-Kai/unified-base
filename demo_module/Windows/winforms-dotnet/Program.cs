// WinForms demo for Unified Base: native Windows controls (DataGridView,
// MonthCalendar, TrackBar, ProgressBar) beside the same bouncing ball every
// demo shares. Windows-only by construction — on Linux it runs under Wine.
using System.Drawing.Drawing2D;

ApplicationConfiguration.Initialize();
Application.Run(new DemoForm());

sealed class DemoForm : Form
{
    static readonly Color Bg = Color.FromArgb(0x12, 0x15, 0x1C);
    static readonly Color Panel = Color.FromArgb(0x1A, 0x1F, 0x2B);
    static readonly Color[] Palette =
    {
        Color.FromArgb(0x4F, 0x8C, 0xFF), Color.FromArgb(0xFF, 0x6B, 0x6B),
        Color.FromArgb(0x3F, 0xB9, 0x50), Color.FromArgb(0xF2, 0xC1, 0x4E),
        Color.FromArgb(0xB3, 0x7D, 0xFF),
    };

    readonly ArenaPanel arena = new();
    readonly Label count = new() { AutoSize = true, ForeColor = Color.Gainsboro };
    readonly TrackBar speed = new() { Minimum = 2, Maximum = 40, Value = 12, TickStyle = TickStyle.None, Width = 160 };
    readonly ProgressBar load = new() { Width = 160, Style = ProgressBarStyle.Continuous };
    readonly System.Windows.Forms.Timer timer = new() { Interval = 16 };
    float bx = 80, by = 80, vx = 3.1f, vy = 2.4f;
    int color, bounces;

    public DemoForm()
    {
        Text = "WinForms Demo";
        ClientSize = new Size(820, 540);
        BackColor = Bg;
        ForeColor = Color.Gainsboro;
        Font = new Font("Segoe UI", 9.5f);

        var title = new Label
        {
            Text = "WinForms · Unified Base demo", AutoSize = true,
            Font = new Font("Segoe UI", 18f, FontStyle.Bold), ForeColor = Color.White,
        };
        var sub = new Label
        {
            Text = ".NET Windows Forms — Wine on Linux, native on Windows",
            AutoSize = true, ForeColor = Color.FromArgb(0x8A, 0x93, 0xA6),
        };
        var header = new FlowLayoutPanel
        {
            Dock = DockStyle.Top, Height = 74, FlowDirection = FlowDirection.TopDown,
            Padding = new Padding(12, 10, 0, 0), WrapContents = false,
        };
        header.Controls.AddRange(new Control[] { title, sub });

        arena.BackColor = Panel;
        arena.Dock = DockStyle.Fill;
        arena.Paint += PaintArena;

        var grid = new DataGridView
        {
            Dock = DockStyle.Fill, ReadOnly = true, RowHeadersVisible = false,
            AllowUserToAddRows = false, BackgroundColor = Panel,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
            // Cells default to white; the form's light ForeColor needs a dark cell.
            DefaultCellStyle = { BackColor = Panel, ForeColor = Color.Gainsboro },
        };
        grid.Columns.Add("lang", "Runtime");
        grid.Columns.Add("bridge", "On Linux");
        foreach (var (a, b) in new[] { ("Win32 C", "Wine"), ("WinForms", "Wine"),
                                       ("Python", "native"), ("Rust", "native") })
            grid.Rows.Add(a, b);
        var side = new TableLayoutPanel { Dock = DockStyle.Right, Width = 250, Padding = new Padding(8) };
        side.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        side.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        side.Controls.Add(new MonthCalendar { MaxSelectionCount = 1 }, 0, 0);
        side.Controls.Add(grid, 0, 1);

        var change = new Button { Text = "Change color", AutoSize = true, BackColor = Color.FromArgb(0x2C, 0x34, 0x45), FlatStyle = FlatStyle.Flat };
        change.Click += (_, _) => { color = (color + 1) % Palette.Length; arena.Invalidate(); };
        var bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 44, Padding = new Padding(10, 8, 0, 0) };
        bar.Controls.AddRange(new Control[] {
            change, count, new Label { Text = "Speed", AutoSize = true, Margin = new Padding(16, 6, 0, 0) },
            speed, new Label { Text = "Work", AutoSize = true, Margin = new Padding(8, 6, 0, 0) }, load });
        count.Margin = new Padding(12, 6, 0, 0);

        Controls.Add(arena);
        Controls.Add(side);
        Controls.Add(bar);
        Controls.Add(header);

        timer.Tick += (_, _) => Step();
        timer.Start();
        Step();
    }

    void Step()
    {
        float s = speed.Value / 10f, r = 22;
        bx += vx * s; by += vy * s;
        float w = arena.ClientSize.Width, h = arena.ClientSize.Height;
        if (bx - r < 0) { bx = r; vx = -vx; bounces++; }
        if (bx + r > w) { bx = w - r; vx = -vx; bounces++; }
        if (by - r < 0) { by = r; vy = -vy; bounces++; }
        if (by + r > h) { by = h - r; vy = -vy; bounces++; }
        count.Text = $"Bounces: {bounces}";
        load.Value = bounces % 101;
        arena.Invalidate();
    }

    void PaintArena(object? sender, PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var brush = new SolidBrush(Palette[color]);
        using var ring = new Pen(Color.White, 2);
        e.Graphics.FillEllipse(brush, bx - 22, by - 22, 44, 44);
        e.Graphics.DrawEllipse(ring, bx - 22, by - 22, 44, 44);
    }

    sealed class ArenaPanel : System.Windows.Forms.Panel
    {
        public ArenaPanel() => DoubleBuffered = true;
    }
}
