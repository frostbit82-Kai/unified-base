# Java — Unified Base Windows demo #2: Win32 through the FFM API

A live map of your desktop — every top-level window drawn to scale and in
z-order on the virtual screen, the mouse cursor moving across it — plus a
table of the windows and a status line of memory, power, uptime and DPI.
Hover a window for its process and class; click one (map or table) and
**Flash on taskbar** makes Windows flash it.

All of it comes from `user32`, `kernel32` and `dwmapi`, called from plain
Java with the **Foreign Function and Memory API** (`java.lang.foreign`,
final in Java 22).

## Demonstrates
- **No JNI, no JNA, no C.** A native function is a symbol from a
  `SymbolLookup` plus a `FunctionDescriptor`; `Linker.downcallHandle` turns
  that into a `MethodHandle`.
- **Upcalls.** `EnumWindows` calls back into Java through an upcall stub —
  a C function pointer whose body is a static Java method. An exception
  escaping one kills the JVM outright, so the callback only appends.
- **Structs as layouts.** `RECT`, `POINT`, `MEMORYSTATUSEX`,
  `SYSTEM_POWER_STATUS` and `FLASHWINFO` are `MemoryLayout`s; Java computes
  each field's offset — including the 4 bytes of padding C puts before
  `FLASHWINFO`'s 8-byte-aligned `HWND` (the self-test checks it is 32
  bytes).
- **Arenas for lifetime.** Each call's buffers live in a confined arena
  closed on the spot; the DLLs and the callback stub live in the global one.
- **`invokeExact` is exact.** A boxed `Integer` where the descriptor says
  `int` throws at run time — one trap from writing this, noted in the code.
- **Windows trivia:** strings are UTF-16 (`WCHAR`); Store apps leave
  windows "visible" that DWM has *cloaked*, filtered out with
  `DwmGetWindowAttribute`.
- **Native access, declared.** The jar's manifest says
  `Enable-Native-Access: ALL-UNNAMED`; without it Java 24+ warns on the
  first native call.

Something to notice while it is embedded in Unified Base: its own window is
missing from the map. The launcher adopted it, making it a child window.

## Dependencies
- JDK 22+ (FFM is final from 22): `winget install -e --id EclipseAdoptium.Temurin.25.JDK`.
- Maven on PATH.

## Run
Unified Base builds and runs this automatically. Windows-only: on Linux it
says so and exits.

Manual equivalent:

```
mvn -q -DskipTests package && java -jar target/ub-java-ffm.jar
```

Check, no window: `java -jar target/ub-java-ffm.jar --selftest`

## Files
- `pom.xml` — Java 22 release target; the native-access manifest entry
- `src/main/java/com/example/Win32.java` — every declaration and call
- `src/main/java/com/example/App.java` — the map, the table, and `--selftest`
