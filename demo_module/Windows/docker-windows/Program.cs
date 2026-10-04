// Docker — Unified Base Windows demo #2: the payload of a Windows container.
//
// Runs inside Nano Server and reports on the Windows it finds there — the
// Windows counterpart of docker-multistage's report from a Linux scratch
// image. A container is a whole Windows user mode of its own: its own
// registry, its own C:, a handful of system processes, a built-in user.
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32;

static void Row(string key, object? value) => Console.WriteLine($"  {key,-22} {value}");
static void Head(string title) => Console.WriteLine($"\n  {title}");

Console.WriteLine("\n  Docker · a Windows container");
Console.WriteLine($"  Nano Server, .NET {Environment.Version}, reporting on the Windows inside");

// The image's own registry: per container, not the host's.
using var cv = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows NT\CurrentVersion");
string Reg(string name) => cv?.GetValue(name)?.ToString() ?? "?";
Head("Windows in here");
Row("product", Reg("ProductName"));
Row("edition", Reg("EditionID"));
Row("image build", $"{Reg("CurrentBuild")}.{Reg("UBR")}");
// The kernel answering this call. Under Hyper-V isolation (the default on
// Windows 10/11) the container boots its own kernel in a utility VM, so
// this is the image's build; under process isolation it is the *host's*.
Row("kernel", RuntimeInformation.OSDescription);
Row("isolation", Reg("CurrentBuild") == Environment.OSVersion.Version.Build.ToString()
    ? "kernel matches the image: Hyper-V isolation, or a host of the same build"
    : "kernel is the host's: process isolation");

Head("Who and where");
Row("hostname", Environment.MachineName + "  (the container ID)");
Row("user", $@"{Environment.UserDomainName}\{Environment.UserName}");
Row("processors", Environment.ProcessorCount);
Row("memory available", $"{GC.GetGCMemoryInfo().TotalAvailableMemoryBytes / 1048576.0:N0} MB");
foreach (var d in DriveInfo.GetDrives().Where(d => d.IsReady))
    Row($"drive {d.Name}", $"{d.DriveFormat}, {d.TotalFreeSpace / 1073741824.0:N1} GB free of {d.TotalSize / 1073741824.0:N1} GB");

Head("Every process in the container");
foreach (var g in Process.GetProcesses().GroupBy(p => p.ProcessName).OrderBy(g => g.Key))
    Row(g.Key, g.Count() > 1 ? $"× {g.Count()}" : $"pid {g.First().Id}");

Head("What isn't here");
Row("Explorer, a desktop", File.Exists(@"C:\Windows\explorer.exe") ? "present" : "no — Nano Server has no GUI at all");
Row("PowerShell", File.Exists(@"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    ? "Windows PowerShell present" : "no Windows PowerShell — only cmd.exe");
Row(".NET Framework", Directory.Exists(@"C:\Windows\Microsoft.NET\Framework64")
    ? "present" : "no — only the .NET runtime this image added");
Console.WriteLine();
