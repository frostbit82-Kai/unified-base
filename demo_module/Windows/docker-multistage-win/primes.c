/*
 * Docker — Unified Base demo #2: the payload of a scratch image.
 *
 * This binary is compiled in one build stage, verified in a second, and copied
 * alone into a `FROM scratch` final stage. It then reports on the container it
 * finds itself in: no shell, no libc, no /etc, just PID 1 and this file.
 */
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define C_RESET "\033[0m"
#define C_DIM   "\033[2m"
#define C_CYAN  "\033[36m"
#define C_GREEN "\033[32m"
#define C_YELL  "\033[33m"
#define C_BOLD  "\033[1m"

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

/* Sieve of Eratosthenes. Returns the count and fills `largest` with the top n. */
static long sieve(long limit, long *largest, int want) {
    char *flags = calloc((size_t) limit + 1, 1);
    if (!flags) {
        fprintf(stderr, "out of memory\n");
        exit(1);
    }
    long count = 0;
    for (long n = 2; n <= limit; n++) {
        if (flags[n]) continue;
        count++;
        for (long m = n * n; m <= limit && m > 0; m += n) flags[m] = 1;
    }
    int found = 0;
    for (long n = limit; n >= 2 && found < want; n--) {
        if (!flags[n]) largest[found++] = n;
    }
    free(flags);
    return count;
}

/* Run at BUILD time by the tester stage: a wrong binary never reaches the
 * final image. Known values, so a miscompile or bad flag is caught early. */
static int selftest(void) {
    long top[3];
    long c = sieve(100, top, 3);
    if (c != 25) {
        fprintf(stderr, "selftest: expected 25 primes below 100, got %ld\n", c);
        return 1;
    }
    if (top[0] != 97 || top[1] != 89 || top[2] != 83) {
        fprintf(stderr, "selftest: wrong tail primes\n");
        return 1;
    }
    printf("selftest OK: 25 primes below 100, largest 97\n");
    return 0;
}

static void row(const char *k, const char *v) {
    printf("  " C_DIM "%-22s" C_RESET " %s\n", k, v);
}

int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--selftest") == 0) return selftest();

    printf("\n" C_BOLD C_CYAN "  Docker · multi-stage build & a scratch image" C_RESET "\n");
    printf("  " C_DIM "compiled in one stage, tested in another, "
           "shipped alone in a third" C_RESET "\n\n");

    printf(C_BOLD "  Container\n" C_RESET);
    char buf[256];
    snprintf(buf, sizeof buf, "%d %s", getpid(),
             getpid() == 1 ? C_GREEN "(PID 1 — this binary IS the container)" C_RESET : "");
    row("pid", buf);

    struct stat st;
    if (stat("/proc/self/exe", &st) == 0) {
        snprintf(buf, sizeof buf, "%.1f KB (static, no libc in the image)",
                 st.st_size / 1024.0);
        row("this binary", buf);
    }
    row("shell present", access("/bin/sh", X_OK) == 0
        ? C_YELL "yes" C_RESET : C_GREEN "no — nothing to exec into" C_RESET);
    row("/etc/passwd", access("/etc/passwd", R_OK) == 0
        ? C_YELL "yes" C_RESET : C_GREEN "no — no users, no NSS" C_RESET);

    /* What is actually in the image root? On scratch: just this binary. */
    DIR *d = opendir("/");
    if (d) {
        char list[512] = "";
        struct dirent *e;
        while ((e = readdir(d))) {
            if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
            if (strlen(list) + strlen(e->d_name) + 3 >= sizeof list) break;
            if (list[0]) strcat(list, ", ");
            strcat(list, e->d_name);
        }
        closedir(d);
        row("/ contains", list[0] ? list : "(empty)");
        /* Only /primes is image content. dev, proc, sys, etc and .dockerenv are
         * mounted in by the runtime at start — every scratch container shows
         * them, and they vanish with the container. */
        row("", C_DIM "(only /primes is image content — the rest are runtime mounts)" C_RESET);
    }

    printf("\n" C_BOLD "  Work\n" C_RESET);
    const long limit = 5000000;
    long top[5];
    double t0 = now_ms();
    long count = sieve(limit, top, 5);
    double ms = now_ms() - t0;

    snprintf(buf, sizeof buf, "%ld", limit);
    row("sieve limit", buf);
    snprintf(buf, sizeof buf, C_GREEN "%ld" C_RESET, count);
    row("primes found", buf);
    snprintf(buf, sizeof buf, "%ld, %ld, %ld, %ld, %ld",
             top[4], top[3], top[2], top[1], top[0]);
    row("largest five", buf);
    snprintf(buf, sizeof buf, C_GREEN "%.0f ms" C_RESET, ms);
    row("elapsed", buf);

    printf("\n  " C_DIM "Nothing here but this file: no package manager, no shell,\n"
           "  no interpreter — so there is nothing to patch or exploit." C_RESET "\n\n");
    return 0;
}
