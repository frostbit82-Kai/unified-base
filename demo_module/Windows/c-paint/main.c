/* C — Unified Base Windows demo: a paint program on plain Win32.
 *
 * What the classic Win32 toolkit gives a C program for free: common
 * controls (push-like radio buttons, a trackbar, a status bar), common
 * dialogs (Choose Colour, Open, Save As), the clipboard, keyboard
 * accelerators, and GDI to draw with: pens, flood fill, rubber-band shapes
 * drawn over a double-buffered canvas, and BMP files written by hand.
 *
 * No menu bar, on purpose: Unified Base embeds a window by making it a
 * child window, and a Win32 child can't have a menu - its HMENU slot is
 * reinterpreted as the control ID. Every command is a button and a key.
 *
 * Keys: Ctrl+N new, Ctrl+O open, Ctrl+S save, Ctrl+Z undo, Ctrl+C / Ctrl+V
 * copy and paste; P L R E F X pick a tool, [ and ] change the width.
 *
 * `paint.exe --selftest` draws, fills, saves, reloads and compares pixels.
 * Build: make (zig cc on Windows, MinGW-w64 on Linux).
 */
#define UNICODE
#define _UNICODE
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00 /* Windows 10: GetDpiForWindow */
#endif
#include <windows.h>
#include <commctrl.h>
#include <commdlg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define DOC_W 1600
#define DOC_H 1000
#define UNDO_MAX 8 /* 6.4 MB each */

enum { T_PEN, T_LINE, T_RECT, T_ELLIPSE, T_FILL, T_ERASER, T_COUNT };
enum {
    ID_NEW = 100, ID_OPEN, ID_SAVE, ID_UNDO, ID_COPY, ID_PASTE,
    ID_TOOL0 = 120, ID_COLOR = 140, ID_SWATCH, ID_WIDTH, ID_WIDTH_LABEL,
    ID_WIDER, ID_THINNER
};
static const wchar_t *TOOL_NAMES[T_COUNT] = {
    L"Pen", L"Line", L"Rectangle", L"Ellipse", L"Fill", L"Eraser"
};

static HINSTANCE g_inst;
static HWND g_main, g_canvas, g_status, g_width, g_swatch;
static HDC g_doc;                       /* the picture: a memory DC */
static HBITMAP g_docbmp;
static HGDIOBJ g_docold;
static COLORREF g_color = RGB(0x23, 0x86, 0x36), g_custom[16];
static HBRUSH g_swatch_brush;
static HFONT g_font;
static int g_tool = T_PEN, g_pen = 6;
static BOOL g_drag;
static POINT g_from, g_to, g_last;
static HBITMAP g_undo[UNDO_MAX];
static int g_nundo;

/* -- the document ------------------------------------------------------ */
static void doc_clear(void)
{
    RECT r = {0, 0, DOC_W, DOC_H};
    FillRect(g_doc, &r, (HBRUSH)GetStockObject(WHITE_BRUSH));
}

static void doc_create(void)
{
    HDC screen = GetDC(NULL);
    g_doc = CreateCompatibleDC(screen);
    g_docbmp = CreateCompatibleBitmap(screen, DOC_W, DOC_H);
    ReleaseDC(NULL, screen);
    g_docold = SelectObject(g_doc, g_docbmp);
    doc_clear();
}

static HBITMAP doc_copy(void)
{
    HDC screen = GetDC(NULL);
    HDC m = CreateCompatibleDC(screen);
    HBITMAP b = CreateCompatibleBitmap(screen, DOC_W, DOC_H);
    ReleaseDC(NULL, screen);
    HGDIOBJ o = SelectObject(m, b);
    BitBlt(m, 0, 0, DOC_W, DOC_H, g_doc, 0, 0, SRCCOPY);
    SelectObject(m, o);
    DeleteDC(m);
    return b;
}

static void doc_blit(HBITMAP b)
{
    BITMAP bm;
    HDC m = CreateCompatibleDC(g_doc);
    HGDIOBJ o = SelectObject(m, b);
    GetObjectW(b, sizeof bm, &bm);
    BitBlt(g_doc, 0, 0, bm.bmWidth, bm.bmHeight, m, 0, 0, SRCCOPY);
    SelectObject(m, o);
    DeleteDC(m);
}

/* Undo keeps whole copies of the picture: simple, and 8 of them is 51 MB. */
static void undo_push(void)
{
    if (g_nundo == UNDO_MAX) {
        DeleteObject(g_undo[0]);
        memmove(g_undo, g_undo + 1, sizeof g_undo[0] * (UNDO_MAX - 1));
        g_nundo--;
    }
    g_undo[g_nundo++] = doc_copy();
}

static void undo_pop(void)
{
    if (g_nundo == 0)
        return;
    HBITMAP b = g_undo[--g_nundo];
    doc_blit(b);
    DeleteObject(b);
}

/* A shape, onto any DC: the document, or the canvas's back buffer while a
 * drag is still in progress (the rubber band). Pens wider than 1 are
 * geometric pens with round caps, which is what makes strokes smooth. */
static void draw_shape(HDC dc, int tool, POINT a, POINT b)
{
    COLORREF c = tool == T_ERASER ? RGB(255, 255, 255) : g_color;
    HPEN pen = CreatePen(PS_SOLID, g_pen, c);
    HGDIOBJ op = SelectObject(dc, pen);
    HGDIOBJ ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    switch (tool) {
    case T_RECT:
        Rectangle(dc, a.x, a.y, b.x, b.y);
        break;
    case T_ELLIPSE:
        Ellipse(dc, a.x, a.y, b.x, b.y);
        break;
    default:
        MoveToEx(dc, a.x, a.y, NULL);
        LineTo(dc, b.x, b.y);
        /* LineTo stops short of its end point; a zero-length segment
         * (a click) would draw nothing at all. */
        LineTo(dc, b.x + (a.x == b.x && a.y == b.y), b.y);
    }
    SelectObject(dc, op);
    SelectObject(dc, ob);
    DeleteObject(pen);
}

static void flood(int x, int y)
{
    COLORREF at = GetPixel(g_doc, x, y);
    if (at == g_color || at == CLR_INVALID)
        return;
    HBRUSH br = CreateSolidBrush(g_color);
    HGDIOBJ o = SelectObject(g_doc, br);
    ExtFloodFill(g_doc, x, y, at, FLOODFILLSURFACE);
    SelectObject(g_doc, o);
    DeleteObject(br);
}

/* -- BMP files ------------------------------------------------------------- */
static BOOL save_bmp(const wchar_t *path)
{
    BITMAPINFOHEADER bi = {sizeof bi, DOC_W, DOC_H, 1, 24, BI_RGB};
    DWORD stride = (DOC_W * 3 + 3) & ~3u; /* rows are padded to 4 bytes */
    DWORD size = stride * DOC_H;
    BITMAPFILEHEADER fh = {0x4D42, sizeof fh + sizeof bi + size, 0, 0, sizeof fh + sizeof bi};
    BYTE *px = malloc(size);
    if (!px)
        return FALSE;
    /* GetDIBits wants the bitmap out of any DC while it reads. */
    SelectObject(g_doc, g_docold);
    GetDIBits(g_doc, g_docbmp, 0, DOC_H, px, (BITMAPINFO *)&bi, DIB_RGB_COLORS);
    SelectObject(g_doc, g_docbmp);
    HANDLE f = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    DWORD n;
    BOOL ok = f != INVALID_HANDLE_VALUE
        && WriteFile(f, &fh, sizeof fh, &n, NULL)
        && WriteFile(f, &bi, sizeof bi, &n, NULL)
        && WriteFile(f, px, size, &n, NULL);
    if (f != INVALID_HANDLE_VALUE)
        CloseHandle(f);
    free(px);
    return ok;
}

static BOOL load_bmp(const wchar_t *path)
{
    HBITMAP b = (HBITMAP)LoadImageW(NULL, path, IMAGE_BITMAP, 0, 0, LR_LOADFROMFILE);
    if (!b)
        return FALSE;
    doc_clear();
    doc_blit(b);
    DeleteObject(b);
    return TRUE;
}

/* -- UI helpers ------------------------------------------------------------- */
static void status(void)
{
    wchar_t s[96];
    SendMessageW(g_status, SB_SETTEXTW, 0, (LPARAM)TOOL_NAMES[g_tool]);
    swprintf(s, 96, L"#%02x%02x%02x", GetRValue(g_color), GetGValue(g_color), GetBValue(g_color));
    SendMessageW(g_status, SB_SETTEXTW, 1, (LPARAM)s);
    swprintf(s, 96, L"width %d", g_pen);
    SendMessageW(g_status, SB_SETTEXTW, 2, (LPARAM)s);
    swprintf(s, 96, L"%d undo step%s · picture %d×%d", g_nundo, g_nundo == 1 ? L"" : L"s", DOC_W, DOC_H);
    SendMessageW(g_status, SB_SETTEXTW, 4, (LPARAM)s);
}

static void set_tool(int t)
{
    g_tool = t;
    CheckRadioButton(g_main, ID_TOOL0, ID_TOOL0 + T_COUNT - 1, ID_TOOL0 + t);
    status();
}

static void set_width(int w)
{
    g_pen = w < 1 ? 1 : w > 40 ? 40 : w;
    SendMessageW(g_width, TBM_SETPOS, TRUE, g_pen);
    status();
}

static void set_color(COLORREF c)
{
    g_color = c;
    if (g_swatch_brush)
        DeleteObject(g_swatch_brush);
    g_swatch_brush = CreateSolidBrush(c);
    InvalidateRect(g_swatch, NULL, TRUE);
    status();
}

static BOOL file_dialog(BOOL save, wchar_t *path, DWORD cap)
{
    OPENFILENAMEW o = {sizeof o};
    o.hwndOwner = g_main;
    o.lpstrFilter = L"Bitmap (*.bmp)\0*.bmp\0";
    o.lpstrFile = path;
    o.nMaxFile = cap;
    o.lpstrDefExt = L"bmp";
    o.Flags = save ? OFN_OVERWRITEPROMPT : OFN_FILEMUSTEXIST;
    return save ? GetSaveFileNameW(&o) : GetOpenFileNameW(&o);
}

static void command(int id)
{
    wchar_t path[MAX_PATH] = L"";
    switch (id) {
    case ID_NEW:
        undo_push();
        doc_clear();
        break;
    case ID_OPEN:
        if (file_dialog(FALSE, path, MAX_PATH)) {
            undo_push();
            if (!load_bmp(path))
                MessageBoxW(g_main, L"That file isn't a bitmap Windows can read.", L"Open", MB_ICONWARNING);
        }
        break;
    case ID_SAVE:
        wcscpy(path, L"drawing.bmp");
        if (file_dialog(TRUE, path, MAX_PATH) && !save_bmp(path))
            MessageBoxW(g_main, L"Couldn't write the file.", L"Save", MB_ICONWARNING);
        break;
    case ID_UNDO:
        undo_pop();
        break;
    case ID_COPY:
        /* The clipboard takes ownership of the bitmap handed to it. */
        if (OpenClipboard(g_main)) {
            EmptyClipboard();
            SetClipboardData(CF_BITMAP, doc_copy());
            CloseClipboard();
        }
        break;
    case ID_PASTE:
        if (IsClipboardFormatAvailable(CF_BITMAP) && OpenClipboard(g_main)) {
            undo_push();
            doc_blit((HBITMAP)GetClipboardData(CF_BITMAP));
            CloseClipboard();
        }
        break;
    case ID_COLOR: {
        CHOOSECOLORW cc = {sizeof cc};
        cc.hwndOwner = g_main;
        cc.lpCustColors = g_custom;
        cc.rgbResult = g_color;
        cc.Flags = CC_FULLOPEN | CC_RGBINIT;
        if (ChooseColorW(&cc))
            set_color(cc.rgbResult);
        break;
    }
    case ID_WIDER:
        set_width(g_pen + 2);
        break;
    case ID_THINNER:
        set_width(g_pen - 2);
        break;
    default:
        if (id >= ID_TOOL0 && id < ID_TOOL0 + T_COUNT)
            set_tool(id - ID_TOOL0);
    }
    status();
    InvalidateRect(g_canvas, NULL, FALSE);
}

/* -- canvas ------------------------------------------------------------------- */
static LRESULT CALLBACK canvas_proc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    POINT p = {(short)LOWORD(lp), (short)HIWORD(lp)};
    switch (msg) {
    case WM_LBUTTONDOWN:
        SetCapture(h);
        undo_push();
        g_from = g_to = g_last = p;
        if (g_tool == T_FILL) {
            flood(p.x, p.y);
            ReleaseCapture();
        } else {
            g_drag = TRUE;
            if (g_tool == T_PEN || g_tool == T_ERASER)
                draw_shape(g_doc, g_tool, p, p);
        }
        status();
        InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_MOUSEMOVE: {
        wchar_t s[32];
        swprintf(s, 32, L"%d, %d", p.x, p.y);
        SendMessageW(g_status, SB_SETTEXTW, 3, (LPARAM)s);
        if (!g_drag)
            return 0;
        if (g_tool == T_PEN || g_tool == T_ERASER) {
            draw_shape(g_doc, g_tool, g_last, p);
            g_last = p;
        }
        g_to = p;
        InvalidateRect(h, NULL, FALSE);
        return 0;
    }
    case WM_LBUTTONUP:
        if (g_drag && g_tool != T_PEN && g_tool != T_ERASER)
            draw_shape(g_doc, g_tool, g_from, p);
        g_drag = FALSE;
        ReleaseCapture();
        InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_ERASEBKGND:
        return 1;          /* WM_PAINT covers every pixel */
    case WM_PAINT: {
        PAINTSTRUCT ps;
        RECT rc;
        HDC dc = BeginPaint(h, &ps);
        GetClientRect(h, &rc);
        /* Picture + the shape being dragged, composed offscreen and copied
         * in one go: the rubber band never flickers. */
        HDC m = CreateCompatibleDC(dc);
        HBITMAP b = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
        HGDIOBJ o = SelectObject(m, b);
        HBRUSH bg = CreateSolidBrush(RGB(0x3b, 0x40, 0x48));
        FillRect(m, &rc, bg);
        DeleteObject(bg);
        BitBlt(m, 0, 0, DOC_W, DOC_H, g_doc, 0, 0, SRCCOPY);
        if (g_drag && g_tool != T_PEN && g_tool != T_ERASER)
            draw_shape(m, g_tool, g_from, g_to);
        BitBlt(dc, 0, 0, rc.right, rc.bottom, m, 0, 0, SRCCOPY);
        SelectObject(m, o);
        DeleteObject(b);
        DeleteDC(m);
        EndPaint(h, &ps);
        return 0;
    }
    }
    return DefWindowProcW(h, msg, wp, lp);
}

/* -- main window ------------------------------------------------------------------ */
static struct { int id, width; const wchar_t *cls, *text; DWORD style; } CONTROLS[] = {
    {ID_NEW, 64, L"BUTTON", L"New", BS_PUSHBUTTON},
    {ID_OPEN, 72, L"BUTTON", L"Open…", BS_PUSHBUTTON},
    {ID_SAVE, 72, L"BUTTON", L"Save…", BS_PUSHBUTTON},
    {ID_UNDO, 64, L"BUTTON", L"Undo", BS_PUSHBUTTON},
    {ID_COPY, 64, L"BUTTON", L"Copy", BS_PUSHBUTTON},
    {ID_PASTE, 64, L"BUTTON", L"Paste", BS_PUSHBUTTON},
    {ID_TOOL0 + T_PEN, 64, L"BUTTON", L"Pen", BS_AUTORADIOBUTTON | BS_PUSHLIKE | WS_GROUP},
    {ID_TOOL0 + T_LINE, 64, L"BUTTON", L"Line", BS_AUTORADIOBUTTON | BS_PUSHLIKE},
    {ID_TOOL0 + T_RECT, 84, L"BUTTON", L"Rectangle", BS_AUTORADIOBUTTON | BS_PUSHLIKE},
    {ID_TOOL0 + T_ELLIPSE, 72, L"BUTTON", L"Ellipse", BS_AUTORADIOBUTTON | BS_PUSHLIKE},
    {ID_TOOL0 + T_FILL, 64, L"BUTTON", L"Fill", BS_AUTORADIOBUTTON | BS_PUSHLIKE},
    {ID_TOOL0 + T_ERASER, 72, L"BUTTON", L"Eraser", BS_AUTORADIOBUTTON | BS_PUSHLIKE},
    {ID_COLOR, 80, L"BUTTON", L"Colour…", BS_PUSHBUTTON | WS_GROUP},
    {ID_SWATCH, 28, L"STATIC", L"", SS_NOTIFY},
    {ID_WIDTH_LABEL, 44, L"STATIC", L"Width", SS_CENTERIMAGE | SS_RIGHT},
    {ID_WIDTH, 140, TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS},
};
#define NCONTROLS (sizeof CONTROLS / sizeof CONTROLS[0])

/* Flow layout: controls left to right, wrapping to a new row when the
 * window is narrow - a tiled pane can be a third of the screen. */
static void layout(void)
{
    RECT rc, sb;
    double s = GetDpiForWindow(g_main) / 96.0;
    int m = (int)(8 * s), gap = (int)(4 * s), h = (int)(28 * s);
    int x = m, y = m;
    GetClientRect(g_main, &rc);
    SendMessageW(g_status, WM_SIZE, 0, 0);
    GetWindowRect(g_status, &sb);
    for (size_t i = 0; i < NCONTROLS; i++) {
        int w = (int)(CONTROLS[i].width * s);
        if (x + w > rc.right - m && x > m) {
            x = m;
            y += h + gap;
        }
        MoveWindow(GetDlgItem(g_main, CONTROLS[i].id), x, y, w, h, TRUE);
        x += w + gap + (i == 5 || i == 11 ? (int)(10 * s) : 0);   /* group gaps */
    }
    y += h + m;
    MoveWindow(g_canvas, 0, y, rc.right, rc.bottom - y - (sb.bottom - sb.top), TRUE);
    int parts[5] = {(int)(90 * s), (int)(170 * s), (int)(250 * s), (int)(340 * s), -1};
    SendMessageW(g_status, SB_SETPARTS, 5, (LPARAM)parts);
    status();               /* parts made just now hold no text yet */
}

static void create_controls(HWND h)
{
    double s = GetDpiForWindow(h) / 96.0;
    g_font = CreateFontW(-(int)(12 * s), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                         CLEARTYPE_QUALITY, 0, L"Segoe UI");
    for (size_t i = 0; i < NCONTROLS; i++) {
        HWND c = CreateWindowExW(0, CONTROLS[i].cls, CONTROLS[i].text,
                                 WS_CHILD | WS_VISIBLE | CONTROLS[i].style, 0, 0, 10, 10, h,
                                 (HMENU)(INT_PTR)CONTROLS[i].id, g_inst, NULL);
        SendMessageW(c, WM_SETFONT, (WPARAM)g_font, TRUE);
    }
    g_swatch = GetDlgItem(h, ID_SWATCH);
    g_width = GetDlgItem(h, ID_WIDTH);
    SendMessageW(g_width, TBM_SETRANGE, TRUE, MAKELPARAM(1, 40));
    g_canvas = CreateWindowExW(0, L"UbPaintCanvas", NULL, WS_CHILD | WS_VISIBLE, 0, 0, 10, 10,
                               h, NULL, g_inst, NULL);
    g_status = CreateWindowExW(0, STATUSCLASSNAMEW, NULL, WS_CHILD | WS_VISIBLE, 0, 0, 0, 0,
                               h, NULL, g_inst, NULL);
    SendMessageW(g_status, WM_SETFONT, (WPARAM)g_font, TRUE);
}

static LRESULT CALLBACK main_proc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE:
        g_main = h;
        create_controls(h);
        set_color(g_color);
        set_width(g_pen);
        set_tool(T_PEN);
        return 0;
    case WM_SIZE:
        layout();
        return 0;
    case WM_COMMAND:
        if (HIWORD(wp) == BN_CLICKED || HIWORD(wp) == 1 /* accelerator */)
            command(LOWORD(wp));
        return 0;
    case WM_HSCROLL:
        if ((HWND)lp == g_width)
            set_width((int)SendMessageW(g_width, TBM_GETPOS, 0, 0));
        return 0;
    case WM_CTLCOLORSTATIC:
        if ((HWND)lp == g_swatch)
            return (LRESULT)g_swatch_brush;
        break;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

/* -- self-test -------------------------------------------------------------------- */
static int check(BOOL ok, const char *what)
{
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    return ok ? 0 : 1;
}

static int selftest(void)
{
    int bad = 0;
    wchar_t path[MAX_PATH];
    doc_create();
    g_color = RGB(200, 30, 40);
    g_pen = 4;
    draw_shape(g_doc, T_RECT, (POINT){100, 100}, (POINT){300, 200});
    bad += check(GetPixel(g_doc, 100, 150) == g_color, "rectangle edge drawn");
    bad += check(GetPixel(g_doc, 200, 150) == RGB(255, 255, 255), "rectangle hollow");
    g_color = RGB(20, 90, 200);
    flood(200, 150);
    bad += check(GetPixel(g_doc, 200, 150) == g_color && GetPixel(g_doc, 50, 50) == RGB(255, 255, 255),
                 "flood fill stays inside the rectangle");
    undo_push();
    doc_clear();
    undo_pop();
    bad += check(GetPixel(g_doc, 200, 150) == g_color, "undo restores the picture");
    GetTempPathW(MAX_PATH, path);
    wcscat(path, L"ub-paint-selftest.bmp");
    bad += check(save_bmp(path), "BMP written");
    doc_clear();
    bad += check(load_bmp(path) && GetPixel(g_doc, 200, 150) == g_color
                 && GetPixel(g_doc, 101, 150) == RGB(200, 30, 40),
                 "BMP read back pixel for pixel");
    DeleteFileW(path);
    printf(bad ? "selftest FAILED\n" : "selftest ok\n");
    return bad;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show)
{
    (void)prev;
    g_inst = inst;
    if (strstr(cmd, "--selftest"))
        return selftest();
    INITCOMMONCONTROLSEX icc = {sizeof icc, ICC_BAR_CLASSES | ICC_STANDARD_CLASSES};
    InitCommonControlsEx(&icc);
    doc_create();

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = canvas_proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(NULL, IDC_CROSS);
    wc.lpszClassName = L"UbPaintCanvas";
    RegisterClassW(&wc);
    wc.lpfnWndProc = main_proc;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = L"UbPaintMain";
    RegisterClassW(&wc);

    double s = GetDpiForSystem() / 96.0;
    CreateWindowExW(0, L"UbPaintMain", L"C · paint on plain Win32 — Unified Base Windows demo",
                    WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN, CW_USEDEFAULT, CW_USEDEFAULT,
                    (int)(1000 * s), (int)(700 * s), NULL, NULL, inst, NULL);
    ShowWindow(g_main, show);

    ACCEL keys[] = {
        {FVIRTKEY | FCONTROL, 'N', ID_NEW}, {FVIRTKEY | FCONTROL, 'O', ID_OPEN},
        {FVIRTKEY | FCONTROL, 'S', ID_SAVE}, {FVIRTKEY | FCONTROL, 'Z', ID_UNDO},
        {FVIRTKEY | FCONTROL, 'C', ID_COPY}, {FVIRTKEY | FCONTROL, 'V', ID_PASTE},
        {FVIRTKEY, 'P', ID_TOOL0 + T_PEN}, {FVIRTKEY, 'L', ID_TOOL0 + T_LINE},
        {FVIRTKEY, 'R', ID_TOOL0 + T_RECT}, {FVIRTKEY, 'E', ID_TOOL0 + T_ELLIPSE},
        {FVIRTKEY, 'F', ID_TOOL0 + T_FILL}, {FVIRTKEY, 'X', ID_TOOL0 + T_ERASER},
        {FVIRTKEY, VK_OEM_6, ID_WIDER}, {FVIRTKEY, VK_OEM_4, ID_THINNER},
    };
    HACCEL acc = CreateAcceleratorTableW(keys, sizeof keys / sizeof keys[0]);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (!TranslateAcceleratorW(g_main, acc, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    return 0;
}
