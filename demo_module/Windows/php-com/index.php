<?php
// PHP — Unified Base Windows demo #2: Windows through COM.
//
// PHP for Windows has spoken COM since PHP 4, through the com_dotnet
// extension: `new COM('ProgID')`, then plain property and method calls, with
// COM collections iterable by foreach. This page is a live dashboard of the
// machine it runs on, every number from a COM object:
//
//   WbemScripting.SWbemLocator   WMI: system, processes, services, network
//   Scripting.FileSystemObject   drives
//   WScript.Shell                special folders
//
// `?live=1` answers JSON for the parts that refresh every two seconds.
// com_dotnet is not loaded by default: without it the page explains how to
// turn it on instead of failing.

declare(strict_types=1);

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function gb(float $bytes): string
{
    return number_format($bytes / 1024 ** 3, 1) . ' GB';
}

// ------------------------------------------------------- no COM? say so. --
if (!class_exists('COM')) {
    $ini = php_ini_loaded_file();
    http_response_code(500);
    ?><!doctype html><meta charset="utf-8"><title>COM is off</title>
    <body style="font:15px/1.6 'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;padding:30px">
    <h1>PHP's COM extension isn't loaded</h1>
    <p>This demo talks to Windows through <code>com_dotnet</code>, which PHP for
    Windows ships but doesn't load by default. Add this line to
    <?= $ini ? '<code>' . e($ini) . '</code>' : 'a <code>php.ini</code> next to <code>' . e(PHP_BINARY) . '</code> (copy <code>php.ini-development</code>)' ?>,
    then press Restart:</p>
    <pre style="background:#161b22;padding:12px;border-radius:8px">extension_dir = "ext"
extension=com_dotnet</pre>
    <p>Running on <?= e(PHP_OS_FAMILY) ?>: <?= PHP_OS_FAMILY === 'Windows' ? 'that is all it needs.'
        : 'COM exists only on Windows — run this demo there.' ?></p></body><?php
    exit;
}

// COM strings are UTF-16; ask for them as UTF-8, not the ANSI code page.
ini_set('com.code_page', (string) CP_UTF8);

$wmi = (new COM('WbemScripting.SWbemLocator'))->ConnectServer('.', 'root\\cimv2');

function rows(string $wql): array
{
    global $wmi;
    $out = [];
    foreach ($wmi->ExecQuery($wql) as $row) {     // a COM collection, iterated
        $out[] = $row;
    }
    return $out;
}

// --------------------------------------------------------------- live JSON --
function live(): array
{
    $os = rows('SELECT FreePhysicalMemory, TotalVisibleMemorySize FROM Win32_OperatingSystem')[0];
    $cpu = rows("SELECT PercentProcessorTime FROM Win32_PerfFormattedData_PerfOS_Processor WHERE Name='_Total'")[0];
    $procs = [];
    foreach (rows('SELECT Name, ProcessId, WorkingSetSize, ThreadCount FROM Win32_Process') as $p) {
        $procs[] = ['name' => (string) $p->Name, 'pid' => (int) $p->ProcessId,
                    'ws' => (float) $p->WorkingSetSize, 'threads' => (int) $p->ThreadCount];
    }
    usort($procs, fn($a, $b) => $b['ws'] <=> $a['ws']);
    $total = (float) $os->TotalVisibleMemorySize * 1024;
    return ['cpu' => (int) $cpu->PercentProcessorTime,
            'memUsed' => $total - (float) $os->FreePhysicalMemory * 1024, 'memTotal' => $total,
            'count' => count($procs), 'top' => array_slice($procs, 0, 12)];
}

if (isset($_GET['live'])) {
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    echo json_encode(live());
    exit;
}

// ------------------------------------------------------------ the sections --
$t0 = microtime(true);

// Each section runs on its own: one COM error shows in its card, not a blank page.
function section(callable $fn): array
{
    try {
        return [$fn(), null];
    } catch (com_exception $ex) {
        return [null, $ex->getMessage()];
    }
}

[$system, $systemErr] = section(function () {
    $os = rows('SELECT * FROM Win32_OperatingSystem')[0];
    $cs = rows('SELECT Manufacturer, Model FROM Win32_ComputerSystem')[0];
    $cpu = rows('SELECT Name, NumberOfCores, NumberOfLogicalProcessors FROM Win32_Processor')[0];
    // CIM datetime: 20261004011500.500000-300 — local time, then the offset
    // from UTC in minutes. Read without the offset it is hours off.
    $cim = (string) $os->LastBootUpTime;
    $off = (int) substr($cim, 21);
    $zone = new DateTimeZone(sprintf('%+03d:%02d', intdiv($off, 60), abs($off) % 60));
    $boot = DateTime::createFromFormat('YmdHis', substr($cim, 0, 14), $zone);
    $up = $boot ? (new DateTime('now', $zone))->diff($boot) : null;
    return [
        'Windows' => "{$os->Caption} {$os->OSArchitecture}",
        'Version' => "{$os->Version} (build {$os->BuildNumber})",
        'Up for' => $up ? $up->format('%a d %h h %i min') : '?',
        'Computer' => "{$cs->Manufacturer} {$cs->Model}",
        'CPU' => trim((string) $cpu->Name) . " · {$cpu->NumberOfCores} cores / {$cpu->NumberOfLogicalProcessors} threads",
    ];
});

[$drives, $drivesErr] = section(function () {
    $types = ['unknown', 'removable', 'fixed', 'network', 'optical', 'RAM'];
    $out = [];
    foreach ((new COM('Scripting.FileSystemObject'))->Drives as $d) {
        $row = ['letter' => (string) $d->DriveLetter, 'type' => $types[(int) $d->DriveType] ?? '?',
                'ready' => (bool) $d->IsReady];
        if ($row['ready']) {
            $row += ['fs' => (string) $d->FileSystem, 'label' => (string) $d->VolumeName,
                     'total' => (float) $d->TotalSize, 'free' => (float) $d->FreeSpace];
        }
        $out[] = $row;
    }
    return $out;
});

[$services, $servicesErr] = section(function () {
    $by = [];
    $autoStopped = [];
    foreach (rows('SELECT DisplayName, State, StartMode FROM Win32_Service') as $s) {
        $by[(string) $s->State] = ($by[(string) $s->State] ?? 0) + 1;
        if ($s->StartMode === 'Auto' && $s->State === 'Stopped') {
            $autoStopped[] = (string) $s->DisplayName;
        }
    }
    arsort($by);
    sort($autoStopped);
    return ['by' => $by, 'autoStopped' => $autoStopped];
});

[$network, $networkErr] = section(function () {
    $out = [];
    foreach (rows('SELECT Description, IPAddress, DHCPEnabled, MACAddress FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = TRUE') as $n) {
        $ips = [];
        foreach ($n->IPAddress as $ip) {             // a SAFEARRAY, iterated
            $ips[] = (string) $ip;
        }
        $out[] = ['name' => (string) $n->Description, 'ips' => $ips,
                  'dhcp' => (bool) $n->DHCPEnabled, 'mac' => (string) $n->MACAddress];
    }
    return $out;
});

[$folders, $foldersErr] = section(function () {
    $sh = new COM('WScript.Shell');
    $out = [];
    foreach (['Desktop', 'MyDocuments', 'Startup', 'Fonts', 'SendTo'] as $f) {
        $out[$f] = (string) $sh->SpecialFolders($f);
    }
    return $out;
});

$live = live();
$ms = (int) round((microtime(true) - $t0) * 1000);

function err(?string $msg): string
{
    return $msg === null ? '' : '<p class="err">COM error: ' . e($msg) . '</p>';
}

function bar(float $frac): string
{
    $pct = max(0, min(100, $frac * 100));
    $color = $pct > 90 ? '#ff7b72' : ($pct > 75 ? '#f0883e' : '#2ea043');
    return '<span class="bar"><i style="width:' . round($pct, 1) . '%;background:' . $color . '"></i></span>';
}
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PHP · Windows through COM — Unified Base Windows demo</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 22px 26px; background: #0d1117; color: #e6edf3;
         font: 14px/1.5 "Segoe UI Variable", "Segoe UI", system-ui, sans-serif; }
  h1 { font-size: 20px; margin: 0 0 2px; }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: #7d8590;
       margin: 0 0 10px; font-weight: 600; }
  .sub { color: #7d8590; font-size: 13px; margin: 0 0 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }
  .card { background: #161b22; border: 1px solid #21262d; border-radius: 10px; padding: 14px 16px; min-width: 0; }
  .wide { grid-column: 1 / -1; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 3px 14px; margin: 0; }
  dt { color: #7d8590; } dd { margin: 0; color: #9fd8ef; overflow-wrap: anywhere; }
  table { width: 100%; border-collapse: collapse; font: 12.5px "Cascadia Mono", Consolas, monospace; }
  th { text-align: left; color: #7d8590; font-weight: 600; padding: 3px 6px; border-bottom: 1px solid #21262d; }
  td { padding: 3px 6px; border-bottom: 1px solid #161b22; }
  td.n, th.n { text-align: right; }
  .bar { display: inline-block; width: 120px; height: 8px; background: #21262d; border-radius: 4px;
         overflow: hidden; vertical-align: middle; }
  .bar i { display: block; height: 100%; }
  .big { font-size: 34px; font-weight: 600; color: #e6edf3; }
  .muted, .note { color: #7d8590; font-size: 12.5px; }
  .err { color: #ff7b72; }
  ul { margin: 6px 0 0; padding-left: 18px; color: #c9d1d9; }
  code { font: 12.5px "Cascadia Mono", Consolas, monospace; color: #9fd8ef; }
  footer { margin-top: 16px; color: #7d8590; font: 12px "Cascadia Mono", Consolas, monospace; }
</style>
</head>
<body>
<h1>PHP · Windows through COM</h1>
<p class="sub">com_dotnet — <code>new COM('WbemScripting.SWbemLocator')</code>,
  <code>Scripting.FileSystemObject</code>, <code>WScript.Shell</code> · PHP <?= e(PHP_VERSION) ?></p>

<div class="grid">
  <section class="card">
    <h2>System — WMI</h2>
    <?= err($systemErr) ?>
    <dl><?php foreach ($system ?? [] as $k => $v): ?>
      <dt><?= e($k) ?></dt><dd><?= e($v) ?></dd><?php endforeach ?></dl>
  </section>

  <section class="card">
    <h2>Right now — refreshed every 2 s</h2>
    <div class="big"><span id="cpu"><?= $live['cpu'] ?></span> % <span class="muted">CPU</span></div>
    <p id="mem"><?= gb($live['memUsed']) ?> of <?= gb($live['memTotal']) ?> memory
      <?= bar($live['memUsed'] / $live['memTotal']) ?></p>
    <p class="note"><span id="count"><?= $live['count'] ?></span> processes ·
      <code>Win32_PerfFormattedData_PerfOS_Processor</code></p>
  </section>

  <section class="card">
    <h2>Drives — Scripting.FileSystemObject</h2>
    <?= err($drivesErr) ?>
    <table><tr><th>Drive</th><th>Type</th><th>FS</th><th class="n">Used</th><th></th></tr>
    <?php foreach ($drives ?? [] as $d): ?>
      <tr><td><?= e($d['letter']) ?>: <span class="muted"><?= e($d['label'] ?? '') ?></span></td>
          <td><?= e($d['type']) ?></td>
      <?php if ($d['ready']): ?>
          <td><?= e($d['fs']) ?></td>
          <td class="n"><?= gb($d['total'] - $d['free']) ?> / <?= gb($d['total']) ?></td>
          <td><?= bar(($d['total'] - $d['free']) / max($d['total'], 1)) ?></td>
      <?php else: ?>
          <td colspan="3" class="muted">not ready</td>
      <?php endif ?></tr>
    <?php endforeach ?></table>
  </section>

  <section class="card wide">
    <h2>Biggest processes by memory — Win32_Process, live</h2>
    <table id="procs"><thead><tr><th>Process</th><th class="n">PID</th><th class="n">Threads</th>
      <th class="n">Working set</th><th></th></tr></thead><tbody></tbody></table>
  </section>

  <section class="card">
    <h2>Services — Win32_Service</h2>
    <?= err($servicesErr) ?>
    <dl><?php foreach ($services['by'] ?? [] as $state => $n): ?>
      <dt><?= e($state) ?></dt><dd><?= $n ?></dd><?php endforeach ?></dl>
    <?php if (!empty($services['autoStopped'])): ?>
      <p class="note">Set to start automatically, but stopped right now (usually
        delayed or trigger-started — not necessarily broken):</p>
      <ul><?php foreach (array_slice($services['autoStopped'], 0, 8) as $s): ?>
        <li><?= e($s) ?></li><?php endforeach ?></ul>
    <?php endif ?>
  </section>

  <section class="card">
    <h2>Network — Win32_NetworkAdapterConfiguration</h2>
    <?= err($networkErr) ?>
    <?php foreach ($network ?? [] as $n): ?>
      <dl style="margin-bottom:10px">
        <dt>adapter</dt><dd><?= e($n['name']) ?></dd>
        <dt>addresses</dt><dd><?= e(implode(', ', $n['ips'])) ?></dd>
        <dt>DHCP</dt><dd><?= $n['dhcp'] ? 'yes' : 'no' ?></dd>
      </dl>
    <?php endforeach ?>
  </section>

  <section class="card">
    <h2>Special folders — WScript.Shell</h2>
    <?= err($foldersErr) ?>
    <dl><?php foreach ($folders ?? [] as $k => $v): ?>
      <dt><?= e($k) ?></dt><dd><?= e($v) ?></dd><?php endforeach ?></dl>
  </section>
</div>

<footer>rendered in <?= $ms ?> ms by <?= e(PHP_SAPI) ?> · every value from a COM object</footer>

<script>
  // The live card and the process table, from ?live=1 every two seconds.
  const fmt = (b) => (b / 1024 ** 3 >= 1 ? (b / 1024 ** 3).toFixed(1) + ' GB'
                                         : (b / 1024 ** 2).toFixed(0) + ' MB');
  const cell = (text, cls) => {
    const td = document.createElement('td');
    if (cls) td.className = cls;
    td.textContent = text;
    return td;
  };
  async function tick() {
    try {
      const d = await (await fetch('?live=1', { cache: 'no-store' })).json();
      document.getElementById('cpu').textContent = d.cpu;
      document.getElementById('count').textContent = d.count;
      const pct = d.memUsed / d.memTotal * 100;
      document.getElementById('mem').firstChild.textContent =
        `${fmt(d.memUsed)} of ${fmt(d.memTotal)} memory `;
      document.querySelector('#mem .bar i').style.width = pct.toFixed(1) + '%';
      const max = d.top.length ? d.top[0].ws : 1;
      document.querySelector('#procs tbody').replaceChildren(...d.top.map((p) => {
        const tr = document.createElement('tr');
        const bar = document.createElement('td');
        bar.innerHTML = '<span class="bar"><i style="background:#58a6ff"></i></span>';
        bar.querySelector('i').style.width = (p.ws / max * 100).toFixed(1) + '%';
        tr.append(cell(p.name), cell(p.pid, 'n'), cell(p.threads, 'n'), cell(fmt(p.ws), 'n'), bar);
        return tr;
      }));
    } catch (e) {
      /* a missed tick is fine; the next one tries again */
    }
  }
  tick();
  setInterval(tick, 2000);
</script>
</body>
</html>
