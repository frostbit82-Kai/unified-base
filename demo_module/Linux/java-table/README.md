# Java — Unified Base demo #2: Swing data table

20,000 synthetic nodes in a sortable, filterable table. Click a header to sort,
type in the filter box to narrow rows, select a row to see it in the status bar.
Rows stream in with a progress bar while the UI stays fully interactive.

## Demonstrates
Where the first Java demo is custom animation painting, this is Swing as an
*application* toolkit:

- **AbstractTableModel** — the model owns the data, the view asks for it. Batch
  inserts fire `fireTableRowsInserted` for the affected range, so selection and
  scroll position survive each batch (a blanket refresh would reset both).
- **SwingWorker threading** — `doInBackground()` builds rows off the EDT and
  `publish`/`process` hands batches back on it, the only thread allowed to touch
  Swing state.
- **RowSorter + RowFilter** — `getColumnClass` makes numeric columns sort as
  numbers, and the live filter quotes user input so a stray `(` can't throw
  `PatternSyntaxException` mid-typing.
- **Custom cell renderers** — coloured status text and an in-cell usage bar
  drawn with Graphics2D; a display-only renderer groups digits without
  disturbing numeric sorting.

## Dependencies
- JDK 17+ and Maven (`sudo apt install default-jdk maven`)

## Run
Unified Base builds and runs this automatically (`mvn package`, then the jar).

Manual equivalent:

```
mvn -q -DskipTests package && java -jar target/ub-swing-table.jar
```

## Files
- `pom.xml` — Maven build, `com.example.App` as the jar's main class
- `src/main/java/com/example/App.java` — model, renderers, worker, and UI
