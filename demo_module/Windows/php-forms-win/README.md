# PHP — Unified Base Windows demo: forms, sessions & state

The Windows twin of `demo_module/Linux/php-forms`: a small task list served
by PHP's built-in server — add, toggle, delete, filter, clear completed. No
database, no framework, no JavaScript.

## Why a twin
Same code, unchanged but for its title: the point is that it *is* the same.
The places where a PHP app usually trips on Windows were checked:

- **Atomic save by `rename()` over an existing file** — POSIX `rename`
  replaces atomically; on Windows PHP uses `MoveFileEx` with
  `MOVEFILE_REPLACE_EXISTING`, which works too. (It could fail if another
  request held the file open, but `php -S` serves one request at a time.)
- **Sessions** — with no `session.save_path`, PHP uses the temp folder
  (`%TEMP%` here, `/tmp` there).
- **Time zones** — set explicitly, so no `date.timezone` warning on a bare
  install.
- **`mbstring`** — optional on both; the code falls back to `strlen`.

The Linux README covers POST/redirect/GET, CSRF tokens with
`hash_equals`, escaping on output, flash messages and the atomic JSON store.

## Dependencies
- PHP 8 for Windows (`winget install -e --id PHP.PHP.8.4`). It needs the
  Visual C++ runtime (`winget install -e --id Microsoft.VCRedist.2015+.x64`).
- No Composer: `composer.json` requires no packages, so the launcher runs
  no `composer install`.

## Run
Unified Base runs `php -S localhost:<free port>` here and embeds Edge on it.

Manual equivalent:

```
php -S localhost:8000
```

## Files
- `composer.json` — marks the folder as a PHP project (the dev-server entry)
- `index.php` — routing, CSRF, storage and template in one file
- `.state/` — created at run time; holds `tasks.json`
