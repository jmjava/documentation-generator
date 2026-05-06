# Upstream dogfood — second project that consumes `docgen`

**Upstream** here means a **separate repository** (application, course, or sample repo) that installs **docgen as a dependency** (`pip install docgen` or `pip install "docgen @ git+https://…"`), not the in-tree **`docs/demos`** path. Goal: prove the **library + CLI + CI contracts** work for a real consumer and capture friction for fixes here.

Pair with **[in-repo dogfood](next-session-dogfood.md)** (this repo’s `docs/demos` full run).

**Designated consumer repo:** **`courseforge/course-builder`** — local clone: **`/home/ubuntu/github/courseforge/course-builder`**. All upstream dogfood work lands there; friction feeds back here.

---

## 0 — Preconditions (course-builder)

- [ ] Clone / sync **`courseforge/course-builder`** at **`/home/ubuntu/github/courseforge/course-builder`** (or your equivalent path; keep docs here aligned with reality).
- [ ] Decide **install source** for docgen in that repo: PyPI release vs **`pip install "docgen @ git+https://github.com/jmjava/documentation-generator.git@<sha>"`** (recommended until PyPI carries the fixes you need).

---

## 1 — Bootstrap the consumer repo

- [ ] Add **`pyproject.toml`** / **`requirements.txt`** with `docgen` (and **`[dev]`** extras if you run pytest with docgen-adjacent tools).
- [ ] Run **`docgen init`** (or hand-write **`docgen.yaml`**) under the chosen demo directory; set **`repo_root`**, **`env_file`**, **`discover_tests.roots`** if the app lives in a subfolder.
- [ ] Commit a **minimal** segment set (one Manim or one VHS tape, or stills) so **`validate`** and **`generate-all --skip-*`** are achievable before Playwright extras land.

---

## 2 — CI that mirrors real consumers

- [ ] GitHub Actions: **`pip install`** docgen from chosen ref; **`PYTHONPATH`** only if you also run **this** repo’s tests in the consumer (usually unnecessary—prefer testing the consumer’s own scripts).
- [ ] Reuse **[`.github/workflows/reusable-docgen-catalog.yml`](../.github/workflows/reusable-docgen-catalog.yml)** (or copy the pattern): `catalog init`, `catalog stale`, optional **`merge-on-stale`** + **`discover-tests --merge-catalog`**.
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
