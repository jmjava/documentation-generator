# docgen init — scaffold a new project
Output terminal/rendered/02-init-scaffold.mp4

Set Shell "bash"
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20

Type "# Scaffold a new project with docgen init"
Enter
Sleep 1s

Type "mkdir /tmp/my-new-project && cd /tmp/my-new-project && git init"
Enter
Sleep 2s

Type "# Run the interactive init wizard"
Enter
Sleep 500ms

Type "docgen init"
Enter
Sleep 1s

# Project name
Type "my-new-project"
Enter
Sleep 500ms

# Demo directory (accept default)
Enter
Sleep 500ms

# .env (skip)
Enter
Sleep 500ms

# Segment count
Type "3"
Enter
Sleep 500ms

# Segment names
Type "01-overview"
Enter
Sleep 300ms
Type "02-installation"
Enter
Sleep 300ms
Type "03-walkthrough"
Enter
Sleep 300ms

# TTS voice
Enter
Sleep 300ms

# TTS model
Enter
Sleep 300ms

# Pre-push hook
Type "y"
Enter
Sleep 2s

Type "# Check what was created"
Enter
Sleep 500ms
Type "find docs/demos -type f | sort"
Enter
Sleep 2s

Type "# Config is immediately usable"
Enter
Sleep 500ms
Type "cd docs/demos && docgen tts --dry-run"
Enter
Sleep 3s

Type "# Clean up"
Enter
Type "rm -rf /tmp/my-new-project"
Enter
Sleep 1s
