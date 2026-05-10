# Upstream dogfood — projects that consume `docgen`

**Upstream** here means a **separate repository** that installs **docgen**
(`pip install` from PyPI or **`pip install "docgen @ git+https://…@<sha>"`**),
maintains a demo bundle (often **`docs/demos`**), and runs CI that mirrors real
usage.

This library no longer ships an in-repo dogfood bundle; treat the consumer
project as the authoritative integration test.

## Bootstrap (generic)

- [ ] Add **`docgen`** as a dependency in the consumer’s Python project metadata.
- [ ] **`docgen init`** (or hand-write **`docgen.yaml`**) under the demo directory; set **`repo_root`**, **`env_file`**, **`dirs`**, **`segments`**, and **`visual_map`** (Manim / still / image / mixed as appropriate).
- [ ] Document the exact **`generate-all`** / **`validate`** sequence in the consumer’s **`docs/demos/README.md`**.

## CI (generic)

- [ ] Install **ffmpeg** (and **Manim** if scenes render in CI).
- [ ] Install **docgen** from the chosen git ref or PyPI version.
- [ ] Run **`validate`** / **`generate-all`** with secrets (e.g. **`OPENAI_API_KEY`**) only when those steps are in scope.

## Feedback

- [ ] Open issues or PRs in **this** repository for contract gaps, docs, or CLI ergonomics.
