# docgen tts — TTS pipeline demo
Output terminal/rendered/04-tts-pipeline.mp4

Set Shell "bash"
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20

Type "cd docs/demos"
Enter
Sleep 500ms

Type "# Preview what TTS will say (no API call)"
Enter
Sleep 500ms

Type "docgen tts --dry-run --segment 01"
Enter
Sleep 3s

Type "# Lint narration for TTS-readiness"
Enter
Sleep 500ms

Type "docgen lint"
Enter
Sleep 2s

Type "# All segments pass — ready for TTS"
Enter
Sleep 1s

Type "# Generate audio for a single segment (requires OPENAI_API_KEY)"
Enter
Sleep 500ms

Type "docgen tts --dry-run"
Enter
Sleep 4s
