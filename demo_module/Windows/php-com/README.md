# PHP — Unified Base Windows demo #2: Windows through COM

A live dashboard of the machine it runs on, from PHP's Windows-only
**COM extension** (`com_dotnet`): system facts, CPU and memory refreshed
every two seconds, drives, the biggest processes, services, network
adapters and special folders — every value from a COM object.

| Card | COM object |
|---|---|
| System, Right now, Processes, Services, Network | WMI — `WbemScripting.SWbemLocator` → `ExecQuery` (WQL) |
| Drives | `Scripting.FileSystemObject` |
| Special folders | `WScript.Shell` |

## Demonstrates
- **COM from PHP**: `new COM('ProgID')`, then plain properties and
  methods. COM collections are `foreach`-able, and so are `SAFEARRAY`
  properties (an adapter's `IPAddress`).
- **UTF-8 across the boundary**: COM strings are UTF-16; `com.code_page =
  CP_UTF8` hands them to PHP as UTF-8 instead of the ANSI code page.
- **A JSON endpoint on the same page**: `?live=1` answers the refreshing
  parts; a few lines of `fetch` update the DOM through `textContent`.
- **One failure, one card**: each section catches `com_exception` and
  shows it in place instead of blanking the page.
- **CIM datetimes** (`20261004011500.500000-300`) are local time plus an
  offset in minutes. Read without the offset — PHP defaults to UTC — the
  uptime came out five hours long.
- **WMI's cold start**: the very first query after boot can take ~10 s
  while WMI loads its providers; after that a full page is about a second.
- **Degrading honestly**: without `com_dotnet` the page shows the two
  `php.ini` lines to add, and where that file is.

## Dependencies
- PHP 8 for Windows (`winget install -e --id PHP.PHP.8.4`, plus
  `Microsoft.VCRedist.2015+.x64`) with COM enabled in `php.ini`:

  ```
  extension_dir = "ext"
  extension=com_dotnet
  ```

  winget's PHP comes with no `php.ini` at all: copy `php.ini-development`
  to `php.ini` next to `php.exe` and add those lines.

## Run
Unified Base runs `php -S localhost:<free port>` and embeds Edge on it.
Windows-only; elsewhere the page says why.

Manual equivalent:

```
php -S localhost:8000
```

## Files
- `composer.json` — marks the folder as a PHP project (the dev-server entry)
- `index.php` — the queries, the JSON endpoint and the page
