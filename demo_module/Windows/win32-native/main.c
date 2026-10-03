/* Win32 native demo for Unified Base.
 *
 * A plain Win32 API program: no framework, no runtime, one .exe. On Windows
 * it runs natively; on Linux the launcher runs it through Wine, and because
 * Wine draws real X11 windows it embeds into a pane like any Linux app.
 *
 * Build: make   (Linux cross-compiles with MinGW-w64; Windows uses MSYS2 gcc)
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <commctrl.h>
#include <stdio.h>

#define ID_COLOR 101
#define ID_SPEED 102
#define ID_TIMER 1

static const COLORREF PALETTE[] = {
    RGB(0x4F, 0x8C, 0xFF), RGB(0xFF, 0x6B, 0x6B), RGB(0x3F, 0xB9, 0x50),
    RGB(0xF2, 0xC1, 0x4E), RGB(0xB3, 0x7D, 0xFF), RGB(0x4F, 0xC3, 0xF7)};
#define NCOLORS (sizeof(PALETTE) / sizeof(PALETTE[0]))

static HWND g_btn, g_count, g_speed, g_speed_lbl;
static HFONT g_title, g_text;
static HBRUSH g_panel;            /* background behind the labels and slider */
static double bx = 80, by = 80, vx = 3.1, vy = 2.4;
static int g_color, g_bounces, g_dpi = 96;
static RECT g_arena;

static int S(int px) { return MulDiv(px, g_dpi, 96); }

static void layout(HWND hwnd) {
    RECT rc;
    GetClientRect(hwnd, &rc);
    int pad = S(16), bar = S(34), top = S(78);
    g_arena.left = pad;
    g_arena.top = top;
    g_arena.right = rc.right - pad;
    g_arena.bottom = rc.bottom - pad - bar - S(8);
    if (g_arena.bottom < g_arena.top + S(40)) g_arena.bottom = g_arena.top + S(40);
    int y = rc.bottom - pad - bar;
    MoveWindow(g_btn, pad, y, S(130), bar, TRUE);
    int cx = pad + S(142);
    MoveWindow(g_count, cx, y + S(8), S(110), S(22), TRUE);
    /* The slider gives up width before the "Speed" label lands on the count. */
    int sw = rc.right - pad - (cx + S(118) + S(56));
    if (sw > S(170)) sw = S(170);
    if (sw < S(60)) sw = S(60);
    int sx = rc.right - pad - sw;
    MoveWindow(g_speed_lbl, sx - S(56), y + S(8), S(52), S(22), TRUE);
    MoveWindow(g_speed, sx, y, sw, bar, TRUE);
}

static void set_count(void) {
    wchar_t buf[48];
    swprintf(buf, 48, L"Bounces: %d", g_bounces);
    SetWindowTextW(g_count, buf);
}

static void step(HWND hwnd) {
    double speed = SendMessageW(g_speed, TBM_GETPOS, 0, 0) / 10.0;
    int r = S(22);
    bx += vx * speed;
    by += vy * speed;
    int w = g_arena.right - g_arena.left, h = g_arena.bottom - g_arena.top;
    if (bx - r < 0)  { bx = r;     vx = -vx; g_bounces++; }
    if (bx + r > w)  { bx = w - r; vx = -vx; g_bounces++; }
    if (by - r < 0)  { by = r;     vy = -vy; g_bounces++; }
    if (by + r > h)  { by = h - r; vy = -vy; g_bounces++; }
    set_count();
    InvalidateRect(hwnd, &g_arena, FALSE);
}

static void paint(HWND hwnd) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(hwnd, &ps);
    RECT rc;
    GetClientRect(hwnd, &rc);
    /* Double-buffered: draw everything off screen, blit once, no flicker. */
    HDC mem = CreateCompatibleDC(dc);
    HBITMAP bmp = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
    HGDIOBJ old = SelectObject(mem, bmp);

    HBRUSH bg = CreateSolidBrush(RGB(0x12, 0x15, 0x1C));
    FillRect(mem, &rc, bg);
    DeleteObject(bg);
    SetBkMode(mem, TRANSPARENT);
    SelectObject(mem, g_title);
    SetTextColor(mem, RGB(0xF0, 0xF3, 0xF8));
    const wchar_t *title = L"Win32 \x00B7 Unified Base demo";
    TextOutW(mem, S(16), S(12), title, (int)wcslen(title));
    SelectObject(mem, g_text);
    SetTextColor(mem, RGB(0x8A, 0x93, 0xA6));
    const wchar_t *sub = L"Native Windows program \x2014 Wine on Linux, native on Windows";
    TextOutW(mem, S(16), S(48), sub, (int)wcslen(sub));

    HBRUSH arena = CreateSolidBrush(RGB(0x1A, 0x1F, 0x2B));
    HPEN edge = CreatePen(PS_SOLID, 1, RGB(0x2C, 0x34, 0x45));
    SelectObject(mem, arena);
    SelectObject(mem, edge);
    RoundRect(mem, g_arena.left, g_arena.top, g_arena.right, g_arena.bottom,
              S(12), S(12));
    DeleteObject(arena);
    DeleteObject(edge);

    int r = S(22);
    int cx = g_arena.left + (int)bx, cy = g_arena.top + (int)by;
    HBRUSH ball = CreateSolidBrush(PALETTE[g_color]);
    HPEN ring = CreatePen(PS_SOLID, S(2), RGB(0xFF, 0xFF, 0xFF));
    SelectObject(mem, ball);
    SelectObject(mem, ring);
    Ellipse(mem, cx - r, cy - r, cx + r, cy + r);
    DeleteObject(ball);
    DeleteObject(ring);

    BitBlt(dc, 0, 0, rc.right, rc.bottom, mem, 0, 0, SRCCOPY);
    SelectObject(mem, old);
    DeleteObject(bmp);
    DeleteDC(mem);
    EndPaint(hwnd, &ps);
}

static LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        HDC dc = GetDC(hwnd);
        g_dpi = GetDeviceCaps(dc, LOGPIXELSY);
        ReleaseDC(hwnd, dc);
        g_title = CreateFontW(-S(26), 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
                              0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
        g_text = CreateFontW(-S(14), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                             0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
        HINSTANCE hi = ((LPCREATESTRUCT)lp)->hInstance;
        g_btn = CreateWindowW(L"BUTTON", L"Change color",
                              WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 0, 0, 0, 0,
                              hwnd, (HMENU)ID_COLOR, hi, NULL);
        g_count = CreateWindowW(L"STATIC", L"Bounces: 0", WS_CHILD | WS_VISIBLE,
                                0, 0, 0, 0, hwnd, NULL, hi, NULL);
        g_speed_lbl = CreateWindowW(L"STATIC", L"Speed", WS_CHILD | WS_VISIBLE
                                    | SS_RIGHT, 0, 0, 0, 0, hwnd, NULL, hi, NULL);
        g_speed = CreateWindowW(TRACKBAR_CLASSW, L"", WS_CHILD | WS_VISIBLE
                                | TBS_NOTICKS, 0, 0, 0, 0, hwnd,
                                (HMENU)ID_SPEED, hi, NULL);
        SendMessageW(g_speed, TBM_SETRANGE, TRUE, MAKELPARAM(2, 40));
        SendMessageW(g_speed, TBM_SETPOS, TRUE, 12);
        HWND kids[] = {g_btn, g_count, g_speed_lbl};
        for (int i = 0; i < 3; i++)
            SendMessageW(kids[i], WM_SETFONT, (WPARAM)g_text, TRUE);
        layout(hwnd);
        SetTimer(hwnd, ID_TIMER, 16, NULL);
        return 0;
    }
    case WM_SIZE:
        layout(hwnd);
        InvalidateRect(hwnd, NULL, FALSE);
        return 0;
    case WM_TIMER:
        step(hwnd);
        return 0;
    case WM_COMMAND:
        if (LOWORD(wp) == ID_COLOR) {
            g_color = (g_color + 1) % NCOLORS;
            InvalidateRect(hwnd, &g_arena, FALSE);
        }
        return 0;
    case WM_CTLCOLORSTATIC:
        SetTextColor((HDC)wp, RGB(0xC9, 0xD1, 0xE0));
        SetBkColor((HDC)wp, RGB(0x12, 0x15, 0x1C));
        if (!g_panel) g_panel = CreateSolidBrush(RGB(0x12, 0x15, 0x1C));
        return (LRESULT)g_panel;
    case WM_ERASEBKGND:
        return 1;                       /* paint() covers every pixel */
    case WM_PAINT:
        paint(hwnd);
        return 0;
    case WM_DESTROY:
        KillTimer(hwnd, ID_TIMER);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE hi, HINSTANCE prev, PWSTR cmd, int show) {
    (void)prev;
    (void)cmd;
    SetProcessDPIAware();
    INITCOMMONCONTROLSEX icc = {sizeof(icc), ICC_BAR_CLASSES};
    InitCommonControlsEx(&icc);
    WNDCLASSW wc = {0};
    wc.lpfnWndProc = wndproc;
    wc.hInstance = hi;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wc.lpszClassName = L"UnifiedBaseWin32Demo";
    RegisterClassW(&wc);
    HWND hwnd = CreateWindowW(wc.lpszClassName, L"Win32 Native Demo",
                              WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                              760, 520, NULL, NULL, hi, NULL);
    ShowWindow(hwnd, show);
    UpdateWindow(hwnd);
    MSG m;
    while (GetMessageW(&m, NULL, 0, 0) > 0) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    return 0;
}
