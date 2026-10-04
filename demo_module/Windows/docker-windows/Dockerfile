# escape=`
# Docker — Unified Base Windows demo #2: a *Windows* container.
#
# Every Linux demo's container is Linux. This one is Windows all the way
# down: Nano Server, the smallest Windows Server image, running a .NET
# program that reports on the Windows it finds itself in.
#
#   build  → the .NET SDK on Nano Server compiles report.csproj
#   final  → the .NET runtime on Nano Server, plus the compiled app
#
# Needs Docker Desktop switched to Windows containers (tray icon ▸ "Switch to
# Windows containers…"). The escape directive above makes ` the escape
# character, so Windows paths can keep their backslashes.

FROM mcr.microsoft.com/dotnet/sdk:10.0-nanoserver-ltsc2025 AS build
WORKDIR C:\src
COPY report.csproj Program.cs ./
RUN dotnet publish -c Release -o C:\out --nologo

FROM mcr.microsoft.com/dotnet/runtime:10.0-nanoserver-ltsc2025
COPY --from=build C:\out C:\app
ENTRYPOINT ["dotnet", "C:\\app\\report.dll"]
