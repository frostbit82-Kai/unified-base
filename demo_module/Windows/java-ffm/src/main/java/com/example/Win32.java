package com.example;

import static java.lang.foreign.ValueLayout.ADDRESS;
import static java.lang.foreign.ValueLayout.JAVA_BYTE;
import static java.lang.foreign.ValueLayout.JAVA_CHAR;
import static java.lang.foreign.ValueLayout.JAVA_INT;
import static java.lang.foreign.ValueLayout.JAVA_LONG;

import java.lang.foreign.Arena;
import java.lang.foreign.FunctionDescriptor;
import java.lang.foreign.Linker;
import java.lang.foreign.MemoryLayout;
import java.lang.foreign.MemoryLayout.PathElement;
import java.lang.foreign.MemorySegment;
import java.lang.foreign.StructLayout;
import java.lang.foreign.SymbolLookup;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Every Win32 call this demo makes, declared with the Foreign Function and
 * Memory API (java.lang.foreign, final in Java 22). No JNI, no JNA, no C:
 * a function is a symbol looked up in a DLL plus a FunctionDescriptor, and a
 * struct is a MemoryLayout whose field offsets Java computes, padding and
 * all.
 */
final class Win32 {
    private Win32() { }

    /** One top-level window, as the map and the table show it. */
    record Win(long hwnd, String title, String cls, int pid, String exe,
               int x, int y, int w, int h) { }

    private static final Linker LINKER = Linker.nativeLinker();
    private static final Arena LIBS = Arena.global();      // DLLs stay loaded
    private static final SymbolLookup USER32 = SymbolLookup.libraryLookup("user32", LIBS);
    private static final SymbolLookup KERNEL32 = SymbolLookup.libraryLookup("kernel32", LIBS);
    private static final SymbolLookup DWMAPI = SymbolLookup.libraryLookup("dwmapi", LIBS);

    private static MethodHandle fn(SymbolLookup lib, String name, FunctionDescriptor fd) {
        return LINKER.downcallHandle(lib.find(name).orElseThrow(), fd);
    }

    // -- structs: Java lays them out, C's alignment rules included ----------
    static final StructLayout RECT = MemoryLayout.structLayout(
            JAVA_INT.withName("left"), JAVA_INT.withName("top"),
            JAVA_INT.withName("right"), JAVA_INT.withName("bottom"));
    static final StructLayout POINT = MemoryLayout.structLayout(
            JAVA_INT.withName("x"), JAVA_INT.withName("y"));
    static final StructLayout MEMORYSTATUSEX = MemoryLayout.structLayout(
            JAVA_INT.withName("dwLength"), JAVA_INT.withName("dwMemoryLoad"),
            JAVA_LONG.withName("ullTotalPhys"), JAVA_LONG.withName("ullAvailPhys"),
            JAVA_LONG.withName("ullTotalPageFile"), JAVA_LONG.withName("ullAvailPageFile"),
            JAVA_LONG.withName("ullTotalVirtual"), JAVA_LONG.withName("ullAvailVirtual"),
            JAVA_LONG.withName("ullAvailExtendedVirtual"));
    static final StructLayout SYSTEM_POWER_STATUS = MemoryLayout.structLayout(
            JAVA_BYTE.withName("ACLineStatus"), JAVA_BYTE.withName("BatteryFlag"),
            JAVA_BYTE.withName("BatteryLifePercent"), JAVA_BYTE.withName("SystemStatusFlag"),
            JAVA_INT.withName("BatteryLifeTime"), JAVA_INT.withName("BatteryFullLifeTime"));
    /** cbSize, then 4 bytes of padding C inserts so the HWND is 8-aligned. */
    static final StructLayout FLASHWINFO = MemoryLayout.structLayout(
            JAVA_INT.withName("cbSize"), MemoryLayout.paddingLayout(4),
            ADDRESS.withName("hwnd"), JAVA_INT.withName("dwFlags"),
            JAVA_INT.withName("uCount"), JAVA_INT.withName("dwTimeout"),
            MemoryLayout.paddingLayout(4));

    static long off(StructLayout s, String field) {
        return s.byteOffset(PathElement.groupElement(field));
    }

    // -- functions -----------------------------------------------------------
    private static final MethodHandle EnumWindows = fn(USER32, "EnumWindows",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_LONG));
    private static final MethodHandle IsWindowVisible = fn(USER32, "IsWindowVisible",
            FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle IsIconic = fn(USER32, "IsIconic",
            FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle GetWindow = fn(USER32, "GetWindow",
            FunctionDescriptor.of(ADDRESS, ADDRESS, JAVA_INT));
    private static final MethodHandle GetWindowTextW = fn(USER32, "GetWindowTextW",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, JAVA_INT));
    private static final MethodHandle GetClassNameW = fn(USER32, "GetClassNameW",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS, JAVA_INT));
    private static final MethodHandle GetWindowRect = fn(USER32, "GetWindowRect",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS));
    private static final MethodHandle GetWindowThreadProcessId = fn(USER32,
            "GetWindowThreadProcessId", FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS));
    private static final MethodHandle FlashWindowEx = fn(USER32, "FlashWindowEx",
            FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle MessageBeep = fn(USER32, "MessageBeep",
            FunctionDescriptor.of(JAVA_INT, JAVA_INT));
    private static final MethodHandle GetCursorPos = fn(USER32, "GetCursorPos",
            FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle GetSystemMetrics = fn(USER32, "GetSystemMetrics",
            FunctionDescriptor.of(JAVA_INT, JAVA_INT));
    private static final MethodHandle GetDpiForSystem = fn(USER32, "GetDpiForSystem",
            FunctionDescriptor.of(JAVA_INT));
    private static final MethodHandle GlobalMemoryStatusEx = fn(KERNEL32,
            "GlobalMemoryStatusEx", FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle GetSystemPowerStatus = fn(KERNEL32,
            "GetSystemPowerStatus", FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle GetTickCount64 = fn(KERNEL32, "GetTickCount64",
            FunctionDescriptor.of(JAVA_LONG));
    private static final MethodHandle GetComputerNameW = fn(KERNEL32, "GetComputerNameW",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, ADDRESS));
    private static final MethodHandle OpenProcess = fn(KERNEL32, "OpenProcess",
            FunctionDescriptor.of(ADDRESS, JAVA_INT, JAVA_INT, JAVA_INT));
    private static final MethodHandle QueryFullProcessImageNameW = fn(KERNEL32,
            "QueryFullProcessImageNameW",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_INT, ADDRESS, ADDRESS));
    private static final MethodHandle CloseHandle = fn(KERNEL32, "CloseHandle",
            FunctionDescriptor.of(JAVA_INT, ADDRESS));
    private static final MethodHandle DwmGetWindowAttribute = fn(DWMAPI,
            "DwmGetWindowAttribute",
            FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_INT, ADDRESS, JAVA_INT));

    // -- EnumWindows calls back into Java: an upcall stub ----------------------
    private static List<MemorySegment> found;       // filled during the call
    private static final MemorySegment ENUM_PROC;

    static {
        try {
            MethodHandle cb = MethodHandles.lookup().findStatic(Win32.class, "onWindow",
                    MethodType.methodType(int.class, MemorySegment.class, long.class));
            ENUM_PROC = LINKER.upcallStub(cb,
                    FunctionDescriptor.of(JAVA_INT, ADDRESS, JAVA_LONG), LIBS);
        } catch (ReflectiveOperationException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    /** WNDENUMPROC. An exception escaping an upcall kills the JVM outright,
     *  so this does nothing that can throw. */
    private static int onWindow(MemorySegment hwnd, long lparam) {
        found.add(hwnd);
        return 1;                                     // TRUE: keep enumerating
    }

    private static final int GW_OWNER = 4;
    private static final int DWMWA_CLOAKED = 14;
    private static final Map<Integer, String> EXES = new HashMap<>();

    /** Top-level windows a taskbar would show, front to back: visible,
     *  titled, unowned, not minimized, and not cloaked — Store apps leave
     *  windows "visible" that DWM hides. */
    static synchronized List<Win> windows() {
        found = new ArrayList<>();
        call(() -> (int) EnumWindows.invokeExact(ENUM_PROC, 0L));
        List<Win> out = new ArrayList<>();
        try (Arena a = Arena.ofConfined()) {
            MemorySegment text = a.allocate(JAVA_CHAR, 256);
            MemorySegment cls = a.allocate(JAVA_CHAR, 256);
            MemorySegment rect = a.allocate(RECT);
            MemorySegment pid = a.allocate(JAVA_INT);
            MemorySegment cloaked = a.allocate(JAVA_INT);
            for (MemorySegment h : found) {
                if (call(() -> (int) IsWindowVisible.invokeExact(h)) == 0
                        || call(() -> (int) IsIconic.invokeExact(h)) != 0
                        || callAddr(() -> (MemorySegment) GetWindow.invokeExact(h, GW_OWNER)) != 0) {
                    continue;
                }
                cloaked.set(JAVA_INT, 0, 0);
                call(() -> (int) DwmGetWindowAttribute.invokeExact(h, DWMWA_CLOAKED, cloaked, 4));
                int n = call(() -> (int) GetWindowTextW.invokeExact(h, text, 256));
                if (cloaked.get(JAVA_INT, 0) != 0 || n == 0) {
                    continue;
                }
                int c = call(() -> (int) GetClassNameW.invokeExact(h, cls, 256));
                call(() -> (int) GetWindowRect.invokeExact(h, rect));
                call(() -> (int) GetWindowThreadProcessId.invokeExact(h, pid));
                int l = rect.get(JAVA_INT, off(RECT, "left"));
                int t = rect.get(JAVA_INT, off(RECT, "top"));
                int p = pid.get(JAVA_INT, 0);
                out.add(new Win(h.address(), utf16(text, n), utf16(cls, c), p, exe(p), l, t,
                        rect.get(JAVA_INT, off(RECT, "right")) - l,
                        rect.get(JAVA_INT, off(RECT, "bottom")) - t));
            }
        }
        return out;
    }

    private static String exe(int pid) {
        // invokeExact matches types exactly: the boxed Integer computeIfAbsent
        // hands its lambda would fail at run time, so the int pid is used.
        return EXES.computeIfAbsent(pid, unused -> {
            MemorySegment h = callAddrSeg(() -> (MemorySegment) OpenProcess.invokeExact(0x1000, 0, pid));
            if (h.address() == 0) {
                return "?";                  // elevated or protected process
            }
            try (Arena a = Arena.ofConfined()) {
                MemorySegment buf = a.allocate(JAVA_CHAR, 1024);
                MemorySegment len = a.allocate(JAVA_INT);
                len.set(JAVA_INT, 0, 1024);
                int ok = call(() -> (int) QueryFullProcessImageNameW.invokeExact(h, 0, buf, len));
                String path = ok == 0 ? "?" : utf16(buf, len.get(JAVA_INT, 0));
                return path.substring(path.lastIndexOf('\\') + 1);
            } finally {
                call(() -> (int) CloseHandle.invokeExact(h));
            }
        });
    }

    static void flash(long hwnd) {
        try (Arena a = Arena.ofConfined()) {
            MemorySegment fi = a.allocate(FLASHWINFO);
            fi.set(JAVA_INT, off(FLASHWINFO, "cbSize"), (int) FLASHWINFO.byteSize());
            fi.set(ADDRESS, off(FLASHWINFO, "hwnd"), MemorySegment.ofAddress(hwnd));
            fi.set(JAVA_INT, off(FLASHWINFO, "dwFlags"), 3);    // FLASHW_ALL
            fi.set(JAVA_INT, off(FLASHWINFO, "uCount"), 6);
            call(() -> (int) FlashWindowEx.invokeExact(fi));
        }
    }

    static void beep() {
        call(() -> (int) MessageBeep.invokeExact(0x40));         // MB_ICONINFORMATION
    }

    static int metric(int index) {
        return call(() -> (int) GetSystemMetrics.invokeExact(index));
    }

    static int dpi() {
        return call(() -> (int) GetDpiForSystem.invokeExact());
    }

    static long uptimeMs() {
        try {
            return (long) GetTickCount64.invokeExact();
        } catch (Throwable t) {
            throw new IllegalStateException(t);
        }
    }

    static int[] cursor() {
        try (Arena a = Arena.ofConfined()) {
            MemorySegment p = a.allocate(POINT);
            call(() -> (int) GetCursorPos.invokeExact(p));
            return new int[] {p.get(JAVA_INT, off(POINT, "x")), p.get(JAVA_INT, off(POINT, "y"))};
        }
    }

    /** {load %, total bytes, available bytes}. */
    static long[] memory() {
        try (Arena a = Arena.ofConfined()) {
            MemorySegment m = a.allocate(MEMORYSTATUSEX);
            // Win32's struct versioning: say which size you passed.
            m.set(JAVA_INT, off(MEMORYSTATUSEX, "dwLength"), (int) MEMORYSTATUSEX.byteSize());
            call(() -> (int) GlobalMemoryStatusEx.invokeExact(m));
            return new long[] {m.get(JAVA_INT, off(MEMORYSTATUSEX, "dwMemoryLoad")),
                               m.get(JAVA_LONG, off(MEMORYSTATUSEX, "ullTotalPhys")),
                               m.get(JAVA_LONG, off(MEMORYSTATUSEX, "ullAvailPhys"))};
        }
    }

    static String power() {
        try (Arena a = Arena.ofConfined()) {
            MemorySegment s = a.allocate(SYSTEM_POWER_STATUS);
            call(() -> (int) GetSystemPowerStatus.invokeExact(s));
            int flag = Byte.toUnsignedInt(s.get(JAVA_BYTE, off(SYSTEM_POWER_STATUS, "BatteryFlag")));
            if (flag == 128) {
                return "mains, no battery";
            }
            int pct = Byte.toUnsignedInt(s.get(JAVA_BYTE, off(SYSTEM_POWER_STATUS, "BatteryLifePercent")));
            int ac = s.get(JAVA_BYTE, off(SYSTEM_POWER_STATUS, "ACLineStatus"));
            return pct + " % " + (ac == 1 ? "plugged in" : ac == 0 ? "on battery" : "");
        }
    }

    static String computerName() {
        try (Arena a = Arena.ofConfined()) {
            MemorySegment buf = a.allocate(JAVA_CHAR, 64);
            MemorySegment len = a.allocate(JAVA_INT);
            len.set(JAVA_INT, 0, 64);
            call(() -> (int) GetComputerNameW.invokeExact(buf, len));
            return utf16(buf, len.get(JAVA_INT, 0));
        }
    }

    /** n UTF-16 code units from a WCHAR buffer (Windows strings are UTF-16). */
    static String utf16(MemorySegment buf, int n) {
        return new String(buf.asSlice(0, 2L * n).toArray(JAVA_CHAR));
    }

    // invokeExact throws Throwable; these keep the call sites one line each.
    interface IntCall { int run() throws Throwable; }
    interface AddrCall { MemorySegment run() throws Throwable; }

    private static int call(IntCall c) {
        try {
            return c.run();
        } catch (Throwable t) {
            throw new IllegalStateException(t);
        }
    }

    private static long callAddr(AddrCall c) {
        return callAddrSeg(c).address();
    }

    private static MemorySegment callAddrSeg(AddrCall c) {
        try {
            return c.run();
        } catch (Throwable t) {
            throw new IllegalStateException(t);
        }
    }
}
