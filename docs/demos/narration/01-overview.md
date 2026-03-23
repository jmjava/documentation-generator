docgen is a Python library and CLI that turns Markdown narration scripts into polished demo videos, automatically.

Most developer tools need recorded demos, but keeping them in sync with the codebase is tedious. Every time you refactor an API or change a UI flow, the old recording is stale. docgen solves this by making demo production reproducible.

You write narration in plain Markdown. docgen strips the formatting, sends the text to OpenAI text-to-speech, and produces an MP3. Terminal demos are recorded with VHS tape files, animations are rendered with Manim, and ffmpeg composites everything into final segment videos.

The entire pipeline runs from a single command: docgen generate-all. Or you can run each stage independently. TTS, Manim, VHS, compose, validate, concatenate.

Validation catches problems before you commit. Missing audio or video streams, audio-visual drift beyond a threshold, and narration text that still contains markdown syntax or metadata that should not be read aloud.

Everything is configured in one YAML file, docgen dot yaml. Segments, visual source mapping, TTS voice, validation thresholds, and wizard settings all live in a single place.
