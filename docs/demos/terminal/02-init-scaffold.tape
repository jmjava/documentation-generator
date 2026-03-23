# docgen init — scaffold a new project
# Target ~70s to match 73s audio
Output rendered/02-init-scaffold.mp4

Set Shell "bash"
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20

Hide
Type "export PS1='$ '"
Enter
Sleep 500ms
Type "rm -rf /tmp/my-new-project"
Enter
Sleep 500ms
Show

Sleep 2s

Type "# Getting started with docgen takes about 30 seconds"
Enter
Sleep 3s

Type "mkdir /tmp/my-new-project && cd /tmp/my-new-project"
Enter
Sleep 2s

Type "git init"
Enter
Sleep 3s

Type "# Run the interactive init wizard"
Enter
Sleep 2s

Type "docgen init"
Enter
Sleep 3s

# Project name prompt
Type "my-new-project"
Enter
Sleep 2s

# Demo directory (accept default)
Enter
Sleep 2s

# .env (skip)
Enter
Sleep 2s

# Segment count
Type "3"
Enter
Sleep 2s

# Segment names
Type "01-overview"
Enter
Sleep 1500ms
Type "02-installation"
Enter
Sleep 1500ms
Type "03-walkthrough"
Enter
Sleep 1500ms

# TTS voice
Enter
Sleep 1500ms

# TTS model
Enter
Sleep 1500ms

# Pre-push hook
Type "y"
Enter
Sleep 4s

Type "# The wizard generated a complete docgen.yaml"
Enter
Sleep 3s

Type "cat docs/demos/docgen.yaml | head -20"
Enter
Sleep 5s

Type "# Plus wrapper shell scripts and full directory structure"
Enter
Sleep 2s

Type "find docs/demos -type f | sort"
Enter
Sleep 5s

Type "# Config is immediately usable"
Enter
Sleep 2s

Type "cd docs/demos && docgen tts --dry-run 2>&1 | head -10"
Enter
Sleep 5s

Type "# docgen lint checks narration quality"
Enter
Sleep 2s

Type "docgen lint"
Enter
Sleep 4s

Type "# No manual setup required — ready to go"
Enter
Sleep 3s

# Clean up
Hide
Type "rm -rf /tmp/my-new-project"
Enter
Sleep 500ms
