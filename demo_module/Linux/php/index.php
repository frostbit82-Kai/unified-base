<?php
// PHP — Unified Base demo
// Self-contained dark dashboard served by PHP's built-in dev server.
// Live server-side values: PHP version, time, request count, uptime.

declare(strict_types=1);
date_default_timezone_set('UTC');

$stateDir   = __DIR__ . '/.state';
$countFile  = $stateDir . '/requests.count';
$startFile  = $stateDir . '/server.start';

if (!is_dir($stateDir)) {
    @mkdir($stateDir, 0777, true);
}

// Record the first-seen timestamp as "server start" (for uptime).
if (!is_file($startFile)) {
    @file_put_contents($startFile, (string) time());
}
$startTs = (int) @file_get_contents($startFile);
if ($startTs <= 0) {
    $startTs = time();
}

// Atomically increment a persistent request counter.
$count = 1;
$fh = @fopen($countFile, 'c+');
if ($fh !== false) {
    if (flock($fh, LOCK_EX)) {
        $raw   = stream_get_contents($fh);
        $count = ((int) trim((string) $raw)) + 1;
        ftruncate($fh, 0);
        rewind($fh);
        fwrite($fh, (string) $count);
        fflush($fh);
        flock($fh, LOCK_UN);
    }
    fclose($fh);
}

// Also log this request to the dev-server stderr (shows in Unified Base panel).
// STDERR is defined by the CLI SAPI only. `php -S` runs as "cli-server", where
// the constant does not exist and touching it is a fatal error -> HTTP 500.
// php://stderr is the same stream and works under every SAPI.
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path   = $_SERVER['REQUEST_URI'] ?? '/';
$err = fopen('php://stderr', 'w');
fwrite($err, sprintf("[%s] served %s %s  (request #%d)\n",
    date('H:i:s'), $method, $path, $count));
fclose($err);

$uptimeSec = max(0, time() - $startTs);
function human_uptime(int $s): string {
    $h = intdiv($s, 3600);
    $m = intdiv($s % 3600, 60);
    $sec = $s % 60;
    return sprintf('%02d:%02d:%02d', $h, $m, $sec);
}

$phpVersion = PHP_VERSION;
$sapi       = PHP_SAPI;
$osFamily   = PHP_OS_FAMILY;
$nowIso     = date('Y-m-d H:i:s') . ' UTC';
$startIso   = date('Y-m-d H:i:s', $startTs) . ' UTC';
$mem        = round(memory_get_usage(true) / 1048576, 1);
$peak       = round(memory_get_peak_usage(true) / 1048576, 1);
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Server-side refresh every 5s: bumps the request counter and re-renders live values -->
<meta http-equiv="refresh" content="5">
<title>PHP — Unified Base demo</title>
<style>
  :root {
    --bg: #0b1020;
    --bg2: #121a33;
    --card: rgba(255,255,255,0.04);
    --line: rgba(255,255,255,0.08);
    --ink: #e8edff;
    --muted: #93a0c8;
    --accent: #7c9cff;
    --accent2: #59e6c3;
    --glow: rgba(124,156,255,0.35);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; }
  body {
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    color: var(--ink);
    background:
      radial-gradient(900px 500px at 12% -10%, rgba(124,156,255,0.16), transparent 60%),
      radial-gradient(700px 500px at 110% 10%, rgba(89,230,195,0.12), transparent 55%),
      linear-gradient(160deg, var(--bg), var(--bg2));
    min-height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px 20px;
  }
  .wrap { width: 100%; max-width: 820px; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 26px; }
  .logo {
    width: 46px; height: 46px; border-radius: 12px; flex: none;
    display: grid; place-items: center; font-weight: 800; font-size: 13px; letter-spacing: .5px;
    color: #0b1020;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    box-shadow: 0 8px 30px var(--glow);
  }
  h1 { font-size: 20px; margin: 0; font-weight: 700; letter-spacing: .2px; }
  .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .live {
    margin-left: auto; display: inline-flex; align-items: center; gap: 8px;
    font-size: 12px; color: var(--muted);
    border: 1px solid var(--line); padding: 6px 12px; border-radius: 999px;
    background: var(--card);
  }
  .dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--accent2);
    box-shadow: 0 0 0 0 rgba(89,230,195,0.7);
    animation: pulse 1.8s infinite;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(89,230,195,0.55); }
    70%  { box-shadow: 0 0 0 10px rgba(89,230,195,0); }
    100% { box-shadow: 0 0 0 0 rgba(89,230,195,0); }
  }
  .grid {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 18px 18px 16px;
    backdrop-filter: blur(6px);
  }
  .card.big { grid-column: 1 / -1; }
  .label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 1.4px;
    color: var(--muted); margin-bottom: 8px;
  }
  .value { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .value.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  .value small { font-size: 14px; color: var(--muted); font-weight: 500; }
  .clockrow { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  #clock {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 44px; font-weight: 700; letter-spacing: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .bar { height: 6px; border-radius: 999px; background: rgba(255,255,255,0.06); overflow: hidden; margin-top: 14px; }
  .bar > i {
    display: block; height: 100%; width: 40%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    border-radius: 999px;
    animation: slide 2.6s ease-in-out infinite;
  }
  @keyframes slide {
    0%   { margin-left: -40%; }
    100% { margin-left: 100%; }
  }
  .meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
  .chip {
    font-size: 12px; color: var(--muted);
    border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px;
    background: var(--card);
  }
  .chip b { color: var(--ink); font-weight: 600; }
  footer { margin-top: 22px; text-align: center; color: var(--muted); font-size: 12px; }
  a { color: var(--accent); text-decoration: none; }
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="logo">PHP</div>
      <div>
        <h1>PHP — Unified Base demo</h1>
        <div class="sub">Rendered server-side by PHP <?= htmlspecialchars($phpVersion) ?> · <?= htmlspecialchars($sapi) ?></div>
      </div>
      <span class="live"><span class="dot"></span> live · auto-refresh 5s</span>
    </header>

    <div class="grid">
      <div class="card big">
        <div class="label">Server clock (UTC)</div>
        <div class="clockrow">
          <div id="clock"><?= htmlspecialchars(date('H:i:s')) ?></div>
          <div class="value"><small><?= htmlspecialchars($nowIso) ?></small></div>
        </div>
        <div class="bar"><i></i></div>
      </div>

      <div class="card">
        <div class="label">Requests served</div>
        <div class="value mono"><?= number_format($count) ?></div>
      </div>

      <div class="card">
        <div class="label">Server uptime</div>
        <div class="value mono" id="uptime" data-seconds="<?= $uptimeSec ?>"><?= human_uptime($uptimeSec) ?></div>
      </div>

      <div class="card">
        <div class="label">PHP version</div>
        <div class="value mono"><?= htmlspecialchars($phpVersion) ?></div>
      </div>

      <div class="card">
        <div class="label">Memory (used / peak)</div>
        <div class="value mono"><?= $mem ?><small> / <?= $peak ?> MB</small></div>
      </div>
    </div>

    <div class="meta">
      <span class="chip">SAPI <b><?= htmlspecialchars($sapi) ?></b></span>
      <span class="chip">OS <b><?= htmlspecialchars($osFamily) ?></b></span>
      <span class="chip">Started <b><?= htmlspecialchars($startIso) ?></b></span>
      <span class="chip">Doc root <b><?= htmlspecialchars(basename(__DIR__)) ?>/</b></span>
    </div>

    <footer>Served by <code>php -S localhost:8000</code> · launched automatically by Unified Base</footer>
  </div>

<script>
  // Smooth per-second ticking between the 5s server refreshes.
  (function () {
    var clock = document.getElementById('clock');
    var up = document.getElementById('uptime');
    var upSecs = parseInt(up.getAttribute('data-seconds'), 10) || 0;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function tick() {
      var d = new Date();
      clock.textContent = pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
      upSecs += 1;
      var h = Math.floor(upSecs / 3600);
      var m = Math.floor((upSecs % 3600) / 60);
      var s = upSecs % 60;
      up.textContent = pad(h) + ':' + pad(m) + ':' + pad(s);
    }
    setInterval(tick, 1000);
  })();
</script>
</body>
</html>
