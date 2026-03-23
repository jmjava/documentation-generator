# docgen CI integration — full pipeline overview
# Target ~88s to match 92s audio
Output rendered/06-ci-integration.mp4

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

Type "# DocGen fits into your existing development workflow"
Enter
Sleep 3s

Type "# The wrapper scripts delegate to docgen"
Enter
Sleep 2s

Type "head -12 docs/demos/generate-all.sh"
Enter
Sleep 5s

Type "head -12 docs/demos/validate.sh"
Enter
Sleep 5s

Type "# Pre-push hook validates on every push"
Enter
Sleep 3s

Type "grep -A8 docgen-validate .pre-commit-config.yaml"
Enter
Sleep 5s

Type "# Stream presence, drift, and narration lint checked in under 3 seconds"
Enter
Sleep 4s

Type "# For GitHub Actions, the CI workflow runs lint + tests + E2E"
Enter
Sleep 3s

Type "head -30 .github/workflows/ci.yml"
Enter
Sleep 6s

Type "# E2E tests launch a real Flask server and test the wizard GUI"
Enter
Sleep 4s

Type "# Run the full test suite"
Enter
Sleep 2s

Type "python3 -m pytest tests/ --ignore=tests/e2e -v --tb=short 2>&1 | tail -25"
Enter
Sleep 8s

Type "# The full pipeline is designed for reproducibility"
Enter
Sleep 3s

Type "# Same narration + same visual sources = identical output"
Enter
Sleep 3s

Type "# Wrapper scripts mean everyone uses the same commands"
Enter
Sleep 3s

Type "# generate-all.sh, compose.sh, validate.sh all delegate to docgen"
Enter
Sleep 3s

Type "# That is the full loop: write → generate → validate → push"
Enter
Sleep 4s

Type "# New team members install docgen, run the scripts, and everything works"
Enter
Sleep 4s
