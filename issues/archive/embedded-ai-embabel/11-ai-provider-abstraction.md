# Issue: AI Provider Abstraction Layer

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** Critical (prerequisite for all other Embabel work)
**Depends on:** None

## Summary

Create an `AIProvider` abstraction layer that decouples docgen from direct OpenAI API calls. This enables switching between providers (OpenAI, Embabel via MCP, Ollama for local models) via configuration, and is the prerequisite for all Embabel integration work.

## Background

Today, docgen has three hard-coded OpenAI integration points:

| File | API | Model | Purpose |
|------|-----|-------|---------|
| `wizard.py` | `chat.completions.create` | `gpt-4o` (configurable) | Narration generation |
| `tts.py` | `audio.speech.create` | `gpt-4o-mini-tts` (configurable) | Text-to-speech |
| `timestamps.py` | `audio.transcriptions.create` | `whisper-1` (hard-coded) | Audio timestamps |

Each creates its own `openai.OpenAI()` client. There is no abstraction layer, no provider switching, and no support for non-OpenAI backends.

## Acceptance Criteria

- [ ] Create `AIProvider` protocol with methods:
  ```python
  class AIProvider(Protocol):
      def chat(self, model: str, messages: list[dict], **kwargs) -> str: ...
      def tts(self, model: str, voice: str, text: str, instructions: str, output_path: Path) -> Path: ...
      def transcribe(self, model: str, audio_path: Path, **kwargs) -> dict: ...
  ```
- [ ] Implement `OpenAIProvider` wrapping all current direct calls
- [ ] Implement `EmbabelProvider` that connects via MCP Python SDK to Embabel server
- [ ] Implement `OllamaProvider` for local model support:
  - Chat: Ollama REST API (`/api/chat`)
  - TTS: falls back to OpenAI (Ollama doesn't support TTS)
  - Transcribe: falls back to OpenAI or local `whisper.cpp`
- [ ] Factory function: `get_ai_provider(config) -> AIProvider`
- [ ] Config in `docgen.yaml`:
  ```yaml
  ai:
    provider: openai              # "openai", "embabel", "ollama"
    embabel_url: http://localhost:8080/sse
    ollama_url: http://localhost:11434
    ollama_model: llama3.2
  ```
- [ ] Refactor all three call sites to use `AIProvider`:
  - `wizard.py:generate_narration_via_llm` → `provider.chat(...)`
  - `tts.py:TTSGenerator.generate` → `provider.tts(...)`
  - `timestamps.py:TimestampExtractor.extract` → `provider.transcribe(...)`
- [ ] Backward compatible: no config = default to `openai` with existing behavior
- [ ] Make `whisper-1` model configurable (currently hard-coded in `timestamps.py`)
- [ ] Unit tests with mock providers for each implementation

## Technical Notes

### Provider resolution order

1. Explicit `ai.provider` in `docgen.yaml` → use that
2. `DOCGEN_AI_PROVIDER` environment variable → override
3. Default → `openai`

### EmbabelProvider sketch

```python
class EmbabelProvider:
    def __init__(self, url: str):
        self.url = url
        self._client = None  # lazy MCP client

    async def _connect(self):
        from mcp import ClientSession
        # Connect to Embabel SSE endpoint
        ...

    def chat(self, model, messages, **kwargs):
        # Invoke Embabel NarrationAgent tool via MCP
        return self._call_tool("generate_narration", {...})

    def tts(self, model, voice, text, instructions, output_path):
        # Invoke Embabel TTSAgent tool via MCP, or fall back to OpenAI
        ...
```

### Narration lint impact

`NarrationLinter.lint_audio` in `narration_lint.py` also uses `TimestampExtractor` indirectly — it will automatically benefit from the provider abstraction without code changes.

## Files to Create/Modify

- **Create:** `src/docgen/ai_provider.py`
- **Modify:** `src/docgen/wizard.py` (use provider instead of direct openai)
- **Modify:** `src/docgen/tts.py` (use provider instead of direct openai)
- **Modify:** `src/docgen/timestamps.py` (use provider instead of direct openai)
- **Modify:** `src/docgen/config.py` (add `ai` config block)
- **Create:** `tests/test_ai_provider.py`
