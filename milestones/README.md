# Milestones

**Consumers:** See **[upstream-dogfood.md](upstream-dogfood.md)** — notes for
repositories that install `docgen` and maintain their own demo bundle. The
library no longer ships an in-repo dogfood; consumers are the integration test
of record.

**Active:** **[cli-segments-all.md](cli-segments-all.md)** —
`narration-generate --all` / `scene-spec-generate --all` must use
`Config.segments_all` (missing `all` falls back to `default`).

**Shipped:**
- **[empty-segments-all.md](empty-segments-all.md)** —
  explicit empty `segments.all: []` must not fall through to
  `segments.default` in yaml-generate (#124).
- **[concat-ffmpeg-timeout.md](concat-ffmpeg-timeout.md)** —
  concat must not leave a truncated full-demo mp4 after ffmpeg
  timeout or failure (#123).
- **[generation-zero-values.md](generation-zero-values.md)** —
  `temperature: 0` / `max_whisper_segment_text_chars: 0` must not be
  replaced by ``or`` defaults (#122).
- **[compose-ffmpeg-timeout.md](compose-ffmpeg-timeout.md)** —
  compose must not treat a timed-out ffmpeg mux as success (#121).
- **[visual-beats-numeric.md](visual-beats-numeric.md)** —
  `visual_beats` / `default_visual_beats` must be YAML numbers (#120).
- **[validation-enable-bools.md](validation-enable-bools.md)** —
  validation / manim enable flags must be YAML booleans (#119).
- **[validation-numeric-tunables.md](validation-numeric-tunables.md)** —
  nested validation OCR / layout / av_sync / timing / story_end
  numerics must be YAML numbers (#118).
- **[generation-numeric-tunables.md](generation-numeric-tunables.md)** —
  narration / scene-generation temperature and context-byte tunables
  must be YAML numbers (#117).
- **[hint-segment-create-bool.md](hint-segment-create-bool.md)** —
  hint `docgen.segment.create` must be a YAML boolean (#116).
- **[numeric-config-tunables.md](numeric-config-tunables.md)** —
  timestamps / compose / manim / validation numeric tunables must be
  YAML numbers (#115).
- **[discovery-bool-flags.md](discovery-bool-flags.md)** —
  `discovery.auto_visual_map` / `merge_hint_segments` must be YAML
  booleans (#114).
- **[wizard-default-guidance.md](wizard-default-guidance.md)** —
  `wizard.default_guidance` must be a YAML string at config load (#113).
- **[visual-map-sources.md](visual-map-sources.md)** —
  `visual_map` mixed `sources` must be a YAML list of strings (#112).
- **[pages-config-strings.md](pages-config-strings.md)** —
  `pages.docs_dir` / title / extra_links must be typed (#111).
- **[generation-segment-strings.md](generation-segment-strings.md)** —
  per-segment narration / scene-generation prompts must be YAML strings
  (#110).
- **[path-config-strings.md](path-config-strings.md)** —
  `env_file` / `repo_root` / `dirs.*` must be YAML strings (#109).
- **[visual-map-field-strings.md](visual-map-field-strings.md)** —
  `visual_map` type/scene/source and `segment_names` values must be YAML
  strings (#108).
- **[generation-model-strings.md](generation-model-strings.md)** —
  `narration_from_source` / `manim_scene_generation` model and prompt
  keys must be YAML strings (#107).
- **[manim-font-quality.md](manim-font-quality.md)** —
  `manim.font` / `quality` / `manim_path` must be YAML strings (#106).
- **[ai-timestamp-strings.md](ai-timestamp-strings.md)** —
  `ai.provider` / `timestamps.engine` / `tts.language` must be YAML
  strings (#105).
- **[image-generation-strings.md](image-generation-strings.md)** —
  `image_generation.model` / `size` / `quality` must be YAML strings (#104).
- **[image-empty-bytes.md](image-empty-bytes.md)** —
  `image-generate` must not write empty PNG bytes as success (#103).
- **[hint-front-matter-yaml.md](hint-front-matter-yaml.md)** —
  Invalid `hints/*.md` YAML front matter must fail `yaml-generate`, not skip
  hint `visual_map` wiring (#102).
- **[av-sync-anchor-keywords.md](av-sync-anchor-keywords.md)** —
  `validation.av_sync.anchor_keywords` must be a mapping of keyword rows
  (#101).
- **[wizard-prompt-strings.md](wizard-prompt-strings.md)** —
  `wizard.system_prompt` / `llm_model` must be YAML strings at config load
  (#100).
- **[tts-empty-audio.md](tts-empty-audio.md)** —
  TTS must not succeed with an empty mp3; `tts.model` / `voice` /
  `instructions` must be YAML strings (#99).
- **[av-sync-scene-spec.md](av-sync-scene-spec.md)** —
  Unreadable `*.scene.yaml` must fail `av_sync`, not fall back to transcript
  nouns (#98).
- **[layout-check-errors.md](layout-check-errors.md)** —
  Manim layout check crashes must fail, not skip as success (#97).
- **[manim-unsafe-unicode.md](manim-unsafe-unicode.md)** —
  `manim.unsafe_unicode` must be a YAML list at config load (#96).
- **[validation-list-keys.md](validation-list-keys.md)** —
  `validation.ocr.error_patterns`, `av_sync.visual_types`, and narration-lint
  deny pattern lists must be YAML lists (#95).
- **[wizard-exclude-lists.md](wizard-exclude-lists.md)** —
  `wizard.exclude_patterns` / `scan_extensions` must be string lists (#94).
- **[timestamps-merge-stems.md](timestamps-merge-stems.md)** — CLI `timestamps`
  merges stems into existing `timing.json` instead of wiping extra keys (#93).
- **[asset-graph-timing.md](asset-graph-timing.md)** — wizard freshness must
  not treat corrupt `timing.json` as a missing timestamps entry (#92).
- **[yaml-generate-mappings.md](yaml-generate-mappings.md)** — `yaml-generate`
  merge/discover must not replace a list/scalar `visual_map` or narration/manim
  block with `{}` (#91).
- **[context-path-lists.md](context-path-lists.md)** — `pages.segments` and
  narration/manim context path lists must be typed (#90).
- **[timing-json-parse.md](timing-json-parse.md)** — corrupt `timing.json`
  must not be treated as empty words at compile/validate (#89).
- **[lint-empty-narration.md](lint-empty-narration.md)** — lint / validate fail
  when narration has no spoken prose after markdown stripping (#88).
- **[segment-id-strings.md](segment-id-strings.md)** — unquoted YAML `01`
  must not become integer segment ids (#87).
- **[visual-map-row-types.md](visual-map-row-types.md)** — `visual_map` rows
  and `pages.segments` entries must be mappings; unknown compose `type`
  fails closed (#86).
- **[timestamps-empty-words.md](timestamps-empty-words.md)** — heading-only
  / empty-word timestamps fail closed (#85).
- **[concat-segment-lists.md](concat-segment-lists.md)** — concat targets
  must be lists of segment ids; pages extra_links items must be mappings
  (#84).
- **[config-mapping-keys.md](config-mapping-keys.md)** — nested `docgen.yaml`
  mapping/list keys must not traceback; lint/compose empty-all must not
  succeed (#83).
- **[manim-lint-config.md](manim-lint-config.md)** — missing `scenes.py`
  fails validate; invalid `docgen.yaml` is `ConfigError`; TTS empty-all
  fails (#82).
- **[wizard-narration-paths.md](wizard-narration-paths.md)** — wizard
  generate-narration must not drop missing sources; timestamps must not wipe
  corrupt `timing.json` (#81).
- **[validate-fail-closed.md](validate-fail-closed.md)** — validate
  narration/timing skips, empty Manim lists, missing context paths.
- **[scene-compile-pace.md](scene-compile-pace.md)** — paced `scene-compile`
  requires timing words; `yaml-generate` keeps committed Manim rows.
- **[timestamps-fail-closed.md](timestamps-fail-closed.md)** — timestamps,
  concat, Anthropic `base_url`, and remaining CLI/wizard silent-success paths.
- **[pipeline-fail-closed.md](pipeline-fail-closed.md)** — `generate-all` /
  `yaml-generate` fail closed (preserve still/recording wiring; no silent
  compose/validate skip).
- **[multi-host-ai-hardening.md](multi-host-ai-hardening.md)** — Cloud /
  local Cursor / Claude Code keys, `--repo` clone cache, fail-closed chat.

**Not in this milestone:** archived slides / i18n / Playwright / Embabel
roadmaps under [archive/](archive/) (Playwright was removed from the product;
Embabel is a future sketch).

**Archived roadmaps:** [archive/](archive/) — older write-ups kept for history;
not the day-to-day execution list.

**Session notes (ad hoc):** e.g. declarative Manim work under
`docs/session-notes*.md` when present.
