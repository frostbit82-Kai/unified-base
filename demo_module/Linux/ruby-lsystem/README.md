# Ruby — Unified Base demo #2: L-system plotter

Pick one of five Lindenmayer systems (Koch snowflake, dragon curve, Sierpinski
arrowhead, fractal plant, Hilbert curve) and drag the depth slider. The status
line reports the grown string length, segment count, and draw time.

## Demonstrates
Ruby doing what Ruby is good at — the graphics are just the output:

- **String rewriting** — one `gsub` with a hash performs a whole generation,
  which is exactly the *simultaneous* rewrite an L-system requires (rules apply
  to the original string, never to their own output).
- **Struct as a record** — each system is a `Struct` of axiom, rules, angle,
  heading, and a depth cap that keeps the segment count canvas-sized.
- **Blocks and Enumerable** — the turtle walk is an `each_char` + `case`, the
  auto-fit is `flat_map`/`min`/`max`, colouring is `each_with_index`.
- **Tk from Ruby** — canvas, option menu, and a live scale widget whose
  `command` callback redraws, with `TkVariable` binding the widget state.

Depth is capped per system (a dragon curve at depth 14 is 16k segments) and the
drawing is auto-fitted to the canvas, so no system can escape the viewport.

## Dependencies
- Ruby (`ruby`) and the `tk` gem (`gem install tk`, plus `tcl-dev tk-dev`)

## Run
Unified Base runs this automatically. Manual equivalent:

```
ruby main.rb
```

Logic check, no window needed:

```
ruby main.rb --selftest
```

## Files
- `main.rb` — systems table, rewriting, turtle, auto-fit, Tk UI, and `--selftest`
