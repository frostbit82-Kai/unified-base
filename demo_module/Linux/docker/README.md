# Docker — Unified Base demo

An animated ASCII dashboard (clock, uptime, incrementing counter, spinner, and a
sweeping progress bar) printed by a tiny containerized Python app — demonstrates
Unified Base's **panel mode**, streaming container stdout into the log panel.

## Deps

- Docker installed and running (the daemon must be up).

No other dependencies — the image is built from `python:3.12-alpine`.

## Run

Unified Base runs this automatically: it detects the `Dockerfile`, then does the
equivalent of

```sh
docker build -t docker .
docker run --rm docker
```

The container loops forever (so it stays "running"); stop it with Ctrl+C.
