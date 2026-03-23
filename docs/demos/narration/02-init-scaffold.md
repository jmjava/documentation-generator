Getting started with docgen takes about thirty seconds. Run docgen init from any project directory and the interactive wizard does the rest.

It detects your git root, asks for a project name and where demo assets should live. If you already have narration files, it scans them and auto-populates the segment list. Otherwise it prompts you for segment names.

The wizard generates a complete docgen dot yaml with your project name wired into the TTS instructions and wizard prompts. It creates wrapper shell scripts so existing team workflows still work. And it scaffolds the full directory structure: narration, audio, animations, terminal, and recordings.

If you say yes to the pre-push hook, it adds a validation entry to your pre-commit config. Every push then checks that recordings have both audio and video streams, that drift is within tolerance, and that narration scripts are clean for TTS.

After init, your project is immediately ready. docgen tts dry-run previews the stripped text. docgen lint checks narration quality. docgen wizard launches the GUI. No manual setup required.
