# Python - Unified Base demo

A zero-dependency tkinter GUI: a ball bounces smoothly (~60fps via `after()`) around a Canvas, with a title label and a button that cycles the ball's color.

## Demonstrates
A pure standard-library Python GUI that opens one real, embeddable window with **zero setup** - contrast with the PyQt6 demo, which needs a dependency install.

## Dependencies
None beyond the Python standard library. `tkinter` ships with CPython.

- On a minimal Ubuntu, tkinter may live in a separate package: `sudo apt install python3-tk`
- Otherwise there is nothing to install - no `pip`, no venv packages.

## Running
Unified Base runs this automatically: it detects the `python` runtime, uses the venv's Python to launch `main.py`, and embeds the resulting window into a tab.

To run it manually:

```bash
python3 main.py
```
