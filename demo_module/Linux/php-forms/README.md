# PHP — Unified Base demo #2: forms, sessions & state

A small task list served by PHP's built-in dev server. Add, toggle, delete,
filter, clear completed. No database, no framework, no JavaScript.

## Demonstrates
The first PHP demo renders live values. This one does the thing PHP exists for:
accept a request that *changes* something, then respond correctly.

- **POST/redirect/GET** — mutations answer `303 See Other`, so refreshing after
  an add can never resubmit the form.
- **CSRF tokens** — every mutating form carries a per-session token, compared
  with `hash_equals` (constant time; `==` would leak it by timing).
- **Output escaping** — all user text passes through `htmlspecialchars` on the
  way *out* while being stored raw, which is the correct place to escape.
- **Session flash messages** — one-shot notices that survive exactly one redirect.
- **Atomic JSON persistence** — writes go to a temp file then `rename()`, so a
  crash mid-save can't leave a truncated store.
- **Graceful degradation** — falls back to `strlen` when the optional `mbstring`
  extension is absent, so it runs on a bare `php-cli` install.

## Dependencies
- PHP CLI (`php`) — e.g. `sudo apt install php-cli`

## Run
Unified Base detects `composer.json` and runs `php -S localhost:8000` here,
with server logs in the tab. Open http://localhost:8000 to use it.

Manual equivalent:

```
php -S localhost:8000
```

## Files
- `composer.json` — marks the folder as a PHP project (triggers the dev server)
- `index.php` — routing, CSRF, storage, and template in one file
- `.state/` — created at runtime; holds `tasks.json`
