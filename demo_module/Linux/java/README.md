# Java (Swing) — Unified Base demo

Demonstrates a native Java Swing GUI: an 800x600 window with a custom, double-buffered,
antialiased `JPanel` animating a glowing bouncing ball at ~60 fps via a `javax.swing.Timer`.

## Dependencies

- JDK 17+
- Maven

Pure JDK — no external libraries.

## Running

Unified Base runs this automatically: it detects `pom.xml`, builds with
`mvn -q -DskipTests package`, then launches `java -jar target/ub-swing-demo.jar`
and embeds the window into a tab.

To run it by hand:

```bash
mvn -q -DskipTests package
java -jar target/ub-swing-demo.jar
```
