# Docker — Unified Base demo #2: a three-stage build ending in `scratch`.
#
#   builder → compiles a static binary with gcc + musl
#   tester  → RUNS the binary's self-test; a wrong binary fails the BUILD
#   final   → FROM scratch, containing exactly one file
#
# The tester stage is deliberately in the final stage's dependency chain
# (`COPY --from=tester`). A stage nothing copies from is skipped by BuildKit,
# so a test stage that isn't depended on never actually runs.

FROM alpine:3.20 AS builder
RUN apk add --no-cache gcc musl-dev
WORKDIR /src
COPY primes.c .
# -static: no shared libc, so the binary can live in an image that has no libc.
RUN gcc -O2 -Wall -Wextra -static -o /primes primes.c && strip /primes

FROM builder AS tester
RUN /primes --selftest

FROM scratch
COPY --from=tester /primes /primes
ENTRYPOINT ["/primes"]
