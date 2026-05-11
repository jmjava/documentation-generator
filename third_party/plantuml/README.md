# PlantUML (vendored JAR)

This directory contains a **vendored binary** of [PlantUML](https://plantuml.com/) so the suite handbook diagrams can be rendered in CI and locally **without** a network download.

## Current file

- **`plantuml-1.2026.2.jar`** — release **1.2026.2** from the upstream project.

Upstream downloads: [PlantUML releases](https://github.com/plantuml/plantuml/releases).

## License

PlantUML is distributed under the **GNU General Public License v3 or later (GPL-3.0+)**. See the upstream repository for the full license text. Vendoring this JAR in-tree implies compliance with GPL obligations for distribution; this repo publishes only the unmodified binary for diagram rendering.

## Regenerating PNGs

From the repository root:

```bash
./scripts/render-suite-diagrams.sh
```

Requires **Java** on `PATH`. Some diagram types require **Graphviz** (`dot`); the suite relationship diagram uses built-in layout and typically renders without Graphviz.

Override the JAR path:

```bash
PLANTUML_JAR=/path/to/plantuml.jar ./scripts/render-suite-diagrams.sh
```
