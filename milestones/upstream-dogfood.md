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

## Next (course-builder): regen videos in CI, not only catalog gate

The new workflow proves **install + catalog stale** on every relevant PR. It does **not** yet run **`generate-all`**, commit **`docs/demos/recordings`**, or re-enable automatic **Pages**. Suggested order:

1. Add **`discover_tests.roots`** (and optional **`docgen discover-tests --merge-catalog`** with **`merge-on-stale: true`**) once a Node **`@playwright/test`** tree exists under the repo.
2. Add a **self-hosted or heavy** workflow (Manim + ffmpeg + optional **`OPENAI_API_KEY`**) that runs **`docgen generate-all`** (or segment subsets) when `needs_regen` is true, then opens a PR or pushes artifacts.
3. Uncomment **`push`** in **`pages.yml`** when narrated outputs are stable again.
