# docgen validate — validation demo
Output terminal/rendered/05-compose-validate.mp4

Set Shell "bash"
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20

Type "cd docs/demos"
Enter
Sleep 500ms

Type "# Validate all composed recordings"
Enter
Sleep 500ms

Type "docgen validate"
Enter
Sleep 3s

Type "# Pre-push mode: strict gate for CI"
Enter
Sleep 500ms

Type "docgen validate --pre-push"
Enter
Sleep 3s

Type "# Standalone narration lint"
Enter
Sleep 500ms

Type "docgen lint"
Enter
Sleep 2s

Type "# All checks pass — safe to push"
Enter
Sleep 1s
