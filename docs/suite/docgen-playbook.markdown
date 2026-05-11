---
layout: page
title: Docgen playbook
permalink: /docs/handbook/docgen-playbook/
---

# Regenerating documentation (docgen) and regenerate narrated / video documentation in each repository. The library lives in [**jmjava/documentation-generator**](https://github.com/jmjava/documentation-generator); consumer repos own a **`docgen.yaml`** bundle (often under `docs/demos` or `docs/rendered-site`). Authoring contracts are described in [**AGENTS.md**](https://github.com/jmjava/documentation-generator/blob/main/AGENTS.md) in that repository.

## Install

Pin a git SHA (same pattern as CI):

```bash
python -m pip install "docgen[manim] @ git+https://github.com/jmjava/documentation-generator.git@<SHA>"
```

Use `pip install -e '.[manim]'` when hacking on **documentation-generator** itself.

## Common CLI commands

Run from the **bundle directory** (where `docgen.yaml` lives), unless noted:

| Command | Purpose |
|---------|---------|
| `docgen --help` | CLI overview |
| `docgen yaml-generate` | Refresh merged `docgen.yaml` from hints / segments (review diff) |
| `docgen generate-all` | Full pipeline: narration → audio → Manim → compose → concat (bundle-dependent) |
| `docgen validate` | Lint narration / A/V sync for the bundle |
| `docgen pages` | Static preview site (when configured) |

Consumer resets (after pin bumps): **`yaml-generate`** → regenerate media → **`validate`** (see **AGENTS.md**).

## Per-repo matrix (workspace)

Outputs are **not** interchangeable: the long-form **demos** bundle writes under **`docs/demos/`** (including **`recordings/`**). That tree is **never** read by the suite docs aggregator.

**courseforge.github.io pull contract (course-builder):** [**publish-github-io**](https://github.com/courseforge/infrastructure/blob/main/.github/workflows/publish-github-io.yml) sparse-clones **only** **`docs/rendered/`** from [**courseforge/course-builder**](https://github.com/courseforge/course-builder) **`main`** (see [`aggregate-rendered-docs.sh`](https://github.com/courseforge/infrastructure/blob/main/scripts/aggregate-rendered-docs.sh)). It expects a schema-valid **`docs/rendered/index.json`** next to the MP4s. **`docs/demos/recordings/`** does **not** populate **https://courseforge.github.io/docs/course-builder/** — run [**`docgen-render.yml`**](https://github.com/courseforge/course-builder/blob/main/.github/workflows/docgen-render.yml) (org bundle **`docs/rendered-site/`** → **`docs/rendered/`**) and merge to **`main`**.

| Repository | Bundle / paths today | Typical commands | CI workflow(s) | Status |
|------------|----------------------|------------------|----------------|--------|
| **courseforge/course-builder** | **Demos:** `docs/demos/docgen.yaml` → composed MP4s in **`docs/demos/recordings/`** (and bundle-relative audio / Manim / validation paths under `docs/demos/`). **Org Pages bundle:** `docs/rendered-site/docgen.yaml` → **`docs/rendered/`** (MP4s + **`index.json`**) for the suite docs index. | `cd docs/demos && docgen generate-all` · `docgen --config docs/rendered-site/docgen.yaml generate-all` | [docgen-generate-demos.yml](https://github.com/courseforge/course-builder/blob/main/.github/workflows/docgen-generate-demos.yml), [docgen-render.yml](https://github.com/courseforge/course-builder/blob/main/.github/workflows/docgen-render.yml) | **Active** |
| **jmjava/documentation-generator** | Library; suite handbook `docs/suite/` (not a consumer bundle) | `./scripts/render-suite-diagrams.sh` for PlantUML → PNG | [render-suite-diagrams.yml](https://github.com/jmjava/documentation-generator/blob/main/.github/workflows/render-suite-diagrams.yml) | **Active** |
| **jmjava/tekton-dag** | _(none yet)_ | _TBD when a `docgen.yaml` bundle is added_ | _TBD_ | **Planned** |
| **courseforge/infrastructure** | Runbooks under `docs/` (Markdown; not a docgen video bundle) | Clone repo; follow installer / publish docs | [publish-github-io.yml](https://github.com/courseforge/infrastructure/blob/main/.github/workflows/publish-github-io.yml) | **Reference** |
| **courseforge/github.io** | **GitHub Pages** deploy repo — content synced from **`courseforge/infrastructure`** [**`courseforge-github-io/`**](https://github.com/courseforge/infrastructure/tree/main/courseforge-github-io) (not authored only here). | N/A (no docgen here) | N/A | **Target** — see [Repositories: site folder vs Pages repo]({% link docs/handbook/repositories.markdown %}#site-source-vs-github-io-repo) |

## Suite handbook diagrams

PlantUML sources: `docs/suite/diagrams/*.puml`. Regenerate PNGs:

```bash
./scripts/render-suite-diagrams.sh
```

Requires **Java** and **Graphviz** (`dot`). See `third_party/plantuml/README.md` for the vendored JAR, GPL note, and CI (`render-suite-diagrams.yml`).

---

[Suite handbook]({% link docs/handbook/index.markdown %}) · [Video docs index]({% link docs/index.markdown %})
