/* Only for `make portable` (zig cc against an old glibc).
 *
 * glibc 2.38 added C23-conforming __isoc23_* variants of strtol & co., and the
 * static X libraries built on a current distro call those. Forwarding them to
 * the classic functions lets one binary run on glibc back to 2.31 — Ubuntu
 * 22.04 or Debian 12 under WSL. The variants differ only in parsing "0b"
 * prefixes, which X's display-string and locale parsing never sees.
 *
 * Never link this into a native build: with C23 headers `strtol` *is*
 * __isoc23_strtol, and these would call themselves forever.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

long __isoc23_strtol(const char *s, char **end, int base) {
    return strtol(s, end, base);
}

unsigned long __isoc23_strtoul(const char *s, char **end, int base) {
    return strtoul(s, end, base);
}

int __isoc23_sscanf(const char *s, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int n = vsscanf(s, fmt, ap);
    va_end(ap);
    return n;
}
