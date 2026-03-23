# docgen tts — TTS pipeline demo
# Target ~78s to match 82s audio
Output rendered/04-tts-pipeline.mp4

Set Shell "bash"
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20

Hide
Type "export PS1='$ '"
Enter
Sleep 500ms
Show

Sleep 2s

Type "cd docs/demos"
Enter
Sleep 2s

Type "# The TTS command reads narration markdown and strips formatting"
Enter
Sleep 3s

Type "# Preview what TTS will say — no API call"
Enter
Sleep 2s

Type "docgen tts --dry-run --segment 01"
Enter
Sleep 6s

Type "# All headings, bold markers, backtick code,"
Enter
Sleep 2s
Type "# links, and stage directions are stripped away"
Enter
Sleep 3s

Type "# What remains is plain spoken text"
Enter
Sleep 3s

Type "# Preview all segments at once"
Enter
Sleep 2s

Type "docgen tts --dry-run"
Enter
Sleep 8s

Type "# Each segment produces an MP3 in the audio directory"
Enter
Sleep 3s

Type "# The file name matches the narration stem:"
Enter
Sleep 2s
Type "#   01-overview.md  →  01-overview.mp3"
Enter
Sleep 3s

Type "# Regenerate a single segment with --segment"
Enter
Sleep 2s

Type "# docgen tts --segment 01"
Enter
Sleep 4s

Type "# Narration lint catches patterns that should never reach TTS"
Enter
Sleep 3s

Type "docgen lint"
Enter
Sleep 5s

Type "# Duration metadata, visual descriptions, section markers,"
Enter
Sleep 2s
Type "# and any remaining markdown syntax are flagged"
Enter
Sleep 3s

Type "# Fix those before generating audio"
Enter
Sleep 3s

Type "# All segments pass — ready for TTS"
Enter
Sleep 4s
