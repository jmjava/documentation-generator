# Issue: Local Model Support (Ollama)

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** Medium
**Depends on:** Issue 11 (provider abstraction)

## Summary

Implement an `OllamaProvider` that enables docgen to use locally-running LLMs via Ollama for narration generation and chat, reducing cost and removing the OpenAI API dependency for text generation tasks.

## Background

Ollama (`ollama.ai`) runs open-source LLMs locally. For many docgen tasks — narration drafting, narration revision, error diagnosis, script generation — a capable local model (Llama 3.2, Mistral, CodeLlama) may be sufficient, especially for iteration and development.

TTS and Whisper transcription still require OpenAI (or equivalent cloud service) since local TTS quality is not yet competitive for professional narration, but text generation can run fully local.

## Acceptance Criteria

- [ ] `OllamaProvider` implementation using Ollama REST API:
  ```python
  class OllamaProvider:
      def __init__(self, url: str = "http://localhost:11434", model: str = "llama3.2"):
          ...

      def chat(self, model, messages, **kwargs) -> str:
          # POST /api/chat
          ...

      def tts(self, model, voice, text, instructions, output_path):
          # Falls back to OpenAI
          raise NotImplementedError("Use OpenAI for TTS")

      def transcribe(self, model, audio_path, **kwargs):
          # Falls back to OpenAI or local whisper.cpp
          raise NotImplementedError("Use OpenAI for transcription")
  ```
- [ ] Config in `docgen.yaml`:
  ```yaml
  ai:
    provider: ollama
    ollama_url: http://localhost:11434
    ollama_model: llama3.2
    # TTS/transcription still use OpenAI even with Ollama chat
    tts_provider: openai
    transcribe_provider: openai
  ```
- [ ] Hybrid provider support: Ollama for chat, OpenAI for TTS + transcription
- [ ] Test with common local models: llama3.2, mistral, codellama
- [ ] Streaming support for chat responses
- [ ] Auto-detect Ollama availability on startup
- [ ] Document setup instructions:
  ```bash
  # Install Ollama
  curl -fsSL https://ollama.ai/install.sh | sh
  # Pull a model
  ollama pull llama3.2
  # Configure docgen
  # docgen.yaml: ai.provider: ollama
  ```
- [ ] Performance note in docs: first invocation pulls model (may take minutes), subsequent calls are fast

## Technical Notes

### Ollama REST API

```python
import requests

response = requests.post(
    "http://localhost:11434/api/chat",
    json={
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
        ],
        "stream": False,
    },
)
result = response.json()
text = result["message"]["content"]
```

### Hybrid provider pattern

```python
class HybridProvider:
    """Uses different providers for different capabilities."""

    def __init__(self, chat_provider, tts_provider, transcribe_provider):
        self.chat = chat_provider
        self.tts = tts_provider
        self.transcribe = transcribe_provider
```

This naturally handles the case where chat goes to Ollama but TTS goes to OpenAI.

### Local Whisper alternative

For full offline support, we could optionally integrate `whisper.cpp` or `faster-whisper` for local transcription. This is a stretch goal — OpenAI Whisper is cheap and reliable.

## Files to Create/Modify

- **Modify:** `src/docgen/ai_provider.py` (add OllamaProvider, HybridProvider)
- **Modify:** `src/docgen/config.py` (add per-capability provider config)
- **Create:** `tests/test_ollama_provider.py`
- **Modify:** `README.md` (Ollama setup instructions)
