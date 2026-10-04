# Docker — Unified Base Windows demo: multi-stage build & a scratch image

The Windows twin of `demo_module/Linux/docker-multistage`: the same
three-stage Dockerfile — compile a static C binary, run its self-test as a
build stage, ship it alone in a `FROM scratch` image of about 70 kB — built
from a Windows checkout. Its report, printed from inside the container, is
identical on both: a Linux container is Linux, whatever the host.

## Docker on Windows, two ways
- **Docker Desktop** (`winget install -e --id Docker.DockerDesktop`, or the
  tab's Install button): runs Linux containers in a WSL 2 VM and puts
  `docker` on the Windows PATH. It needs a UAC prompt and, on first launch,
  accepting Docker's subscription agreement.
- **Docker Engine inside your WSL distro**, no Desktop:
  `wsl -u root apt install docker.io docker-buildx`, then set this tab's
  **Runs on ▸ Linux only**: the launcher runs `docker build` / `docker run`
  through WSL.

## The Windows trap this twin avoids
Files checked out with CRLF line endings break inside a Linux container —
a shell script fails with `/bin/sh^M: not found`, a Dockerfile `RUN` line
gets a stray `\r`. Git for Windows converts to CRLF by default; this
repository's `.gitattributes` pins `eol=lf`, so the build context is
byte-identical to the Linux checkout.

The Linux README covers the stages, why the test stage is in the final
stage's dependency chain, static linking and `FROM scratch`.

## Run
Unified Base builds and runs this automatically (`docker build`, then
`docker run --rm`). Output is text in the tab's log panel — there is no
window to embed.

## Files
- `Dockerfile` — the three stages
- `primes.c` — the payload: self-test, container report, prime sieve
