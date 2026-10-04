# Builds app.exe from main.c.
#   Linux:   cross-compiles with MinGW-w64   (sudo apt install mingw-w64)
#   Windows: MSYS2 / MinGW gcc               (winget install -e --id MSYS2.MSYS2)
# A prebuilt app.exe ships alongside, so make only runs when main.c changes.
ifeq ($(OS),Windows_NT)
CC ?= gcc
else
CC = x86_64-w64-mingw32-gcc
endif

# Prerequisites only while the exe is missing: git checks files out in any
# order, so a fresh clone often has main.c newer than the shipped exe, and
# a rebuild (never byte-identical) would dirty the tree. After editing the
# source: make -B.
app.exe: $(if $(wildcard app.exe),,main.c)
	$(CC) -O2 -s -municode -mwindows -o $@ main.c -lgdi32 -luser32 -lcomctl32

clean:
	rm -f app.exe
