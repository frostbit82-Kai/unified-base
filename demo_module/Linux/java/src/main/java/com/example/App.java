package com.example;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.GradientPaint;
import java.awt.RadialGradientPaint;
import java.awt.RenderingHints;
import java.awt.geom.Ellipse2D;
import java.awt.geom.Point2D;
import java.awt.image.BufferedImage;
import javax.swing.JFrame;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;
import javax.swing.Timer;

/**
 * Unified Base demo: a single 800x600 Swing window with a custom, double-buffered,
 * antialiased JPanel that animates a bouncing ball at ~60 fps via a javax.swing.Timer.
 *
 * Pure JDK, no external dependencies.
 */
public class App {

    public static void main(String[] args) {
        SwingUtilities.invokeLater(App::createAndShow);
    }

    private static void createAndShow() {
        JFrame frame = new JFrame("Java (Swing) — Unified Base demo");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setContentPane(new BouncePanel());
        frame.pack();
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    /**
     * A custom panel that draws and animates a glowing ball bouncing inside its bounds.
     * Swing's JPanel is double-buffered by default; we add antialiasing for smooth edges.
     */
    static final class BouncePanel extends JPanel {

        private static final int WIDTH = 800;
        private static final int HEIGHT = 600;
        private static final int FPS = 60;
        private static final int RADIUS = 34;

        private final Color[] palette = {
            new Color(0x4F, 0xC3, 0xF7),
            new Color(0x81, 0xC7, 0x84),
            new Color(0xFF, 0xB7, 0x4D),
            new Color(0xE5, 0x73, 0x73),
            new Color(0xBA, 0x68, 0xC8)
        };

        private double x = 120, y = 90;
        private double vx = 4.2, vy = 3.1;
        private int colorIndex = 0;
        private long frames = 0;

        // Everything below is cached pixels. Re-rasterizing the gradients and
        // the grid every frame cost ~5 ms of CPU; the scene only actually
        // changes where the ball is, so the static parts are drawn once.
        private BufferedImage background;              // gradient + grid
        private final BufferedImage[] sprites =         // glow + ball, per color
                new BufferedImage[palette.length];
        // measured fps (the old HUD just printed the target and always said 60)
        private double fps;
        private long fpsClock = System.nanoTime();
        private long fpsFrames = 0;

        BouncePanel() {
            setPreferredSize(new Dimension(WIDTH, HEIGHT));
            setBackground(new Color(0x10, 0x14, 0x20));

            Timer timer = new Timer(1000 / FPS, e -> {
                step();
                repaint();
            });
            timer.start();
        }

        private void step() {
            frames++;
            x += vx;
            y += vy;

            int w = Math.max(getWidth(), 2 * RADIUS + 1);
            int h = Math.max(getHeight(), 2 * RADIUS + 1);

            boolean bounced = false;
            if (x - RADIUS < 0) {
                x = RADIUS;
                vx = Math.abs(vx);
                bounced = true;
            } else if (x + RADIUS > w) {
                x = w - RADIUS;
                vx = -Math.abs(vx);
                bounced = true;
            }
            if (y - RADIUS < 0) {
                y = RADIUS;
                vy = Math.abs(vy);
                bounced = true;
            } else if (y + RADIUS > h) {
                y = h - RADIUS;
                vy = -Math.abs(vy);
                bounced = true;
            }
            if (bounced) {
                colorIndex = (colorIndex + 1) % palette.length;
            }
        }

        @Override
        protected void paintComponent(Graphics g) {
            super.paintComponent(g);
            Graphics2D g2 = (Graphics2D) g.create();
            try {
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING,
                        RenderingHints.VALUE_ANTIALIAS_ON);

                int w = getWidth();
                int h = getHeight();

                g2.drawImage(background(w, h), 0, 0, null);

                Color base = palette[colorIndex];

                // Soft trailing echoes for a sense of motion. Flat alpha fills,
                // so these stay cheap without a cache.
                for (int i = 4; i >= 1; i--) {
                    double tx = x - vx * i * 2.2;
                    double ty = y - vy * i * 2.2;
                    int alpha = 26 - i * 4;
                    if (alpha <= 0) {
                        continue;
                    }
                    double r = RADIUS * (1.0 - i * 0.07);
                    g2.setColor(new Color(base.getRed(), base.getGreen(), base.getBlue(), alpha));
                    g2.fill(new Ellipse2D.Double(tx - r, ty - r, r * 2, r * 2));
                }

                // Glow + shaded ball + highlight, rasterized once per color.
                BufferedImage sprite = sprite(colorIndex);
                int half = sprite.getWidth() / 2;
                g2.drawImage(sprite, (int) Math.round(x) - half,
                        (int) Math.round(y) - half, null);

                drawHud(g2);
            } finally {
                g2.dispose();
            }
        }

        /** Gradient + grid, rasterized once per panel size. */
        private BufferedImage background(int w, int h) {
            if (background != null && background.getWidth() == w
                    && background.getHeight() == h) {
                return background;
            }
            BufferedImage img = new BufferedImage(Math.max(w, 1), Math.max(h, 1),
                    BufferedImage.TYPE_INT_RGB);
            Graphics2D g2 = img.createGraphics();
            try {
                g2.setPaint(new GradientPaint(0, 0, new Color(0x12, 0x17, 0x27),
                        0, h, new Color(0x08, 0x0A, 0x12)));
                g2.fillRect(0, 0, w, h);
                g2.setColor(new Color(255, 255, 255, 10));
                g2.setStroke(new BasicStroke(1f));
                int step = 40;
                for (int gx = step; gx < w; gx += step) {
                    g2.drawLine(gx, 0, gx, h);
                }
                for (int gy = step; gy < h; gy += step) {
                    g2.drawLine(0, gy, w, gy);
                }
            } finally {
                g2.dispose();
            }
            background = img;
            return img;
        }

        /**
         * The ball and its glow for one palette color, drawn into a transparent
         * image centred on the sprite. Only 5 of these ever exist.
         */
        private BufferedImage sprite(int index) {
            if (sprites[index] != null) {
                return sprites[index];
            }
            int size = (int) Math.ceil(RADIUS * 4.4);
            double c = size / 2.0;                       // sprite-local centre
            Color base = palette[index];
            BufferedImage img = new BufferedImage(size, size,
                    BufferedImage.TYPE_INT_ARGB);
            Graphics2D g2 = img.createGraphics();
            try {
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING,
                        RenderingHints.VALUE_ANTIALIAS_ON);
                g2.setRenderingHint(RenderingHints.KEY_RENDERING,
                        RenderingHints.VALUE_RENDER_QUALITY);

                g2.setPaint(new RadialGradientPaint(
                        new Point2D.Double(c, c), RADIUS * 2.2f,
                        new float[]{0f, 1f},
                        new Color[]{
                            new Color(base.getRed(), base.getGreen(), base.getBlue(), 120),
                            new Color(base.getRed(), base.getGreen(), base.getBlue(), 0)
                        }));
                g2.fill(new Ellipse2D.Double(0, 0, size, size));

                g2.setPaint(new RadialGradientPaint(
                        new Point2D.Double(c - RADIUS * 0.35, c - RADIUS * 0.35),
                        RADIUS * 1.4f, new float[]{0f, 1f},
                        new Color[]{base.brighter(), base.darker()}));
                g2.fill(new Ellipse2D.Double(c - RADIUS, c - RADIUS,
                        RADIUS * 2, RADIUS * 2));

                g2.setColor(new Color(255, 255, 255, 150));
                double hr = RADIUS * 0.28;
                g2.fill(new Ellipse2D.Double(c - RADIUS * 0.42 - hr,
                        c - RADIUS * 0.42 - hr, hr * 2, hr * 2));
            } finally {
                g2.dispose();
            }
            sprites[index] = img;
            return img;
        }

        private void drawHud(Graphics2D g2) {
            fpsFrames++;
            long now = System.nanoTime();
            double elapsed = (now - fpsClock) / 1e9;
            if (elapsed >= 0.5) {
                fps = fpsFrames / elapsed;
                fpsFrames = 0;
                fpsClock = now;
            }
            g2.setColor(new Color(255, 255, 255, 160));
            g2.setFont(getFont().deriveFont(13f));
            double speed = Math.hypot(vx, vy);
            g2.drawString(String.format(
                    "Java Swing · %.0f/%d fps · frame %d · speed %.1f px/tick",
                    fps, FPS, frames, speed), 16, getHeight() - 16);
        }
    }
}
