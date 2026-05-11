---
layout: page
title: Suite handbook
permalink: /docs/handbook/
---

This handbook describes how the **Courseforge** and related **jmjava** repositories fit together: responsibilities, documentation flow, and where to regenerate narrated video docs with **docgen**.

Sources for this section (Markdown, PlantUML, and the rendered diagram below) live in **[jmjava/documentation-generator](https://github.com/jmjava/documentation-generator)** under `docs/suite/`. They are synced into this site whenever **[courseforge/infrastructure](https://github.com/courseforge/infrastructure)** runs [**Publish GitHub Pages**](https://github.com/courseforge/infrastructure/blob/main/.github/workflows/publish-github-io.yml).

## Repository relationships

![Suite repository relationships]({{ '/docs/handbook/generated/suite-relationships.png' | relative_url }})

*Diagram source:* [`docs/suite/diagrams/suite-relationships.puml`](https://github.com/jmjava/documentation-generator/blob/main/docs/suite/diagrams/suite-relationships.puml) in **documentation-generator**. To regenerate PNGs locally or in CI, use `./scripts/render-suite-diagrams.sh` (requires Java; see `third_party/plantuml/README.md`).

## Where to read next

- [Suite architecture]({% link suite-architecture.markdown %}) — narrative architecture page on this site.
- [Repositories]({% link docs/handbook/repositories.markdown %}) — quick links to every workspace repo and its role.
- [Regenerating documentation (docgen)]({% link docs/handbook/docgen-playbook.markdown %}) — CLI recap and per-repo status.
- [Documentation / video index]({% link docs/index.markdown %}) — aggregated **docgen** renders (`docs/rendered/` from each product repo).

## Suite integration (deep dive)

The orchestration repo’s Phase 1 trigger graph and workflows are documented in [`docs/suite-integration.md`](https://github.com/courseforge/infrastructure/blob/main/docs/suite-integration.md).
