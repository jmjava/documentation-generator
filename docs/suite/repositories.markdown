---
layout: page
title: Repositories
permalink: /docs/handbook/repositories/
---

Canonical **GitHub** remotes for the suite (also the Cursor **multi-root workspace** in this project).

| Repository | Role |
|------------|------|
| [**courseforge/infrastructure**](https://github.com/courseforge/infrastructure) | Orchestration: Kind installer, Tekton reuse, pins, **Publish GitHub Pages** (`publish-github-io.yml`), doc aggregation from product repos. |
| [**courseforge/course-builder**](https://github.com/courseforge/course-builder) | Main **Courseforge** application; hosts **docgen** consumer bundles (`docs/demos/`, `docs/rendered-site/`). |
| [**courseforge/github.io**](https://github.com/courseforge/github.io) | **Deployed** GitHub Pages repository; content is synced from `courseforge-github-io/` in **infrastructure**. |
| [**jmjava/documentation-generator**](https://github.com/jmjava/documentation-generator) | **`docgen`** CLI/library (Manim, TTS, validation) and this **suite handbook** (`docs/suite/`). |
| [**jmjava/tekton-dag**](https://github.com/jmjava/tekton-dag) | Reusable **Tekton DAG** / task library; version pins and reuse notes live in **infrastructure**. |

## Site source folder versus the github.io repository {#site-source-vs-github-io-repo}

**https://courseforge.github.io/** is served by **GitHub Pages** from the [**courseforge/github.io**](https://github.com/courseforge/github.io) GitHub repository (usually branch **`main`**, site published from the repo root).

Day-to-day **authoring** of that site lives in a **directory inside a different repo**:

| What | Where | Role |
|------|-------|------|
| **`courseforge-github-io/`** | Folder at the root of [**courseforge/infrastructure**](https://github.com/courseforge/infrastructure) | **Canonical Jekyll source** in git: `_config.yml`, `_layouts/`, this handbook under `docs/handbook/`, the [video doc index]({% link docs/index.markdown %}), aggregated `_data/<slug>.json`, and rendered assets under `docs/<slug>/`. Lets you change the public site in the same repo as orchestration (workflows, aggregator scripts, Kind layout). |
| **`courseforge/github.io`** | Its **own** GitHub repository under the **courseforge** org | **Pages deploy target** — the branch GitHub builds and hosts. CI cannot use the default `GITHUB_TOKEN` on **infrastructure** to push here, so [**`publish-github-io.yml`**](https://github.com/courseforge/infrastructure/blob/main/.github/workflows/publish-github-io.yml) uses **`BROAD_REPO_TOKEN`** (typically a PAT with full repo access on your suite; must be able to push **`main`** on **`github.io`**). |

[**`sync-github-io.sh`**](https://github.com/courseforge/infrastructure/blob/main/scripts/sync-github-io.sh) rsyncs **`infrastructure/courseforge-github-io/`** into a checkout of **`courseforge/github.io`** and pushes **`main`**. After a successful run, the **github.io** clone should match the folder (aside from any files that live only in **github.io** if the sync preserves them).

More detail: **infrastructure** root [`README.md` § Documentation (GitHub Pages)](https://github.com/courseforge/infrastructure/blob/main/README.md#documentation-github-pages) and **`courseforge-github-io/README.md`** in that repo.

Return to the [Suite handbook]({% link docs/handbook/index.markdown %}) or [Home]({% link index.markdown %}).
