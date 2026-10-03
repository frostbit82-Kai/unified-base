# Builds app.exe from main.c.
#   Linux:   cross-compiles with MinGW-w64   (sudo apt install mingw-w64)
#   Windows: MSYS2 / MinGW gcc               (winget install -e --id MSYS2.MSYS2)
# A prebuilt app.exe ships alongside, so make only runs when main.c changes.
ifeq ($(OS),Windows_NT)
CC ?= gcc
else
CC = x86_64-w64-mingw32-gcc
endif

app.exe: main.c
	$(CC) -O2 -s -municode -mwindows -o $@ main.c -lgdi32 -luser32 -lcomctl32

clean:
	rm -f app.exe
