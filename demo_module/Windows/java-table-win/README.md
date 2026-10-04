# Java — Unified Base Windows demo: Swing data table

The Windows twin of `demo_module/Linux/java-table`: 20,000 synthetic nodes
in a sortable, filterable table. Click a header to sort, type in the filter
box, select a row to see it in the status bar. Rows stream in from a
SwingWorker while the UI stays live.

## What differs on Windows
One line in `main()`: `UIManager.setLookAndFeel(getSystemLookAndFeelClassName())`.
Swing's *system* look and feel is a different class per OS — on Windows it
is `WindowsLookAndFeel`, drawn with the real Windows theme parts (header,
scrollbars, progress bar, text field), where the Linux twin gets Metal. The
dark colours the code sets explicitly still apply, so the two show exactly
what a look and feel owns and what the application does.

Also free on Windows: Java 9+ is per-monitor DPI aware, so the table is
sharp at 125 % without a manifest.

Everything else — `AbstractTableModel` with ranged insert events,
`SwingWorker` publish/process, `RowSorter` with a quoted live filter,
custom renderers — is described in the Linux README.

## Dependencies
- JDK 17+ (`winget install -e --id EclipseAdoptium.Temurin.25.JDK`, or the
  tab's Install button) and Maven (`mvn` on PATH — winget has no Maven
  package; unzip it from maven.apache.org and add its `bin` to PATH).

## Run
Unified Base builds and runs this automatically (`mvn package`, then the jar).

Manual equivalent:

```
mvn -q -DskipTests package && java -jar target/ub-swing-table-win.jar
```

## Files
- `pom.xml` — Maven build
- `src/main/java/com/example/App.java` — model, renderers, worker, and UI
