# PHP — Unified Base demo

A one-page dark server-side dashboard that shows live values rendered by PHP:
PHP version, server clock, persistent request count, and uptime. The page uses a
`<meta refresh>` to re-render server values every 5s and a tiny JS clock for smooth
per-second ticking.

## Demonstrates
PHP's built-in dev server rendering a self-contained, animated HTML dashboard
(inline CSS/JS, no external assets, no network).

## Dependencies
- PHP CLI (`php`) — e.g. `sudo apt install php-cli`

## Run
Unified Base runs this automatically: it detects `composer.json` and launches
`php -S localhost:8000` in this folder, showing server logs in panel mode.

Manual equivalent:

```
php -S localhost:8000
```

Then open http://localhost:8000

## Files
- `composer.json` — marks the folder as a PHP project (triggers the dev-server entry)
- `index.php` — the dashboard (all logic + inline styles)
- `.state/` — created at runtime to persist the request counter and start time
