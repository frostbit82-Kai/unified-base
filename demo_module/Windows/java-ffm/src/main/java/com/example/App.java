package com.example;

import java.awt.BasicStroke;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.Font;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.Shape;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.awt.geom.RoundRectangle2D;
import java.util.ArrayList;
import java.util.List;
import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JCheckBox;
import javax.swing.JComponent;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JSplitPane;
import javax.swing.JTable;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.table.AbstractTableModel;

/**
 * Java — Unified Base Windows demo #2: Win32 straight from Java.
 *
 * A live map of every window on the desktop, drawn to scale and in z-order,
 * plus memory, power, uptime and the cursor — all from user32, kernel32 and
 * dwmapi through the FFM API (see Win32.java). Hover a window for details,
 * click it (map or table) and Flash it on the taskbar.
 *
 * `java -jar target/ub-java-ffm.jar --selftest` makes every call once and
 * checks the answers.
 */
public class App {
    static final Color BG = new Color(0x0D, 0x11, 0x17);
    static final Color PANEL = new Color(0x16, 0x1B, 0x22);
    static final Color LINE = new Color(0x30, 0x36, 0x3D);
    static final Color FG = new Color(0xE6, 0xED, 0xF3);
    static final Color MUTED = new Color(0x7D, 0x85, 0x90);
    static final Color HI = new Color(0x9F, 0xD8, 0xEF);
    static final Color GREEN = new Color(0x2E, 0xA0, 0x43);

    public static void main(String[] args) {
        if (!System.getProperty("os.name").startsWith("Windows")) {
            System.err.println("This demo calls the Win32 API (user32, kernel32) — run it on Windows.");
            System.exit(1);
        }
        if (List.of(args).contains("--selftest")) {
            selfTest();
            return;
        }
        SwingUtilities.invokeLater(App::createAndShow);
    }

    private static void createAndShow() {
        JFrame frame = new JFrame("Java · Win32 through FFM — Unified Base Windows demo");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setContentPane(new MainPanel());
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    // -------------------------------------------------------------------------
    static final class WindowModel extends AbstractTableModel {
        private static final String[] COLS = {"Window", "Process", "PID", "Size"};
        List<Win32.Win> rows = new ArrayList<>();

        @Override public int getRowCount() { return rows.size(); }
        @Override public int getColumnCount() { return COLS.length; }
        @Override public String getColumnName(int c) { return COLS[c]; }

        @Override
        public Object getValueAt(int r, int c) {
            Win32.Win w = rows.get(r);
            return switch (c) {
                case 0 -> w.title();
                case 1 -> w.exe();
                case 2 -> w.pid();
                default -> w.w() + "×" + w.h();
            };
        }
    }

    /** The desktop to scale: the virtual screen, each window back to front. */
    static final class MapPanel extends JComponent {
        List<Win32.Win> wins = List.of();
        long selected;
        int[] cursor = {0, 0};
        private final List<Shape> shapes = new ArrayList<>();
        private final List<Win32.Win> drawn = new ArrayList<>();
        java.util.function.LongConsumer onPick = h -> { };

        MapPanel() {
            setPreferredSize(new Dimension(520, 360));
            setToolTipText("");             // enables getToolTipText(MouseEvent)
            addMouseListener(new MouseAdapter() {
                @Override public void mouseClicked(MouseEvent e) {
                    Win32.Win w = hit(e.getX(), e.getY());
                    if (w != null) {
                        onPick.accept(w.hwnd());
                    }
                }
            });
        }

        /** Topmost window under a point: the last one drawn wins. */
        private Win32.Win hit(int x, int y) {
            for (int i = shapes.size() - 1; i >= 0; i--) {
                if (shapes.get(i).contains(x, y)) {
                    return drawn.get(i);
                }
            }
            return null;
        }

        @Override
        public String getToolTipText(MouseEvent e) {
            Win32.Win w = hit(e.getX(), e.getY());
            return w == null ? null : String.format("<html><b>%s</b><br>%s · pid %d · class %s<br>"
                    + "%d×%d at (%d, %d)</html>", esc(w.title()), w.exe(), w.pid(), esc(w.cls()),
                    w.w(), w.h(), w.x(), w.y());
        }

        private static String esc(String s) {
            return s.replace("&", "&amp;").replace("<", "&lt;");
        }

        @Override
        protected void paintComponent(Graphics g) {
            Graphics2D g2 = (Graphics2D) g.create();
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g2.setColor(BG);
            g2.fillRect(0, 0, getWidth(), getHeight());
            // SM_XVIRTUALSCREEN .. SM_CYVIRTUALSCREEN: every monitor's union.
            int vx = Win32.metric(76), vy = Win32.metric(77);
            int vw = Math.max(1, Win32.metric(78)), vh = Math.max(1, Win32.metric(79));
            double s = Math.min((getWidth() - 20.0) / vw, (getHeight() - 20.0) / vh);
            double ox = (getWidth() - vw * s) / 2, oy = (getHeight() - vh * s) / 2;
            g2.setColor(PANEL);
            g2.fill(new RoundRectangle2D.Double(ox, oy, vw * s, vh * s, 8, 8));
            g2.setColor(LINE);
            g2.draw(new RoundRectangle2D.Double(ox, oy, vw * s, vh * s, 8, 8));

            shapes.clear();
            drawn.clear();
            Font f = getFont().deriveFont(11f);
            g2.setFont(f);
            // EnumWindows lists front to back; paint back to front.
            for (int i = wins.size() - 1; i >= 0; i--) {
                Win32.Win w = wins.get(i);
                Shape r = new RoundRectangle2D.Double(ox + (w.x() - vx) * s, oy + (w.y() - vy) * s,
                        Math.max(4, w.w() * s), Math.max(4, w.h() * s), 6, 6);
                boolean sel = w.hwnd() == selected;
                g2.setColor(sel ? new Color(0x23, 0x86, 0x36, 220) : new Color(0x1F, 0x3A, 0x5F, 200));
                g2.fill(r);
                g2.setColor(sel ? GREEN.brighter() : new Color(0x58, 0xA6, 0xFF));
                g2.setStroke(new BasicStroke(sel ? 2.2f : 1.2f));
                g2.draw(r);
                var b = r.getBounds();
                if (b.width > 40 && b.height > 14) {
                    Graphics2D t = (Graphics2D) g2.create();
                    t.clip(r);
                    t.setColor(FG);
                    t.drawString(w.title(), b.x + 5, b.y + 13);
                    t.dispose();
                }
                shapes.add(r);
                drawn.add(w);
            }
            // The cursor, live.
            double cx = ox + (cursor[0] - vx) * s, cy = oy + (cursor[1] - vy) * s;
            g2.setColor(new Color(0xF0, 0x88, 0x3E));
            g2.fillOval((int) cx - 4, (int) cy - 4, 8, 8);
            g2.dispose();
        }
    }

    // -------------------------------------------------------------------------
    static final class MainPanel extends JPanel {
        private final WindowModel model = new WindowModel();
        private final JTable table = new JTable(model);
        private final MapPanel map = new MapPanel();
        private final JLabel stats = new JLabel(" ");
        private final JLabel count = new JLabel(" ");

        MainPanel() {
            setLayout(new BorderLayout(0, 10));
            setBorder(BorderFactory.createEmptyBorder(14, 16, 14, 16));
            setBackground(BG);
            setPreferredSize(new Dimension(1000, 640));

            add(header(), BorderLayout.NORTH);
            JSplitPane split = new JSplitPane(JSplitPane.HORIZONTAL_SPLIT, map, tableArea());
            split.setResizeWeight(0.55);
            split.setBorder(null);
            split.setBackground(BG);
            add(split, BorderLayout.CENTER);
            stats.setForeground(HI);
            stats.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
            add(stats, BorderLayout.SOUTH);

            map.onPick = this::select;
            table.getSelectionModel().addListSelectionListener(e -> {
                int r = table.getSelectedRow();
                if (r >= 0) {
                    map.selected = model.rows.get(r).hwnd();
                    map.repaint();
                }
            });
            refreshWindows();
            new Timer(1000, e -> refreshWindows()).start();
            new Timer(100, e -> {                   // the cursor moves; follow it
                map.cursor = Win32.cursor();
                map.repaint();
            }).start();
            new Timer(1000, e -> refreshStats()).start();
            refreshStats();
        }

        private JComponent header() {
            JPanel box = new JPanel();
            box.setLayout(new BoxLayout(box, BoxLayout.Y_AXIS));
            box.setBackground(BG);
            JLabel title = new JLabel("Java · Win32 through the FFM API");
            title.setForeground(FG);
            title.setFont(title.getFont().deriveFont(Font.BOLD, 18f));
            JLabel sub = new JLabel("java.lang.foreign: downcalls, an upcall for EnumWindows, "
                    + "structs as MemoryLayouts — no JNI, no JNA, no C");
            sub.setForeground(MUTED);
            JPanel bar = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 8));
            bar.setBackground(BG);
            JButton flash = new JButton("Flash on taskbar");
            flash.addActionListener(e -> {
                if (map.selected != 0) {
                    Win32.flash(map.selected);
                }
            });
            JButton beep = new JButton("MessageBeep");
            beep.addActionListener(e -> Win32.beep());
            count.setForeground(MUTED);
            bar.add(flash);
            bar.add(beep);
            bar.add(count);
            for (JComponent c : new JComponent[] {title, sub, bar}) {
                c.setAlignmentX(LEFT_ALIGNMENT);
                box.add(c);
            }
            return box;
        }

        private JComponent tableArea() {
            table.setBackground(BG);
            table.setForeground(FG);
            table.setGridColor(new Color(0x21, 0x26, 0x2D));
            table.setSelectionBackground(new Color(0x1F, 0x3A, 0x5F));
            table.setSelectionForeground(FG);
            table.setRowHeight(24);
            table.setFillsViewportHeight(true);
            table.getTableHeader().setBackground(PANEL);
            table.getTableHeader().setForeground(MUTED);
            table.getColumnModel().getColumn(0).setPreferredWidth(220);
            JScrollPane sp = new JScrollPane(table);
            sp.getViewport().setBackground(BG);
            sp.setBorder(BorderFactory.createLineBorder(LINE));
            return sp;
        }

        private void select(long hwnd) {
            for (int i = 0; i < model.rows.size(); i++) {
                if (model.rows.get(i).hwnd() == hwnd) {
                    table.setRowSelectionInterval(i, i);
                    table.scrollRectToVisible(table.getCellRect(i, 0, true));
                }
            }
        }

        /** Replace the rows but keep the selection on the same window. */
        private void refreshWindows() {
            long keep = map.selected;
            model.rows = Win32.windows();
            model.fireTableDataChanged();
            map.wins = model.rows;
            count.setText(model.rows.size() + " top-level windows · refreshed every second");
            if (keep != 0) {
                select(keep);
            }
            map.repaint();
        }

        private void refreshStats() {
            long[] m = Win32.memory();
            long up = Win32.uptimeMs() / 1000;
            stats.setText(String.format(
                    "%s · memory %d %% of %.1f GB · power %s · up %dh %02dm · %d dpi (%d %%) · %d monitor(s)",
                    Win32.computerName(), m[0], m[1] / 1073741824.0, Win32.power(),
                    up / 3600, up / 60 % 60, Win32.dpi(), Win32.dpi() * 100 / 96, Win32.metric(80)));
        }
    }

    // -------------------------------------------------------------------------
    private static void selfTest() {
        check(Win32.FLASHWINFO.byteSize() == 32, "FLASHWINFO is 32 bytes (padding before the HWND)");
        check(Win32.MEMORYSTATUSEX.byteSize() == 64, "MEMORYSTATUSEX is 64 bytes");
        List<Win32.Win> wins = Win32.windows();
        check(wins.stream().allMatch(w -> !w.title().isEmpty() && w.pid() > 0),
                wins.size() + " windows, all titled, all with a pid");
        long[] m = Win32.memory();
        check(m[1] > 256L << 20 && m[0] >= 0 && m[0] <= 100, "memory " + m[0] + " % of " + (m[1] >> 20) + " MB");
        check(Win32.uptimeMs() > 0, "uptime " + Win32.uptimeMs() / 1000 + " s");
        check(!Win32.computerName().isEmpty(), "computer " + Win32.computerName());
        check(Win32.dpi() >= 96, "system dpi " + Win32.dpi());
        int[] c = Win32.cursor();
        check(c.length == 2, "cursor at " + c[0] + "," + c[1]);
        System.out.println("selftest ok");
    }

    private static void check(boolean ok, String what) {
        System.out.println((ok ? "ok   " : "FAIL ") + what);
        if (!ok) {
            System.exit(1);
        }
    }
}
