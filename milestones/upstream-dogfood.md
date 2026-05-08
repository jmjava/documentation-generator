# Upstream dogfood — second project that consumes `docgen`

**Upstream** here means a **separate repository** (application, course, or sample repo) that installs **docgen as a dependency** (`pip install docgen` or `pip install "docgen @ git+https://…"`), not the in-tree **`docs/demos`** path. Goal: prove the **library + CLI + CI contracts** work for a real consumer and capture friction for fixes here.

Pair with **[in-repo dogfood](next-session-dogfood.md)** (this repo’s `docs/demos` full run). The maintainer-facing command sequence for that tree lives in **`docs/demos/README.md`**.

**Designated consumer repo:** **`courseforge/course-builder`** — local clone: **`/home/ubuntu/github/courseforge/course-builder`**. All upstream dogfood work lands there; friction feeds back here.

---

## 0 — Preconditions (course-builder)

- [x] Clone / sync **`courseforge/course-builder`** at **`/home/ubuntu/github/courseforge/course-builder`** (or your equivalent path; keep docs here aligned with reality).
- [x] Decide **install source** for docgen in that repo: PyPI release vs **`pip install "docgen @ git+https://github.com/jmjava/documentation-generator.git@<sha>"`** (recommended until PyPI carries the fixes you need). *(CI uses `main` for the catalog reusable workflow; `docgen-demo-function` pins a SHA.)*

---

## 1 — Bootstrap the consumer repo

- [x] Add **`pyproject.toml`** / **`requirements.txt`** with `docgen` (and **`[dev]`** extras if you run pytest with docgen-adjacent tools). *(Consumer uses pip-from-git in Actions only; full bundle already has `docs/demos/docgen.yaml`.)*
- [x] Run **`docgen init`** (or hand-write **`docgen.yaml`**) under the chosen demo directory; set **`repo_root`**, **`env_file`**, **`discover_tests.roots`** if the app lives in a subfolder.
- [x] Commit a **minimal** segment set (one Manim or one VHS tape, or stills) so **`validate`** and **`generate-all --skip-*`** are achievable before Playwright extras land.

---

## 2 — CI that mirrors real consumers

- [x] GitHub Actions: **`pip install`** docgen from chosen ref; **`PYTHONPATH`** only if you also run **this** repo’s tests in the consumer (usually unnecessary—prefer testing the consumer’s own scripts).
- [x] Reuse **[`.github/workflows/reusable-docgen-catalog.yml`](../.github/workflows/reusable-docgen-catalog.yml)** (or copy the pattern): `catalog init`, `catalog stale`, optional **`merge-on-stale`** + **`discover-tests --merge-catalog`**. *(Shipped as **`.github/workflows/docgen-catalog.yml`** on `courseforge/course-builder` + committed **`docgen.catalog.yaml`**.)*
- [ ] If CI runs **VHS** or **Playwright**-derived steps: install **`ttyd`**, **`xvfb`**, wrap **`pytest`** with **`xvfb-run -a`** as in this repo’s **`ci.yml`**; set **`OPENAI_API_KEY`** secret if TTS / narration runs in CI.

---

## 3 — Exercise discovery + catalog from the outside

- [ ] From consumer repo root (with **`--config`** to demos yaml): **`docgen discover-tests`**, **`--suggest-visual-map`**, optional **`--merge-catalog`** into **their** `docgen.catalog.yaml`.
- [ ] Confirm **paths** in catalog entries and **`visual_map`** resolve against **their** `repo_root` (monorepo sub-apps: tune **`discover_tests.roots`**).

---

## 4 — Feedback loop into `documentation-generator`

- [ ] Open issues or PRs here for **every sharp edge** (missing doc, wrong default, CI recipe, CLI ergonomics).
- [ ] If the consumer must use unreleased APIs, note the **minimum git SHA** in their README until a **PyPI** release catches up.

---

## Optional

- [ ] Publish a **cookiecutter** / **GitHub template** repo that encodes upstream dogfood once it stabilizes.
- [ ] Add a short **“Consumer quickstart”** section in this repo’s **README** linking to **`courseforge/course-builder`** once the integration is demonstrable.

---

## Next (course-builder)

Shipped on **`courseforge/course-builder`**:

- **`docgen-generate-demos.yml`** — **`workflow_dispatch`** always runs **`docgen generate-all`** (requires **`OPENAI_API_KEY`** repository secret; fails fast if missing). **Push to `main`** on narration/animations/catalog paths runs the same when **`needs_regen`** from the reusable workflow is **`true`**. After a stale-driven run, the workflow **refreshes and commits** **`docgen.catalog.yaml`** so the stale gate clears. **Artifacts** upload **`docs/demos/recordings`** and **`docs/demos/audio`**.
- **`pages.yml`** — **push** re-enabled for **`docs/demos/recordings/**`**, **`docs/index.html`**, and the workflow file (narrow paths).

In **`documentation-generator`**: **`reusable-docgen-catalog.yml`** now exposes **`needs_regen`** to callers (``workflow_call`` outputs).

Still optional / later:

1. **`discover_tests.roots`** + **`merge-on-stale: true`** when a Node **`@playwright/test`** tree lives in the repo.
2. **Auto-commit narrated MP4s** to **`docs/demos/recordings`** from CI (today: download artifact and commit, or add a bot PR step).
3. **Pin `docgen-git-ref`** to a SHA instead of **`main`** for reproducible CI.
