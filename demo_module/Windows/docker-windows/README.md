# Docker — Unified Base Windows demo #2: a Windows container

Every Linux demo's container is Linux. This one is **Windows all the way
down**: a .NET program in a Nano Server image, reporting on the Windows it
finds itself in — the counterpart of `docker-multistage`'s report from a
Linux scratch image.

What it prints, from inside the container:

- **its own Windows**: product, edition and build from the *container's*
  registry (Windows Server, not your Windows 11), and the kernel answering
  — the image's under Hyper-V isolation (the default on Windows 10/11, a
  small utility VM per container), the host's under process isolation;
- **who and where**: the container ID as hostname, the built-in
  `ContainerUser`, the CPUs and memory the container was given, a single
  `C:` of its own;
- **every process**: a handful — no desktop, no Explorer, no services you
  would recognise;
- **what isn't there**: no GUI, no Windows PowerShell, no .NET Framework.
  Nano Server is about 120 MB because it drops all of it.

## Demonstrates
- **Windows containers** — the Docker feature only a Windows host has.
- A **multi-stage build on Windows images**: the .NET SDK on Nano Server
  compiles, only the runtime image plus the output ships.
- The Dockerfile's `# escape=`` directive: Windows paths keep their
  backslashes because `` ` `` becomes the escape character.

## Dependencies
- **Docker Desktop switched to Windows containers** (tray icon ▸ *Switch to
  Windows containers…*). That needs Windows 10/11 Pro or Enterprise with
  the Containers and Hyper-V features, which Docker Desktop offers to turn
  on (a restart).
- The first build pulls the Nano Server .NET images (about 1.5 GB for the
  SDK, 150 MB for the runtime).

In Linux-containers mode, or on Linux, the build fails: these images exist
only for Windows. Current BuildKit pulls them anyway and stops at the first
`RUN` with *unable to find user ContainerUser: no matching entries in passwd
file*; older Docker says *no matching manifest for linux/amd64*.

## Run
Unified Base builds and runs this automatically (`docker build`, then
`docker run --rm`). Output is text in the tab's log panel.

Manual equivalent:

```
docker build -t docker-windows . && docker run --rm docker-windows
```

## Files
- `Dockerfile` — the build and runtime stages
- `report.csproj`, `Program.cs` — the report
