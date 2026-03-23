# docgen CI integration — full pipeline overview
Output terminal/rendered/06-ci-integration.mp4

Set Shell "bash"
Set FontSize 14
Set Width 1280
Set Height 720
Set Padding 20

Type "# The wrapper scripts delegate to docgen"
Enter
Sleep 500ms

Type "head -8 docs/demos/generate-all.sh"
Enter
Sleep 2s

Type "head -8 docs/demos/validate.sh"
Enter
Sleep 2s

Type "# Pre-push hook validates on every push"
Enter
Sleep 500ms

Type "grep -A5 docgen-validate .pre-commit-config.yaml"
Enter
Sleep 2s

Type "# Run the full test suite"
Enter
Sleep 500ms

Type "python3 -m pytest tests/ --ignore=tests/e2e -v --tb=short 2>&1 | tail -20"
Enter
Sleep 4s

Type "# 50 tests, all green"
Enter
Sleep 1s
