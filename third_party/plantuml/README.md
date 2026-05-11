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

Requires:

- **Java** on `PATH`
- **Graphviz** (`dot`) on `PATH` — the suite handbook **component** diagram (`suite-relationships.puml`) is laid out with Graphviz. Without `dot`, PlantUML still emits a PNG file that contains **only an error message** (green background), which is easy to miss in review.

CI (`.github/workflows/render-suite-diagrams.yml`) installs Graphviz on `ubuntu-latest`, then runs this script against the **vendored JAR** above — no download of PlantUML at job time.

Override the JAR path:

```bash
PLANTUML_JAR=/path/to/plantuml.jar ./scripts/render-suite-diagrams.sh
```
