# Manim declarative scene specs (dogfood)

Use these constraints when generating **`animations/specs/*.scene.yaml`** (via `docgen scene-spec-generate` or by hand):

- **Rows of `_box` only** in the spec compiler — short ASCII labels, no unicode arrows or smart punctuation (use `->` or hyphen).
- **4–8 rows** typical for a full narration; match beats in **`narration/<segment>.md`** and optional **`wait_segment`** indices when `timing.json` has Whisper segments.
- **Palette tokens only:** `C_BG`, `C_ACCENT`, `C_GREEN`, `C_ORANGE`, `C_BLUE`, `C_RED`, `C_TEAL`, `C_PURPLE`, `C_WHITE`.
- **Readable sizes:** `font_size` ≥ 14; widths ~3–6, heights ~0.7–1.3; increase `row_gap` / `column_gap` in `layout` if labels feel cramped.
- **First row** after title uses `first_row_title_buff` ~0.5; stack rows with consistent `row_gap`.
