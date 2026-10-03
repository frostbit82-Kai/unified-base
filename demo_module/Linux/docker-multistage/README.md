# Docker — Unified Base demo #2: multi-stage build & a scratch image

Builds a static binary with gcc, verifies it in a second stage, and ships it
alone in a `FROM scratch` final image — about **66 kB total**. Running it prints
a report on the container it finds itself in.

## Demonstrates
Demo #1 is an animated ASCII dashboard. This one is about the build itself:

- **Multi-stage builds** — `builder` compiles, `tester` verifies, the final
  stage copies in one file. The toolchain (gcc, musl-dev, sources) never reaches
  the shipped image.
- **A test stage that actually runs** — `tester` is in the final stage's
  dependency chain (`COPY --from=tester`). A stage nothing copies from is
  skipped by BuildKit, so a test stage nobody depends on silently never runs.
  A failed self-test fails the build.
- **Static linking** — `gcc -static` means the image needs no libc, which is
  what makes `FROM scratch` possible at all.
- **Minimal attack surface** — the running container proves it: no shell, no
  `/etc/passwd`, nothing to exec into or patch.
- **Image content vs runtime mounts** — `/dev`, `/proc`, `/sys`, `/etc` and
  `.dockerenv` appear at runtime from the container runtime; only `/primes` is
  actually in the image. The report says so, because the directory listing alone
  would suggest otherwise.

## Dependencies
- Docker daemon running, and your user in the `docker` group.
- Network access on first build (Alpine base image + gcc).

## Run
Unified Base builds and runs this automatically:
`docker build -t docker-multistage .` then `docker run --rm docker-multistage`.
Output is ANSI text in the tab's log panel — there is no GUI window to embed.

Manual equivalent:

```
docker build -t docker-multistage . && docker run --rm docker-multistage
```

## Files
- `Dockerfile` — the three stages
- `primes.c` — the payload: self-test, container report, and a prime sieve
