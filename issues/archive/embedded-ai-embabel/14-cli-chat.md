# Issue: CLI Chat Interface

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** Medium
**Depends on:** Issue 11 (provider abstraction), Issue 13 (MCP client)

## Summary

Add a `docgen chat` CLI command that provides a terminal-based conversational interface for interacting with the AI agent. Users can generate narration, run pipeline steps, diagnose errors, and iterate on their demo videos through natural language.

## Background

Currently, docgen requires users to know specific CLI commands and their flags. A chat interface lets users describe what they want in natural language, and the AI agent translates that into the appropriate tool calls. This is especially valuable for:

- New users exploring docgen capabilities
- Iterating on narration ("make it more conversational", "shorten this section")
- Debugging pipeline failures ("what went wrong?", "why is the video frozen?")
- Generating code ("write a Playwright capture script for the login flow")

## Acceptance Criteria

- [ ] New CLI command: `docgen chat [--provider embabel|openai|ollama]`
- [ ] Terminal-based conversational loop with colored prompt:
  ```
  docgen> generate narration for segment 03 about the wizard setup flow
  [Agent] I'll generate narration for segment 03. Let me check the source documents...
  [Tool: generate_narration] Using sources: docs/setup.md, README.md
  [Agent] Here's the draft narration:

  "The docgen wizard provides a local web interface for bootstrapping narration scripts..."

  Would you like me to save this to narration/03-wizard-gui.md?

  docgen> yes, and make it shorter

  [Agent] I'll revise the narration to be more concise...
  ```
- [ ] Support natural language commands mapping to tools:
  - "generate narration for segment 03" → `generate_narration` tool
  - "run TTS" → `run_tts` tool
  - "run the full pipeline" → `run_pipeline` tool
  - "what went wrong with compose?" → `diagnose_error` tool
  - "write a capture script for test_login.py" → `generate_capture_script` tool
- [ ] Stream responses token-by-token for natural feel
- [ ] Maintain conversation history within session
- [ ] Tool call visualization with status indicators
- [ ] Handle multi-turn conversations with context
- [ ] Exit with `/quit`, `/exit`, or Ctrl+C
- [ ] Special commands:
  - `/help` — show available commands and examples
  - `/status` — show current project state (segments, which have audio, etc.)
  - `/clear` — clear conversation history
  - `/provider` — show/switch active AI provider
- [ ] `--non-interactive` mode for scripted usage:
  ```bash
  echo "generate narration for 03" | docgen chat --non-interactive
  ```

## Technical Notes

### Chat loop architecture

```python
@main.command()
@click.option("--provider", default=None)
@click.pass_context
def chat(ctx, provider):
    cfg = ctx.obj["config"]
    ai = get_ai_provider(cfg, override_provider=provider)

    history = []
    while True:
        user_input = click.prompt("docgen", prompt_suffix="> ")
        if user_input.strip() in ("/quit", "/exit"):
            break

        history.append({"role": "user", "content": user_input})
        response = ai.chat(
            model=cfg.chat_model,
            messages=[SYSTEM_PROMPT, *history],
            tools=get_docgen_tools(cfg),
        )
        # Handle tool calls, stream response
        ...
```

### System prompt

The chat system prompt should include:
- docgen project context (segments, visual_map, current state)
- Available tools and their descriptions
- Instructions for being helpful with demo video creation

## Files to Create/Modify

- **Modify:** `src/docgen/cli.py` (add `chat` command)
- **Create:** `src/docgen/chat.py` (chat loop, history, tool handling)
- **Create:** `tests/test_chat.py`
