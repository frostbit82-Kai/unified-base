# Builds sysmon.exe from main.c, with app.rc embedding the manifest.
# One recipe for both OSes: zig cross-compiles to Windows from anywhere
# (winget install -e --id zig.zig  /  the zig tarball on Linux).
# sysmon.exe ships prebuilt: with no compiler on the machine, the failed
# compile is ignored (the `-` prefix, only when sysmon.exe exists) and the
# launcher runs the prebuilt one.
CC = zig cc -target x86_64-windows-gnu
LIBS = -lgdi32 -luser32 -lcomctl32 -lshell32 -luxtheme

sysmon.exe: main.c app.rc app.manifest
	$(if $(wildcard $@),-)$(CC) -O2 -s -Wl,--subsystem,windows -o $@ main.c app.rc $(LIBS)

clean:
	rm -f sysmon.exe
