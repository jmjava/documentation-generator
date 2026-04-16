# Issue: Wizard Chatbot Panel

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** Medium
**Depends on:** Issue 11 (provider abstraction), Issue 13 (MCP client)

## Summary

Add a chat panel to the existing wizard web GUI, allowing users to interact with the AI agent while editing narration and configuring their demo project.

## Background

The wizard (`docgen wizard`) is a Flask-based local web GUI for bootstrapping narration scripts. Adding a chat panel gives users a conversational way to:
- Ask for narration revisions in context ("make this more concise")
- Generate TTS and preview audio from the chat
- Get explanations of pipeline steps
- Debug issues without leaving the GUI

## Acceptance Criteria

- [ ] Add `/api/chat` SSE endpoint to Flask wizard for streaming responses
- [ ] Add `/api/chat/history` endpoint for loading chat history
- [ ] Add chat panel UI to `wizard.html`:
  - Collapsible sidebar (default collapsed) or dedicated tab
  - Message input with send button
  - Message history with user/agent message bubbles
  - Tool call indicators (spinner, "Running TTS...", etc.)
  - Code blocks in agent responses (for generated scripts)
- [ ] Chat is context-aware:
  - Knows which segment is currently active
  - Can reference current narration text
  - Can suggest edits to the active segment
- [ ] Support commands via chat:
  - "revise this narration to be more conversational"
  - "generate TTS for this segment"
  - "what does this segment's visual map look like?"
  - "suggest source documents for segment 03"
- [ ] Show agent tool calls in chat with progress
- [ ] Persist chat history per session (in-memory, reset on server restart)
- [ ] Degrade gracefully: if no AI provider configured, show message with setup instructions
- [ ] Keyboard shortcut to toggle chat panel (e.g., `Ctrl+/`)

## Technical Notes

### SSE endpoint for streaming

```python
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json
    message = data.get("message", "")
    segment = data.get("segment")  # current segment context

    def stream():
        provider = get_ai_provider(cfg)
        for token in provider.chat_stream(model=..., messages=[...]):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(stream(), mimetype="text/event-stream")
```

### Frontend chat component

```javascript
// wizard.js addition
async function sendChatMessage(message) {
    const res = await fetch("/api/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message, segment: activeSegmentId})
    });
    const reader = res.body.getReader();
    // Stream tokens to chat panel...
}
```

## Files to Create/Modify

- **Modify:** `src/docgen/wizard.py` (add chat endpoints)
- **Modify:** `src/docgen/templates/wizard.html` (add chat panel HTML)
- **Modify:** `src/docgen/static/wizard.js` (add chat JS logic)
- **Create/Modify:** `src/docgen/static/wizard.css` (chat panel styles)
