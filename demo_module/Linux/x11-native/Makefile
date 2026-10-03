# Builds x11-native from main.c (needs libx11-dev). The X libraries are linked
# statically so the binary needs only glibc — a stock WSL distro with no X
# packages installed can run it. A prebuilt binary ships alongside.
CC ?= cc
XLIBS = libX11.a libxcb.a libXau.a libXdmcp.a
XSTATIC = -Wl,-Bstatic -lX11 -lxcb -lXau -lXdmcp -Wl,-Bdynamic

x11-native: main.c
	$(CC) -O2 -s -o $@ main.c $(XSTATIC)

# The shipped binary: zig cc against glibc 2.31, so it also runs on older WSL
# distros (Ubuntu 22.04, Debian 12). `pip install ziglang` provides zig.
LIBDIR = /usr/lib/x86_64-linux-gnu
portable: main.c compat.c
	python3 -m ziglang cc -target x86_64-linux-gnu.2.31 -O2 -s -I/usr/include \
	  -o x11-native main.c compat.c $(addprefix $(LIBDIR)/,$(XLIBS))

clean:
	rm -f x11-native

.PHONY: portable clean
