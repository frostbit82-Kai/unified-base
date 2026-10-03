# Ruby (Tk) — Unified Base demo

A live analog clock (hour/minute/second hands) drawn on a `TkCanvas` and
redrawn every second with `Tk.after`, plus a digital time + date label.
Demonstrates a real, embeddable Ruby GUI window via Ruby's classic **Tk** binding.

## Requirements

This demo needs both the **`tk` gem** and the **system Tcl/Tk** libraries it
binds to:

```bash
sudo apt install tk    # system Tcl/Tk (Ubuntu)
gem install tk         # the Ruby binding
```

If the `tk` gem or system Tcl/Tk is unavailable, Unified Base falls back to
**panel mode** (the script's stdout is shown in a log panel instead of an
embedded window).

## Run

Unified Base runs this automatically: it detects the `ruby` runtime
(`*.rb` / `Gemfile` / `Rakefile`), runs `bundle install` when a `Gemfile` is
present, then launches `ruby clock.rb`.

Manual run:

```bash
bundle install   # or: gem install tk
ruby clock.rb
```

## Files

- `clock.rb` — the Tk clock (entry point)
- `Gemfile` — declares `gem 'tk'`
- `README.md` — this file
