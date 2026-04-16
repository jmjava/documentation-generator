# Issue: Script Generation Agent

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** Low (high value, but requires mature agent infrastructure)
**Depends on:** Issue 12 (Embabel agents), Issue 14 or 15 (chat interface)

## Summary

Implement an Embabel agent (and corresponding Python integration) that generates Playwright capture scripts and Manim scene code from natural language descriptions, test file analysis, and segment narration.

## Background

Today, writing Playwright capture scripts or Manim scenes requires manual coding. The Script Generation Agent automates this by:
1. Analyzing existing test files to understand the UI flow
2. Reading the narration to know what needs to be demonstrated
3. Generating code that follows the `PlaywrightRunner` contract (writes MP4 to `DOCGEN_PLAYWRIGHT_OUTPUT`)
4. Iterating based on user feedback ("make the animation slower", "add a highlight on the login button")

## Acceptance Criteria

- [ ] Embabel `ScriptAgent` that generates Playwright capture scripts:
  - Input: test file path, segment narration, desired demo flow description
  - Output: Python script compatible with `PlaywrightRunner` contract
  - Validates generated code: syntax check, import verification
- [ ] Generate Manim scene code from narration + segment description:
  - Input: segment narration, description of desired animation
  - Output: Python Manim scene class compatible with `ManimRunner`
  - Includes timing from `timing.json` for sync
- [ ] Iterative refinement via chat:
  - "make the animation slower"
  - "add a highlight on the login button"
  - "show the dashboard loading state"
- [ ] Template library for common patterns:
  - Form fill + submit
  - Navigation + page transition
  - Dashboard overview with scroll
  - Terminal command execution
  - Architecture diagram animation
- [ ] Generated code includes appropriate imports and follows project conventions
- [ ] Python-side wrapper for invoking the agent via MCP

## Technical Notes

### Script generation prompt structure

```
System: You are a code generation agent for docgen. Generate {Playwright/Manim} scripts that:
1. Follow the contract: {contract details}
2. Demonstrate the flow described in the narration
3. Use timing from timing.json for synchronization
4. Include error handling and cleanup

User: Generate a Playwright capture script for segment 03 (wizard setup).
Narration: "The wizard provides a local web interface..."
Test reference: tests/e2e/test_setup_view.py
```

### Validation loop

```python
def generate_and_validate(description, narration, test_ref):
    code = agent.generate_script(description, narration, test_ref)
    # Syntax check
    try:
        compile(code, "<generated>", "exec")
    except SyntaxError as e:
        code = agent.fix_syntax(code, str(e))
    # Import check
    missing = check_imports(code)
    if missing:
        code = agent.fix_imports(code, missing)
    return code
```

## Files to Create/Modify

- **Modify:** `docgen-agent/` (add ScriptAgent if using Embabel)
- **Create:** `src/docgen/script_generator.py` (Python-side integration)
- **Create:** `src/docgen/templates/` (script templates for common patterns)
- **Create:** `tests/test_script_generator.py`
