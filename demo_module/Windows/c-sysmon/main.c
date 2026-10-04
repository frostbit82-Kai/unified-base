/* C — Unified Base Windows demo #2: a process monitor on plain Win32.
 *
 * A small Task Manager: every process with its CPU %, memory, threads and
 * parent, refreshed each second; sort by any column, filter by name,
 * double-click to show the program in Explorer. Above it, CPU and memory
 * over the last two minutes.
 *
 *   Toolhelp32      the process list (CreateToolhelp32Snapshot)
 *   GetProcessTimes CPU per process: kernel+user time deltas over the wall
 *                   clock and the processor count
 *   psapi           working set (K32GetProcessMemoryInfo)
 *   ListView        *virtual* (LVS_OWNERDATA): the control keeps no rows;
 *                   it asks for each visible cell as it paints
 *   GDI             the graphs, double-buffered
 *   Shell           ShellExecute explorer /select,"path"
 *
 * `sysmon.exe --selftest` samples twice and checks the numbers and sorting.
 * Build: make (zig cc, any OS).
 */
#define UNICODE
#define _UNICODE
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <commctrl.h>
#include <psapi.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <tlhelp32.h>
#include <uxtheme.h>
#include <wchar.h>

#define MAX_PROCS 4096
#define HISTORY 120
enum { C_NAME, C_PID, C_CPU, C_MEM, C_THREADS, C_PARENT, C_COUNT };
enum { ID_FILTER = 100, ID_EXPLORE, ID_LIST, ID_COUNT };
static const wchar_t *COLS[C_COUNT] = {L"Process", L"PID", L"CPU", L"Memory", L"Threads", L"Parent"};
static const int COL_W[C_COUNT] = {220, 70, 70, 100, 70, 70};

typedef struct {
    DWORD pid, ppid, threads;
    wchar_t name[MAX_PATH];
    SIZE_T ws;
    ULONGLONG cpu_time; /* kernel + user, 100 ns units */
    double cpu;
} Proc;

static Proc g_procs[MAX_PROCS], g_prev[MAX_PROCS];
static int g_nprocs, g_nprev;
static int g_view[MAX_PROCS], g_nview; /* filtered + sorted indexes */
static int g_sort = C_CPU, g_desc = 1;
static wchar_t g_filter[64];
static ULONGLONG g_last_tick;
static ULONGLONG g_sys_idle, g_sys_total;
static double g_cpu_hist[HISTORY], g_mem_hist[HISTORY];
static double g_cpu_now;
static MEMORYSTATUSEX g_mem;
static int g_ncpu;

static HINSTANCE g_inst;
static HWND g_main, g_list, g_graph, g_status, g_filter_box, g_count;
static HFONT g_font;

/* -- sampling ------------------------------------------------------------- */
static ULONGLONG ft(FILETIME f) { return ((ULONGLONG)f.dwHighDateTime << 32) | f.dwLowDateTime; }

static void sample(void)
{
    ULONGLONG now = GetTickCount64();
    double wall = (now - g_last_tick) * 10000.0; /* ms -> 100 ns */
    memcpy(g_prev, g_procs, sizeof(Proc) * g_nprocs);
    g_nprev = g_nprocs;
    g_nprocs = 0;

    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe = {sizeof pe};
    for (BOOL ok = Process32FirstW(snap, &pe); ok && g_nprocs < MAX_PROCS; ok = Process32NextW(snap, &pe)) {
        Proc *p = &g_procs[g_nprocs++];
        memset(p, 0, sizeof *p);
        p->pid = pe.th32ProcessID;
        p->ppid = pe.th32ParentProcessID;
        p->threads = pe.cntThreads;
        wcsncpy(p->name, pe.szExeFile, MAX_PATH - 1);
        /* Limited access is all Windows grants for most processes that
         * aren't ours; it is enough for times and memory. Protected ones
         * (System, csrss ...) refuse even that and show blanks. */
        HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, p->pid);
        if (h) {
            FILETIME c, e, k, u;
            PROCESS_MEMORY_COUNTERS pmc = {sizeof pmc};
            if (GetProcessTimes(h, &c, &e, &k, &u))
                p->cpu_time = ft(k) + ft(u);
            if (K32GetProcessMemoryInfo(h, &pmc, sizeof pmc))
                p->ws = pmc.WorkingSetSize;
            CloseHandle(h);
        }
        for (int i = 0; i < g_nprev; i++) {
            if (g_prev[i].pid == p->pid && wall > 0 && p->cpu_time >= g_prev[i].cpu_time) {
                p->cpu = 100.0 * (p->cpu_time - g_prev[i].cpu_time) / (wall * g_ncpu);
                break;
            }
        }
    }
    CloseHandle(snap);
    g_last_tick = now;

    /* Whole machine: GetSystemTimes. Kernel time includes idle time. */
    FILETIME idle, kern, user;
    GetSystemTimes(&idle, &kern, &user);
    ULONGLONG i2 = ft(idle), t2 = ft(kern) + ft(user);
    if (g_sys_total && t2 > g_sys_total)
        g_cpu_now = 100.0 * (1.0 - (double)(i2 - g_sys_idle) / (t2 - g_sys_total));
    g_sys_idle = i2;
    g_sys_total = t2;
    g_mem.dwLength = sizeof g_mem;
    GlobalMemoryStatusEx(&g_mem);
    memmove(g_cpu_hist, g_cpu_hist + 1, sizeof(double) * (HISTORY - 1));
    memmove(g_mem_hist, g_mem_hist + 1, sizeof(double) * (HISTORY - 1));
    g_cpu_hist[HISTORY - 1] = g_cpu_now;
    g_mem_hist[HISTORY - 1] = g_mem.dwMemoryLoad;
    static int first = 1;
    if (first) { /* no history yet: start the memory line level, not at 0 */
        first = 0;
        for (int i = 0; i < HISTORY; i++)
            g_mem_hist[i] = g_mem.dwMemoryLoad;
    }
}

static int cmp(const void *a, const void *b)
{
    const Proc *x = &g_procs[*(const int *)a], *y = &g_procs[*(const int *)b];
    int r = 0;
    switch (g_sort) {
    case C_NAME: r = _wcsicmp(x->name, y->name); break;
    case C_PID: r = (x->pid > y->pid) - (x->pid < y->pid); break;
    case C_CPU: r = (x->cpu > y->cpu) - (x->cpu < y->cpu); break;
    case C_MEM: r = (x->ws > y->ws) - (x->ws < y->ws); break;
    case C_THREADS: r = (x->threads > y->threads) - (x->threads < y->threads); break;
    case C_PARENT: r = (x->ppid > y->ppid) - (x->ppid < y->ppid); break;
    }
    if (r != 0)
        return g_desc ? -r : r;
    /* Ties by name, A to Z whatever the direction: rows don't shuffle. */
    r = _wcsicmp(x->name, y->name);
    return r ? r : (x->pid > y->pid) - (x->pid < y->pid);
}

static void build_view(void)
{
    g_nview = 0;
    for (int i = 0; i < g_nprocs; i++) {
        if (!g_filter[0]) {
            g_view[g_nview++] = i;
            continue;
        }
        wchar_t low[MAX_PATH];
        wcscpy(low, g_procs[i].name);
        _wcslwr(low);
        if (wcsstr(low, g_filter))
            g_view[g_nview++] = i;
    }
    qsort(g_view, g_nview, sizeof g_view[0], cmp);
}

/* -- UI --------------------------------------------------------------------- */
static void fmt_bytes(wchar_t *s, int cap, double n)
{
    const wchar_t *u[] = {L"B", L"KB", L"MB", L"GB"};
    int i = 0;
    while (n >= 1024 && i < 3) {
        n /= 1024;
        i++;
    }
    swprintf(s, cap, i ? L"%.1f %ls" : L"%.0f %ls", n, u[i]);
}

static DWORD selected_pid(void)
{
    int i = (int)SendMessageW(g_list, LVM_GETNEXTITEM, (WPARAM)-1, LVNI_SELECTED);
    return i >= 0 && i < g_nview ? g_procs[g_view[i]].pid : 0;
}

/* Re-sample, re-sort, and keep the selection on the same *process*: in a
 * virtual list the control only knows row numbers, which change. */
static void refresh(void)
{
    DWORD keep = selected_pid();
    sample();
    build_view();
    SendMessageW(g_list, LVM_SETITEMCOUNT, g_nview, LVSICF_NOSCROLL | LVSICF_NOINVALIDATEALL);
    LVITEMW clear = {0};
    clear.stateMask = LVIS_SELECTED | LVIS_FOCUSED;
    SendMessageW(g_list, LVM_SETITEMSTATE, (WPARAM)-1, (LPARAM)&clear);
    for (int i = 0; keep && i < g_nview; i++) {
        if (g_procs[g_view[i]].pid == keep) {
            LVITEMW sel = {0};
            sel.state = sel.stateMask = LVIS_SELECTED | LVIS_FOCUSED;
            SendMessageW(g_list, LVM_SETITEMSTATE, i, (LPARAM)&sel);
        }
    }
    InvalidateRect(g_list, NULL, FALSE);
    InvalidateRect(g_graph, NULL, FALSE);

    DWORD threads = 0;
    for (int i = 0; i < g_nprocs; i++)
        threads += g_procs[i].threads;
    wchar_t s[96], a[32], b[32];
    swprintf(s, 96, L"%d processes", g_nprocs);
    SendMessageW(g_status, SB_SETTEXTW, 0, (LPARAM)s);
    swprintf(s, 96, L"%lu threads", threads);
    SendMessageW(g_status, SB_SETTEXTW, 1, (LPARAM)s);
    swprintf(s, 96, L"CPU %.0f %% of %d", g_cpu_now, g_ncpu);
    SendMessageW(g_status, SB_SETTEXTW, 2, (LPARAM)s);
    fmt_bytes(a, 32, (double)(g_mem.ullTotalPhys - g_mem.ullAvailPhys));
    fmt_bytes(b, 32, (double)g_mem.ullTotalPhys);
    swprintf(s, 96, L"memory %ls of %ls", a, b);
    SendMessageW(g_status, SB_SETTEXTW, 3, (LPARAM)s);
    ULONGLONG up = GetTickCount64() / 1000;
    swprintf(s, 96, L"up %llud %lluh %02llum", up / 86400, up / 3600 % 24, up / 60 % 60);
    SendMessageW(g_status, SB_SETTEXTW, 4, (LPARAM)s);
    swprintf(s, 96, g_filter[0] ? L"%d match" : L"", g_nview);
    SetWindowTextW(g_count, s);
}

/* ComCtl 6 draws the sort arrow in the header, if asked per column. */
static void sort_arrows(void)
{
    HWND hdr = (HWND)SendMessageW(g_list, LVM_GETHEADER, 0, 0);
    for (int c = 0; c < C_COUNT; c++) {
        HDITEMW it = {HDI_FORMAT};
        SendMessageW(hdr, HDM_GETITEMW, c, (LPARAM)&it);
        it.fmt &= ~(HDF_SORTUP | HDF_SORTDOWN);
        if (c == g_sort)
            it.fmt |= g_desc ? HDF_SORTDOWN : HDF_SORTUP;
        SendMessageW(hdr, HDM_SETITEMW, c, (LPARAM)&it);
    }
}

static void explore(void)
{
    DWORD pid = selected_pid();
    HANDLE h = pid ? OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid) : NULL;
    if (!h)
        return;
    wchar_t path[MAX_PATH], args[MAX_PATH + 16];
    DWORD n = MAX_PATH;
    if (QueryFullProcessImageNameW(h, 0, path, &n)) {
        swprintf(args, MAX_PATH + 16, L"/select,\"%ls\"", path);
        ShellExecuteW(g_main, L"open", L"explorer.exe", args, NULL, SW_SHOWNORMAL);
    }
    CloseHandle(h);
}

static LRESULT CALLBACK graph_proc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_ERASEBKGND)
        return 1;
    if (msg != WM_PAINT)
        return DefWindowProcW(h, msg, wp, lp);
    PAINTSTRUCT ps;
    RECT rc;
    HDC dc = BeginPaint(h, &ps);
    GetClientRect(h, &rc);
    HDC m = CreateCompatibleDC(dc);
    HBITMAP b = CreateCompatibleBitmap(dc, rc.right, rc.bottom);
    HGDIOBJ ob = SelectObject(m, b);
    HBRUSH bg = CreateSolidBrush(RGB(0x0d, 0x11, 0x17));
    FillRect(m, &rc, bg);
    DeleteObject(bg);
    double s = GetDpiForWindow(h) / 96.0;
    int w = rc.right, gh = rc.bottom;
    HPEN grid = CreatePen(PS_SOLID, 1, RGB(0x21, 0x26, 0x2d));
    HGDIOBJ op = SelectObject(m, grid);
    for (int q = 1; q < 4; q++) {
        MoveToEx(m, 0, gh * q / 4, NULL);
        LineTo(m, w, gh * q / 4);
    }
    /* CPU as a filled area, memory as a line over it. */
    POINT pts[HISTORY + 2];
    for (int i = 0; i < HISTORY; i++)
        pts[i] = (POINT){w * i / (HISTORY - 1), gh - (int)(gh * g_cpu_hist[i] / 100)};
    pts[HISTORY] = (POINT){w, gh};
    pts[HISTORY + 1] = (POINT){0, gh};
    HBRUSH fill = CreateSolidBrush(RGB(0x1a, 0x5f, 0x2c));
    HPEN edge = CreatePen(PS_SOLID, (int)(2 * s), RGB(0x2e, 0xa0, 0x43));
    SelectObject(m, fill);
    SelectObject(m, GetStockObject(NULL_PEN));
    Polygon(m, pts, HISTORY + 2);
    SelectObject(m, edge);
    Polyline(m, pts, HISTORY);
    HPEN mem = CreatePen(PS_SOLID, (int)(2 * s), RGB(0x58, 0xa6, 0xff));
    SelectObject(m, mem);
    for (int i = 0; i < HISTORY; i++)
        pts[i] = (POINT){w * i / (HISTORY - 1), gh - (int)(gh * g_mem_hist[i] / 100)};
    Polyline(m, pts, HISTORY);
    wchar_t t[96];
    swprintf(t, 96, L"  CPU %.0f %%   memory %lu %%   — last 2 minutes", g_cpu_now, g_mem.dwMemoryLoad);
    SetBkMode(m, TRANSPARENT);
    SetTextColor(m, RGB(0xe6, 0xed, 0xf3));
    HGDIOBJ of = SelectObject(m, g_font);
    TextOutW(m, (int)(4 * s), (int)(4 * s), t, (int)wcslen(t));
    SelectObject(m, of);
    BitBlt(dc, 0, 0, w, gh, m, 0, 0, SRCCOPY);
    SelectObject(m, op);
    SelectObject(m, ob);
    DeleteObject(grid);
    DeleteObject(fill);
    DeleteObject(edge);
    DeleteObject(mem);
    DeleteObject(b);
    DeleteDC(m);
    EndPaint(h, &ps);
    return 0;
}

static void layout(void)
{
    RECT rc, sb;
    double s = GetDpiForWindow(g_main) / 96.0;
    int m = (int)(8 * s), h = (int)(26 * s), y = m;
    GetClientRect(g_main, &rc);
    SendMessageW(g_status, WM_SIZE, 0, 0);
    GetWindowRect(g_status, &sb);
    MoveWindow(g_filter_box, m, y, (int)(220 * s), h, TRUE);
    MoveWindow(GetDlgItem(g_main, ID_EXPLORE), m + (int)(228 * s), y, (int)(130 * s), h, TRUE);
    MoveWindow(g_count, m + (int)(366 * s), y, (int)(120 * s), h, TRUE);
    y += h + m;
    int gh = (int)(110 * s);
    MoveWindow(g_graph, m, y, rc.right - 2 * m, gh, TRUE);
    y += gh + m;
    MoveWindow(g_list, m, y, rc.right - 2 * m, rc.bottom - y - (sb.bottom - sb.top) - m / 2, TRUE);
    int parts[5] = {(int)(110 * s), (int)(220 * s), (int)(340 * s), (int)(530 * s), -1};
    SendMessageW(g_status, SB_SETPARTS, 5, (LPARAM)parts);
}

static void create_controls(HWND h)
{
    double s = GetDpiForWindow(h) / 96.0;
    g_font = CreateFontW(-(int)(12 * s), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                         CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_filter_box = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
                                   0, 0, 10, 10, h, (HMENU)ID_FILTER, g_inst, NULL);
    SendMessageW(g_filter_box, EM_SETCUEBANNER, TRUE, (LPARAM)L"filter by name");
    CreateWindowExW(0, L"BUTTON", L"Show in Explorer", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                    0, 0, 10, 10, h, (HMENU)ID_EXPLORE, g_inst, NULL);
    g_count = CreateWindowExW(0, L"STATIC", L"", WS_CHILD | WS_VISIBLE | SS_CENTERIMAGE,
                              0, 0, 10, 10, h, (HMENU)ID_COUNT, g_inst, NULL);
    g_graph = CreateWindowExW(0, L"UbSysGraph", NULL, WS_CHILD | WS_VISIBLE, 0, 0, 10, 10, h, NULL, g_inst, NULL);
    g_list = CreateWindowExW(0, WC_LISTVIEWW, NULL,
                             WS_CHILD | WS_VISIBLE | WS_BORDER | LVS_REPORT | LVS_OWNERDATA | LVS_SINGLESEL
                             | LVS_SHOWSELALWAYS,
                             0, 0, 10, 10, h, (HMENU)ID_LIST, g_inst, NULL);
    /* The Explorer theme: the list looks like File Explorer's. */
    SetWindowTheme(g_list, L"Explorer", NULL);
    SendMessageW(g_list, LVM_SETEXTENDEDLISTVIEWSTYLE, 0,
                 LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_HEADERDRAGDROP);
    for (int c = 0; c < C_COUNT; c++) {
        LVCOLUMNW col = {LVCF_TEXT | LVCF_WIDTH | LVCF_FMT};
        col.pszText = (LPWSTR)COLS[c];
        col.cx = (int)(COL_W[c] * s);
        col.fmt = c == C_NAME ? LVCFMT_LEFT : LVCFMT_RIGHT;
        SendMessageW(g_list, LVM_INSERTCOLUMNW, c, (LPARAM)&col);
    }
    g_status = CreateWindowExW(0, STATUSCLASSNAMEW, NULL, WS_CHILD | WS_VISIBLE, 0, 0, 0, 0, h, NULL, g_inst, NULL);
    HWND all[] = {g_filter_box, GetDlgItem(h, ID_EXPLORE), g_count, g_list, g_status};
    for (size_t i = 0; i < sizeof all / sizeof all[0]; i++)
        SendMessageW(all[i], WM_SETFONT, (WPARAM)g_font, TRUE);
}

static LRESULT CALLBACK main_proc(HWND h, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CREATE:
        g_main = h;
        create_controls(h);
        sort_arrows();
        refresh();
        SetTimer(h, 1, 1000, NULL);
        return 0;
    case WM_SIZE:
        layout();
        refresh();
        return 0;
    case WM_TIMER:
        refresh();
        return 0;
    case WM_COMMAND:
        if (LOWORD(wp) == ID_EXPLORE && HIWORD(wp) == BN_CLICKED)
            explore();
        if (LOWORD(wp) == ID_FILTER && HIWORD(wp) == EN_CHANGE) {
            GetWindowTextW(g_filter_box, g_filter, 64);
            _wcslwr(g_filter);
            refresh();
        }
        return 0;
    case WM_NOTIFY: {
        NMHDR *n = (NMHDR *)lp;
        if (n->hwndFrom != g_list)
            break;
        if (n->code == LVN_GETDISPINFOW) {
            /* The virtual list asks for one cell at a time, only for the
             * rows on screen: 300 processes cost 30 rows of formatting. */
            LVITEMW *it = &((NMLVDISPINFOW *)lp)->item;
            if (!(it->mask & LVIF_TEXT) || it->iItem >= g_nview)
                return 0;
            Proc *p = &g_procs[g_view[it->iItem]];
            switch (it->iSubItem) {
            case C_NAME: wcsncpy(it->pszText, p->name, it->cchTextMax - 1); break;
            case C_PID: swprintf(it->pszText, it->cchTextMax, L"%lu", p->pid); break;
            case C_CPU: swprintf(it->pszText, it->cchTextMax, p->cpu >= 0.05 ? L"%.1f %%" : L"", p->cpu); break;
            case C_MEM:
                if (p->ws)
                    fmt_bytes(it->pszText, it->cchTextMax, (double)p->ws);
                else
                    it->pszText[0] = 0;
                break;
            case C_THREADS: swprintf(it->pszText, it->cchTextMax, L"%lu", p->threads); break;
            case C_PARENT: swprintf(it->pszText, it->cchTextMax, L"%lu", p->ppid); break;
            }
            return 0;
        }
        if (n->code == LVN_COLUMNCLICK) {
            int c = ((NMLISTVIEW *)lp)->iSubItem;
            g_desc = c == g_sort ? !g_desc : c != C_NAME;  /* numbers: biggest first */
            g_sort = c;
            sort_arrows();
            refresh();
            return 0;
        }
        if (n->code == NM_DBLCLK) {
            explore();
            return 0;
        }
        break;
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

/* -- self-test ------------------------------------------------------------------ */
static int check(BOOL ok, const char *what)
{
    printf("%s %s\n", ok ? "ok  " : "FAIL", what);
    return ok ? 0 : 1;
}

static int selftest(void)
{
    int bad = 0;
    g_last_tick = GetTickCount64();
    sample();
    Sleep(500);
    sample();
    build_view();
    char buf[96];
    snprintf(buf, sizeof buf, "%d processes", g_nprocs);
    bad += check(g_nprocs > 20, buf);
    int me = -1;
    for (int i = 0; i < g_nprocs; i++)
        if (g_procs[i].pid == GetCurrentProcessId())
            me = i;
    bad += check(me >= 0 && wcsstr(g_procs[me].name, L"sysmon") != NULL, "finds itself");
    bad += check(me >= 0 && g_procs[me].ws > 1024 * 1024, "own working set > 1 MB");
    double total = 0;
    for (int i = 0; i < g_nprocs; i++)
        total += g_procs[i].cpu;
    snprintf(buf, sizeof buf, "per-process CPU sums to %.0f %% (machine %.0f %%)", total, g_cpu_now);
    bad += check(total >= 0 && total <= 105 && g_cpu_now >= 0 && g_cpu_now <= 100, buf);
    g_sort = C_MEM;
    g_desc = 1;
    build_view();
    int sorted = 1;
    for (int i = 1; i < g_nview; i++)
        sorted &= g_procs[g_view[i - 1]].ws >= g_procs[g_view[i]].ws;
    bad += check(sorted, "sort by memory, biggest first");
    wcscpy(g_filter, L"sysmon");
    build_view();
    bad += check(g_nview >= 1 && g_nview < g_nprocs, "filter narrows the list");
    printf(bad ? "selftest FAILED\n" : "selftest ok\n");
    return bad;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show)
{
    (void)prev;
    g_inst = inst;
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    g_ncpu = (int)si.dwNumberOfProcessors;
    if (strstr(cmd, "--selftest"))
        return selftest();
    INITCOMMONCONTROLSEX icc = {sizeof icc, ICC_LISTVIEW_CLASSES | ICC_BAR_CLASSES};
    InitCommonControlsEx(&icc);
    g_last_tick = GetTickCount64();

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = graph_proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.lpszClassName = L"UbSysGraph";
    RegisterClassW(&wc);
    wc.lpfnWndProc = main_proc;
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = L"UbSysMon";
    RegisterClassW(&wc);

    double s = GetDpiForSystem() / 96.0;
    CreateWindowExW(0, L"UbSysMon", L"C · process monitor on plain Win32 — Unified Base Windows demo",
                    WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN, CW_USEDEFAULT, CW_USEDEFAULT,
                    (int)(860 * s), (int)(640 * s), NULL, NULL, inst, NULL);
    ShowWindow(g_main, show);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}
