<?php
// PHP — Unified Base demo #2: forms, sessions, and state.
//
// The first PHP demo renders live server values. This one does the thing PHP
// actually exists for: accept a request that CHANGES something, then respond
// correctly. It is a small task list with:
//
//   * POST/redirect/GET  — a refresh after adding never re-submits the form
//   * CSRF tokens        — every mutating form carries a per-session token
//   * output escaping    — all user text goes through htmlspecialchars()
//   * session flash      — one-shot messages that survive exactly one redirect
//   * JSON persistence   — atomic writes, so a crash mid-save can't truncate
//
// No database, no framework, no JS. Refresh-safe by construction.

declare(strict_types=1);
session_start();
date_default_timezone_set('UTC');

const STORE = __DIR__ . '/.state/tasks.json';

// ---------------------------------------------------------------- storage --
function load_tasks(): array
{
    if (!is_file(STORE)) {
        return [];
    }
    $raw = json_decode((string) file_get_contents(STORE), true);
    return is_array($raw) ? $raw : [];
}

function save_tasks(array $tasks): void
{
    @mkdir(dirname(STORE), 0777, true);
    // Write to a temp file in the same directory, then rename: rename() is
    // atomic on the same filesystem, so readers never see a half-written file.
    $tmp = STORE . '.' . getmypid() . '.tmp';
    file_put_contents($tmp, json_encode($tasks, JSON_PRETTY_PRINT));
    rename($tmp, STORE);
}

// ------------------------------------------------------------------ csrf ---
function csrf_token(): string
{
    if (empty($_SESSION['csrf'])) {
        $_SESSION['csrf'] = bin2hex(random_bytes(16));
    }
    return $_SESSION['csrf'];
}

function csrf_ok(): bool
{
    // hash_equals compares in constant time; == would leak the token by timing.
    return isset($_POST['csrf'], $_SESSION['csrf'])
        && hash_equals($_SESSION['csrf'], (string) $_POST['csrf']);
}

function flash(string $msg): void
{
    $_SESSION['flash'] = $msg;
}

function take_flash(): ?string
{
    $msg = $_SESSION['flash'] ?? null;
    unset($_SESSION['flash']);
    return $msg;
}

function e(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
}

// --------------------------------------------------------------- actions ---
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!csrf_ok()) {
        flash('Rejected: bad or missing CSRF token.');
    } else {
        $tasks  = load_tasks();
        $action = (string) ($_POST['action'] ?? '');

        if ($action === 'add') {
            $text = trim((string) ($_POST['text'] ?? ''));
            if ($text === '') {
                flash('Nothing to add — the field was empty.');
            // mbstring is an optional extension; fall back to byte length so
            // the demo runs on a bare php-cli install.
            } elseif ((function_exists('mb_strlen') ? mb_strlen($text)
                                                    : strlen($text)) > 120) {
                flash('Rejected: task text is over 120 characters.');
            } else {
                $tasks[] = [
                    'id'    => bin2hex(random_bytes(6)),
                    'text'  => $text,
                    'done'  => false,
                    'added' => time(),
                ];
                flash('Added.');
            }
        } elseif ($action === 'toggle') {
            $id = (string) ($_POST['id'] ?? '');
            foreach ($tasks as &$t) {
                if ($t['id'] === $id) {
                    $t['done'] = !$t['done'];
                    flash($t['done'] ? 'Marked done.' : 'Reopened.');
                }
            }
            unset($t);
        } elseif ($action === 'delete') {
            $id = (string) ($_POST['id'] ?? '');
            $before = count($tasks);
            $tasks = array_values(array_filter(
                $tasks,
                static fn(array $t): bool => $t['id'] !== $id
            ));
            flash($before === count($tasks) ? 'Nothing deleted.' : 'Deleted.');
        } elseif ($action === 'clear') {
            $tasks = array_values(array_filter(
                $tasks,
                static fn(array $t): bool => !$t['done']
            ));
            flash('Cleared completed tasks.');
        }

        save_tasks($tasks);
    }

    // POST/redirect/GET: reply 303 so the browser re-requests with GET and a
    // refresh can never resubmit the form.
    header('Location: ' . strtok((string) $_SERVER['REQUEST_URI'], '?')
                        . '?filter=' . urlencode((string) ($_POST['filter'] ?? 'all')),
           true, 303);
    exit;
}

$_SESSION['views'] = ($_SESSION['views'] ?? 0) + 1;

$tasks  = load_tasks();
$filter = (string) ($_GET['filter'] ?? 'all');
$shown  = array_values(array_filter($tasks, static function (array $t) use ($filter): bool {
    return $filter === 'open' ? !$t['done']
        : ($filter === 'done' ? $t['done'] : true);
}));
$open   = count(array_filter($tasks, static fn(array $t): bool => !$t['done']));
$note   = take_flash();
$token  = csrf_token();
?>
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PHP · forms &amp; sessions — Unified Base demo</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 32px; background: #0d1117; color: #e6edf3;
         font: 15px/1.5 system-ui, sans-serif; }
  .wrap { max-width: 640px; margin: 0 auto; }
  h1 { font-size: 21px; margin: 0 0 4px; }
  .sub { color: #7d8590; font-size: 13px; margin-bottom: 20px; }
  .flash { background: #1f6feb22; border: 1px solid #1f6feb66; color: #79c0ff;
           padding: 8px 12px; border-radius: 8px; margin-bottom: 16px;
           font-size: 14px; }
  form.add { display: flex; gap: 8px; margin-bottom: 18px; }
  input[type=text] { flex: 1; background: #010409; border: 1px solid #30363d;
                     color: #e6edf3; padding: 9px 12px; border-radius: 8px; }
  button { background: #21262d; border: 1px solid #30363d; color: #e6edf3;
           padding: 9px 14px; border-radius: 8px; cursor: pointer; }
  button:hover { background: #30363d; }
  button.primary { background: #238636; border-color: #2ea043; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { display: flex; align-items: center; gap: 10px; padding: 10px 12px;
       border: 1px solid #21262d; border-radius: 8px; margin-bottom: 8px;
       background: #161b22; }
  li.done span.text { text-decoration: line-through; color: #7d8590; }
  span.text { flex: 1; }
  .filters { display: flex; gap: 6px; margin: 18px 0 10px; font-size: 13px; }
  .filters a { color: #7d8590; text-decoration: none; padding: 4px 10px;
               border: 1px solid #21262d; border-radius: 999px; }
  .filters a.on { color: #79c0ff; border-color: #1f6feb66; }
  .meta { color: #7d8590; font-size: 12px; margin-top: 18px;
          font-family: monospace; }
  .empty { color: #7d8590; padding: 18px; text-align: center;
           border: 1px dashed #30363d; border-radius: 8px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>PHP · forms, sessions &amp; state</h1>
  <div class="sub">POST/redirect/GET · CSRF tokens · escaped output · atomic JSON writes</div>

  <?php if ($note !== null): ?>
    <div class="flash"><?= e($note) ?></div>
  <?php endif; ?>

  <form class="add" method="post">
    <input type="hidden" name="csrf" value="<?= e($token) ?>">
    <input type="hidden" name="action" value="add">
    <input type="hidden" name="filter" value="<?= e($filter) ?>">
    <input type="text" name="text" placeholder="Add a task…" autofocus
           maxlength="120">
    <button class="primary" type="submit">Add</button>
  </form>

  <div class="filters">
    <?php foreach (['all', 'open', 'done'] as $f): ?>
      <a class="<?= $f === $filter ? 'on' : '' ?>" href="?filter=<?= $f ?>"><?= $f ?></a>
    <?php endforeach; ?>
  </div>

  <?php if (!$shown): ?>
    <div class="empty">No tasks<?= $filter === 'all' ? ' yet' : " matching “{$filter}”" ?>.</div>
  <?php else: ?>
    <ul>
      <?php foreach ($shown as $t): ?>
        <li class="<?= $t['done'] ? 'done' : '' ?>">
          <form method="post">
            <input type="hidden" name="csrf" value="<?= e($token) ?>">
            <input type="hidden" name="action" value="toggle">
            <input type="hidden" name="id" value="<?= e($t['id']) ?>">
            <input type="hidden" name="filter" value="<?= e($filter) ?>">
            <button type="submit" title="toggle"><?= $t['done'] ? '✓' : '○' ?></button>
          </form>
          <span class="text"><?= e($t['text']) ?></span>
          <form method="post">
            <input type="hidden" name="csrf" value="<?= e($token) ?>">
            <input type="hidden" name="action" value="delete">
            <input type="hidden" name="id" value="<?= e($t['id']) ?>">
            <input type="hidden" name="filter" value="<?= e($filter) ?>">
            <button type="submit" title="delete">✕</button>
          </form>
        </li>
      <?php endforeach; ?>
    </ul>
  <?php endif; ?>

  <form method="post" style="margin-top:14px">
    <input type="hidden" name="csrf" value="<?= e($token) ?>">
    <input type="hidden" name="action" value="clear">
    <input type="hidden" name="filter" value="<?= e($filter) ?>">
    <button type="submit">Clear completed</button>
  </form>

  <div class="meta">
    PHP <?= e(PHP_VERSION) ?> · <?= count($tasks) ?> task(s), <?= $open ?> open ·
    session <?= e(substr(session_id(), 0, 8)) ?>… · <?= (int) $_SESSION['views'] ?> view(s) ·
    <?= e(date('H:i:s')) ?> UTC
  </div>
</div>
</body>
</html>
