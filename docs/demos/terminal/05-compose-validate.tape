# docgen compose + validate — composition and quality checks
# Target ~92s to match 97s audio
Output rendered/05-compose-validate.mp4

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

Type "# Composition is where audio meets video"
Enter
Sleep 3s

Type "# The visual map in docgen.yaml tells Compose where to find each source"
Enter
Sleep 3s

Type "grep -A3 'visual_map' docgen.yaml | head -16"
Enter
Sleep 6s

Type "# A segment can be Manim, VHS, a mix, image, or solid color"
Enter
Sleep 4s

Type "# When video is shorter than audio, Compose freezes the last frame"
Enter
Sleep 3s
Type "# When video is longer, it trims to match the audio length"
Enter
Sleep 3s

Type "# Compose all segments"
Enter
Sleep 2s

Type "docgen compose"
Enter
Sleep 8s

Type "# After composing, validation runs automatically"
Enter
Sleep 3s

Type "# Validate checks every recording for three things:"
Enter
Sleep 2s
Type "#   1. Audio and video streams are present"
Enter
Sleep 2s
Type "#   2. Duration drift between streams is within threshold"
Enter
Sleep 2s
Type "#   3. Narration source file passes lint"
Enter
Sleep 3s

Type "docgen validate"
Enter
Sleep 6s

Type "# Pre-push mode: strict gate for CI"
Enter
Sleep 2s

Type "docgen validate --pre-push"
Enter
Sleep 5s

Type "# Exits non-zero on any failure"
Enter
Sleep 3s

Type "# Standalone narration lint"
Enter
Sleep 2s

Type "docgen lint"
Enter
Sleep 4s

Type "# Finally, Concat assembles segments into a full demo"
Enter
Sleep 2s

Type "docgen concat"
Enter
Sleep 5s

Type "# Multiple concat targets are supported (core demo, extended, etc.)"
Enter
Sleep 3s

Type "# All checks pass — safe to push"
Enter
Sleep 4s
