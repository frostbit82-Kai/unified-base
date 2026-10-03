/* X11 native demo for Unified Base.
 *
 * Raw Xlib, nothing else: a program that only exists on Linux. Natively it
 * embeds like any X11 app; on Windows the launcher runs it inside WSL, where
 * WSLg draws its window on the Windows desktop.
 *
 * The X libraries are linked statically, so the binary needs nothing beyond
 * glibc — a stock WSL distro can run it without installing libx11.
 * Build: make
 */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <string.h>
#include <sys/select.h>
#include <sys/time.h>

static const unsigned long PALETTE[] = {0x4F8CFF, 0xFF6B6B, 0x3FB950,
                                        0xF2C14E, 0xB37DFF, 0x4FC3F7};
#define NCOLORS (sizeof(PALETTE) / sizeof(PALETTE[0]))

typedef struct { int x, y, w, h; } Box;

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if (!d) {
        fprintf(stderr, "x11-native: cannot open display (is DISPLAY set?)\n");
        return 1;
    }
    int scr = DefaultScreen(d);
    int W = 760, H = 520;
    Window win = XCreateSimpleWindow(d, RootWindow(d, scr), 0, 0, W, H, 0, 0,
                                     0x12151C);
    XStoreName(d, win, "X11 Native Demo");
    XClassHint ch = {"x11-native", "UnifiedBaseDemo"};
    XSetClassHint(d, win, &ch);
    Atom wm_delete = XInternAtom(d, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(d, win, &wm_delete, 1);
    XSelectInput(d, win, ExposureMask | StructureNotifyMask | ButtonPressMask);
    XMapWindow(d, win);

    GC gc = XCreateGC(d, win, 0, NULL);
    XFontStruct *big = XLoadQueryFont(d, "-*-helvetica-bold-r-*-*-24-*-*-*-*-*-*-*");
    XFontStruct *small = XLoadQueryFont(d, "fixed");
    Pixmap buf = XCreatePixmap(d, win, W, H, DefaultDepth(d, scr));

    double bx = 80, by = 80, vx = 3.1, vy = 2.4;
    int color = 0, bounces = 0, r = 22;
    int fd = ConnectionNumber(d);

    for (;;) {
        while (XPending(d)) {
            XEvent ev;
            XNextEvent(d, &ev);
            if (ev.type == ClientMessage && (Atom)ev.xclient.data.l[0] == wm_delete)
                goto done;
            if (ev.type == ConfigureNotify &&
                (ev.xconfigure.width != W || ev.xconfigure.height != H)) {
                W = ev.xconfigure.width;
                H = ev.xconfigure.height;
                XFreePixmap(d, buf);
                buf = XCreatePixmap(d, win, W, H, DefaultDepth(d, scr));
            }
            if (ev.type == ButtonPress) {
                int bx0 = 16, by0 = H - 50;
                if (ev.xbutton.x >= bx0 && ev.xbutton.x < bx0 + 140 &&
                    ev.xbutton.y >= by0 && ev.xbutton.y < by0 + 34)
                    color = (color + 1) % NCOLORS;
            }
        }
        Box a = {16, 78, W - 32, H - 78 - 66};
        if (a.w < 60) a.w = 60;
        if (a.h < 40) a.h = 40;
        bx += vx; by += vy;
        if (bx - r < 0)   { bx = r;       vx = -vx; bounces++; }
        if (bx + r > a.w) { bx = a.w - r; vx = -vx; bounces++; }
        if (by - r < 0)   { by = r;       vy = -vy; bounces++; }
        if (by + r > a.h) { by = a.h - r; vy = -vy; bounces++; }

        /* Everything into the pixmap, then one copy: no flicker. */
        XSetForeground(d, gc, 0x12151C);
        XFillRectangle(d, buf, gc, 0, 0, W, H);
        if (big) XSetFont(d, gc, big->fid);
        XSetForeground(d, gc, 0xF0F3F8);
        const char *title = "X11 - Unified Base demo";
        XDrawString(d, buf, gc, 16, 38, title, strlen(title));
        if (small) XSetFont(d, gc, small->fid);
        XSetForeground(d, gc, 0x8A93A6);
        const char *sub = "Raw Xlib, Linux only - native on Linux, WSL on Windows";
        XDrawString(d, buf, gc, 16, 62, sub, strlen(sub));
        XSetForeground(d, gc, 0x1A1F2B);
        XFillRectangle(d, buf, gc, a.x, a.y, a.w, a.h);
        XSetForeground(d, gc, PALETTE[color]);
        XFillArc(d, buf, gc, a.x + (int)bx - r, a.y + (int)by - r, 2 * r, 2 * r,
                 0, 360 * 64);
        XSetForeground(d, gc, 0xFFFFFF);
        XSetLineAttributes(d, gc, 2, LineSolid, CapRound, JoinRound);
        XDrawArc(d, buf, gc, a.x + (int)bx - r, a.y + (int)by - r, 2 * r, 2 * r,
                 0, 360 * 64);
        XSetForeground(d, gc, 0x2C3445);
        XFillRectangle(d, buf, gc, 16, H - 50, 140, 34);
        XSetForeground(d, gc, 0xE6EAF2);
        XDrawString(d, buf, gc, 38, H - 29, "Change color", 12);
        char cnt[48];
        snprintf(cnt, sizeof cnt, "Bounces: %d", bounces);
        XSetForeground(d, gc, 0xC9D1E0);
        XDrawString(d, buf, gc, 172, H - 29, cnt, strlen(cnt));
        XCopyArea(d, buf, win, gc, 0, 0, W, H, 0, 0);
        XFlush(d);

        /* ~60 fps, but wake at once for input. */
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        struct timeval tv = {0, 16000};
        select(fd + 1, &fds, NULL, NULL, &tv);
    }
done:
    XFreePixmap(d, buf);
    XFreeGC(d, gc);
    XCloseDisplay(d);
    return 0;
}
