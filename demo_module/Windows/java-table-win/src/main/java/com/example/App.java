package com.example;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.FlowLayout;
import java.awt.Font;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.event.KeyAdapter;
import java.awt.event.KeyEvent;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.JProgressBar;
import javax.swing.JScrollPane;
import javax.swing.JTable;
import javax.swing.JTextField;
import javax.swing.RowFilter;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;
import javax.swing.UIManager;
import javax.swing.JFrame;
import javax.swing.table.AbstractTableModel;
import javax.swing.table.DefaultTableCellRenderer;
import javax.swing.table.TableCellRenderer;
import javax.swing.table.TableRowSorter;

/**
 * Java — Unified Base Windows demo: the twin of demo_module/Linux/java-table.
 *
 * The same code, with one Windows change in main(): Swing's system look and
 * feel. On Windows that is WindowsLookAndFeel — the real Windows header,
 * scrollbars, progress bar and text field — where the Linux twin gets Metal.
 * The dark colours set explicitly below apply on both.
 *
 * Where the first Java demo is a custom-painted animation, this one is about
 * Swing as an application toolkit: a real TableModel, a background SwingWorker
 * that streams 20,000 rows in without freezing the UI, a RowSorter with live
 * text filtering, and custom cell renderers (status pills, in-cell usage bars).
 *
 * Pure JDK, no external dependencies.
 */
public class App {

    public static void main(String[] args) throws Exception {
        UIManager.setLookAndFeel(UIManager.getSystemLookAndFeelClassName());
        SwingUtilities.invokeLater(App::createAndShow);
    }

    private static void createAndShow() {
        JFrame frame = new JFrame("Java · data table — Unified Base Windows demo");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setContentPane(new TablePanel());
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    /** One row of the table. */
    record Node(String name, String region, String status, int cores,
                double usage, long requests) { }

    // ---------------------------------------------------------------------
    // Model: the table asks this for values; it never holds widgets itself.
    // ---------------------------------------------------------------------
    static final class NodeModel extends AbstractTableModel {
        private static final String[] COLS =
            {"Node", "Region", "Status", "Cores", "Usage", "Requests"};
        private final List<Node> rows = new ArrayList<>();

        void addAll(List<Node> batch) {
            int from = rows.size();
            rows.addAll(batch);
            // Tell the view exactly which rows appeared — a blanket
            // fireTableDataChanged() would reset selection and scroll position
            // on every batch.
            fireTableRowsInserted(from, rows.size() - 1);
        }

        Node row(int i) { return rows.get(i); }

        @Override public int getRowCount() { return rows.size(); }
        @Override public int getColumnCount() { return COLS.length; }
        @Override public String getColumnName(int c) { return COLS[c]; }

        @Override
        public Class<?> getColumnClass(int c) {
            // The sorter uses these to sort numerically instead of by text,
            // which is the whole reason "10" must not sort before "9".
            return switch (c) {
                case 3 -> Integer.class;
                case 4 -> Double.class;
                case 5 -> Long.class;
                default -> String.class;
            };
        }

        @Override
        public Object getValueAt(int r, int c) {
            Node n = rows.get(r);
            return switch (c) {
                case 0 -> n.name();
                case 1 -> n.region();
                case 2 -> n.status();
                case 3 -> n.cores();
                case 4 -> n.usage();
                case 5 -> n.requests();
                default -> "";
            };
        }
    }

    // ---------------------------------------------------------------------
    // Renderers
    // ---------------------------------------------------------------------
    /** Coloured pill for the status column. */
    static final class StatusRenderer extends DefaultTableCellRenderer {
        @Override
        public Component getTableCellRendererComponent(JTable t, Object v,
                boolean sel, boolean focus, int row, int col) {
            super.getTableCellRendererComponent(t, v, sel, focus, row, col);
            String s = String.valueOf(v);
            setHorizontalAlignment(CENTER);
            setForeground(switch (s) {
                case "healthy"  -> new Color(0x7E, 0xE7, 0x87);
                case "degraded" -> new Color(0xF0, 0x88, 0x3E);
                default         -> new Color(0xFF, 0x7B, 0x72);
            });
            return this;
        }
    }

    /** Draws the usage fraction as a bar with the percentage on top. */
    static final class UsageRenderer extends JComponent implements TableCellRenderer {
        private double value;
        private boolean selected;

        @Override
        public Component getTableCellRendererComponent(JTable t, Object v,
                boolean sel, boolean focus, int row, int col) {
            value = v instanceof Double d ? d : 0;
            selected = sel;
            return this;
        }

        @Override
        protected void paintComponent(Graphics g) {
            Graphics2D g2 = (Graphics2D) g.create();
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING,
                    RenderingHints.VALUE_ANTIALIAS_ON);
            int w = getWidth(), h = getHeight();
            g2.setColor(selected ? new Color(0x1F, 0x3A, 0x5F) : new Color(0x0D, 0x11, 0x17));
            g2.fillRect(0, 0, w, h);
            int barW = (int) Math.round((w - 60) * Math.min(1.0, value));
            g2.setColor(value > 0.85 ? new Color(0xFF, 0x7B, 0x72)
                      : value > 0.6 ? new Color(0xF0, 0x88, 0x3E)
                                    : new Color(0x2E, 0xA0, 0x43));
            g2.fillRoundRect(6, h / 2 - 5, Math.max(barW, 2), 10, 6, 6);
            g2.setColor(new Color(0xE6, 0xED, 0xF3));
            g2.setFont(getFont().deriveFont(11f));
            g2.drawString(String.format("%3.0f%%", value * 100), w - 44, h / 2 + 4);
            g2.dispose();
        }
    }

    // ---------------------------------------------------------------------
    // Panel: model + view + the worker that fills it
    // ---------------------------------------------------------------------
    static final class TablePanel extends JPanel {
        private static final int TOTAL = 20_000;
        private static final Color BG = new Color(0x0D, 0x11, 0x17);
        private static final Color PANEL = new Color(0x16, 0x1B, 0x22);
        private static final Color FG = new Color(0xE6, 0xED, 0xF3);
        private static final Color MUTED = new Color(0x7D, 0x85, 0x90);

        private final NodeModel model = new NodeModel();
        private final TableRowSorter<NodeModel> sorter = new TableRowSorter<>(model);
        private final JTable table = new JTable(model);
        private final JLabel status = new JLabel("loading…");
        private final JProgressBar progress = new JProgressBar(0, TOTAL);
        private final JTextField filter = new JTextField(22);

        TablePanel() {
            setLayout(new BorderLayout(0, 10));
            setBorder(BorderFactory.createEmptyBorder(14, 16, 14, 16));
            setBackground(BG);
            setPreferredSize(new Dimension(880, 600));

            add(header(), BorderLayout.NORTH);
            add(tableArea(), BorderLayout.CENTER);
            add(footer(), BorderLayout.SOUTH);

            load();
        }

        private JComponent header() {
            JPanel box = new JPanel();
            box.setLayout(new BoxLayout(box, BoxLayout.Y_AXIS));
            box.setBackground(BG);

            JLabel title = new JLabel("Java · Swing data table · Windows look and feel");
            title.setForeground(FG);
            title.setFont(title.getFont().deriveFont(Font.BOLD, 18f));
            title.setAlignmentX(LEFT_ALIGNMENT);

            JLabel sub = new JLabel("TableModel · SwingWorker · RowSorter · custom renderers");
            sub.setForeground(MUTED);
            sub.setAlignmentX(LEFT_ALIGNMENT);

            JPanel controls = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 8));
            controls.setBackground(BG);
            JLabel fl = new JLabel("filter:");
            fl.setForeground(MUTED);
            filter.setBackground(new Color(0x01, 0x04, 0x09));
            filter.setForeground(FG);
            filter.setCaretColor(FG);
            filter.setBorder(BorderFactory.createLineBorder(new Color(0x30, 0x36, 0x3D)));
            filter.setToolTipText("case-insensitive match on any column");
            filter.addKeyListener(new KeyAdapter() {
                @Override public void keyReleased(KeyEvent e) { applyFilter(); }
            });
            controls.add(fl);
            controls.add(filter);
            controls.add(Box.createHorizontalStrut(12));
            progress.setPreferredSize(new Dimension(220, 14));
            progress.setForeground(new Color(0x2E, 0xA0, 0x43));
            progress.setBackground(new Color(0x21, 0x26, 0x2D));
            progress.setBorderPainted(false);
            controls.add(progress);
            controls.setAlignmentX(LEFT_ALIGNMENT);

            box.add(title);
            box.add(sub);
            box.add(controls);
            return box;
        }

        private JComponent tableArea() {
            table.setRowSorter(sorter);
            table.setRowHeight(26);
            table.setBackground(BG);
            table.setForeground(FG);
            table.setGridColor(new Color(0x21, 0x26, 0x2D));
            table.setSelectionBackground(new Color(0x1F, 0x3A, 0x5F));
            table.setSelectionForeground(FG);
            table.setFillsViewportHeight(true);
            table.getTableHeader().setBackground(PANEL);
            table.getTableHeader().setForeground(MUTED);
            table.setAutoCreateRowSorter(false);

            table.getColumnModel().getColumn(2).setCellRenderer(new StatusRenderer());
            table.getColumnModel().getColumn(4).setCellRenderer(new UsageRenderer());
            DefaultTableCellRenderer right = new DefaultTableCellRenderer();
            right.setHorizontalAlignment(DefaultTableCellRenderer.RIGHT);
            table.getColumnModel().getColumn(3).setCellRenderer(right);
            // Grouped digits for readability. Only the DISPLAY changes — the
            // model still hands the sorter a Long, so ordering stays numeric.
            DefaultTableCellRenderer grouped = new DefaultTableCellRenderer() {
                @Override protected void setValue(Object v) {
                    setText(v instanceof Long n ? String.format("%,d", n)
                                                : String.valueOf(v));
                }
            };
            grouped.setHorizontalAlignment(DefaultTableCellRenderer.RIGHT);
            table.getColumnModel().getColumn(5).setCellRenderer(grouped);
            table.getColumnModel().getColumn(4).setPreferredWidth(160);

            table.getSelectionModel().addListSelectionListener(e -> updateStatus());

            JScrollPane sp = new JScrollPane(table);
            sp.getViewport().setBackground(BG);
            sp.setBorder(BorderFactory.createLineBorder(new Color(0x30, 0x36, 0x3D)));
            return sp;
        }

        private JComponent footer() {
            status.setForeground(new Color(0x9F, 0xD8, 0xEF));
            status.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
            return status;
        }

        private void applyFilter() {
            String q = filter.getText().trim();
            // (?i) = case-insensitive; Pattern.quote keeps a stray "(" from
            // throwing PatternSyntaxException mid-typing.
            sorter.setRowFilter(q.isEmpty() ? null
                    : RowFilter.regexFilter("(?i)" + java.util.regex.Pattern.quote(q)));
            updateStatus();
        }

        private void updateStatus() {
            int sel = table.getSelectedRow();
            String detail = "";
            if (sel >= 0) {
                Node n = model.row(table.convertRowIndexToModel(sel));
                detail = String.format("   selected: %s (%s, %s, %d cores, %.0f%%)",
                        n.name(), n.region(), n.status(), n.cores(), n.usage() * 100);
            }
            status.setText(String.format("%,d of %,d rows shown%s",
                    table.getRowCount(), model.getRowCount(), detail));
        }

        /**
         * Fill the model from a background thread. doInBackground() runs off the
         * EDT; publish/process hands batches back ON the EDT, which is the only
         * thread allowed to touch Swing state.
         */
        private void load() {
            new SwingWorker<Void, List<Node>>() {
                @Override
                protected Void doInBackground() throws Exception {
                    Random rnd = new Random(7);
                    String[] regions = {"us-east", "us-west", "eu-central",
                                        "eu-west", "ap-south", "ap-north"};
                    String[] states = {"healthy", "healthy", "healthy",
                                       "degraded", "offline"};
                    List<Node> batch = new ArrayList<>();
                    for (int i = 0; i < TOTAL; i++) {
                        batch.add(new Node(
                                String.format("node-%05d", i),
                                regions[rnd.nextInt(regions.length)],
                                states[rnd.nextInt(states.length)],
                                1 << rnd.nextInt(6),
                                rnd.nextDouble(),
                                (long) (rnd.nextDouble() * 5_000_000)));
                        if (batch.size() == 500) {
                            publish(new ArrayList<>(batch));
                            batch.clear();
                            Thread.sleep(12);   // pretend the rows come from somewhere slow
                        }
                    }
                    if (!batch.isEmpty()) {
                        publish(new ArrayList<>(batch));
                    }
                    return null;
                }

                @Override
                protected void process(List<List<Node>> chunks) {
                    chunks.forEach(model::addAll);
                    progress.setValue(model.getRowCount());
                    updateStatus();
                }

                @Override
                protected void done() {
                    progress.setVisible(false);
                    updateStatus();
                }
            }.execute();
        }
    }
}
