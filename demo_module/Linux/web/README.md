# Web (Vite) — Unified Base demo

An interactive canvas particle field (vanilla Vite, no framework): particles chase
your mouse and fall into an idle orbit when it stops.

## Deps

```
npm install
```

Installs `vite` (the only dependency — see `package.json`).

## Run

Unified Base runs this automatically: it detects the **web** runtime from
`package.json` (a `vite` dependency plus a `dev` script), executes `npm run dev`,
reads the localhost URL Vite prints on stdout, then opens Chromium in `--app` mode
at that URL and embeds the window in a tab.

To run it by hand: `npm run dev`, then open the printed URL.

## Files

- `package.json` — `dev` script + `vite` devDependency
- `index.html` — page shell, heading, canvas
- `src/main.js` — the particle animation
