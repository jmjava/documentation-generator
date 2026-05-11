# Manim declarative scene specs (dogfood)

Use these constraints when generating **`animations/specs/*.scene.yaml`** (via `docgen scene-spec-generate` or by hand):

- **Rows of `_box` only** in the spec compiler — short ASCII labels, no unicode arrows or smart punctuation (use `->` or hyphen).
- **Pages, not shrinking:** use top-level **`pages`** (list of `{ rows: [...], transition?: fade|none }`) when the story needs more boxes than fit on one screen. The compiler does **not** scale everything down; it **fade**s out the previous page’s stack (or **none** for an instant remove) before animating the next page. Single-page specs keep top-level **`rows`** only.
- **Frame budget:** dogfood scenes use a **14.22×8** Manim frame (`scenes.py` header). Content sits under the title — tall stacks (**many rows × box `height` + `row_gap`**) scroll past the bottom. Prefer **extra pages** or **shorter boxes** (`height` ~0.72–0.9, tighter `row_gap`) over piling 5+ full-height rows on one page.
- **~3 rows per page** is a safe default (~6 when rows use compact height); match beats in **`narration/<segment>.md`** and optional **`wait_segment`** / **`wait_at`** when `timing.json` has Whisper data.
- **Palette tokens only:** `C_BG`, `C_ACCENT`, `C_GREEN`, `C_ORANGE`, `C_BLUE`, `C_RED`, `C_TEAL`, `C_PURPLE`, `C_WHITE`.
- **Readable sizes:** `font_size` ≥ 14; widths ~3–6, heights ~0.7–1.3; tune `row_gap` / `column_gap` in `layout` if labels feel cramped.
- **Layout gate:** `docgen scene-spec-generate` rejects specs that exceed a computed vertical stack budget or safe row width (`layout_budget_violations` in `scene_spec.py`). `docgen scene-compile` does **not** enforce that (hand fixes allowed).
- **Layout:** `first_row_title_buff` ~0.5 under the title; `page_transition` / `page_transition_run_time` for defaults between pages (`fade` | `none`).
