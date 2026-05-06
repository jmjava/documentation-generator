# Milestone 5 — Embedded AI via Embabel & Chatbot Interface

**Goal:** Remove the dependency on Cursor (or any specific IDE/tool) for AI-powered code and audio generation by embedding our own AI agent layer. Use the Embabel agent framework to provide a chatbot interface that can generate narration scripts, Python capture code, and orchestrate the full docgen pipeline conversationally.

## Motivation

Today, docgen relies on direct OpenAI API calls hard-coded in three places:

1. **`wizard.py`** — `openai.ChatCompletion` for narration generation (model: `gpt-4o`)
2. **`tts.py`** — `openai.audio.speech` for TTS (model: `gpt-4o-mini-tts`)
3. **`timestamps.py`** — `openai.audio.transcriptions` for Whisper timestamps (model: `whisper-1`)

This creates several problems:
- **No provider flexibility** — locked to OpenAI; no Azure, Anthropic, local model support
- **No agent intelligence** — the wizard is a simple request/response; it cannot plan multi-step workflows, use tools, or adapt to user feedback
- **No chatbot interface** — users must use the CLI or the wizard web GUI; there is no conversational interface for iterating on narration, debugging compose failures, or exploring the pipeline
- **IDE dependency** — teams currently rely on Cursor or similar AI-assisted editors to generate the Python capture scripts, Manim scenes, and configuration that docgen needs

Embabel provides a JVM-based agent framework with planning (GOAP), tool use (MCP), and chatbot support. By running Embabel as an MCP server and connecting docgen as a Python MCP client, we get:
- A conversational AI that understands the docgen domain
- Tool-based orchestration of pipeline steps
- Provider abstraction (Embabel supports OpenAI, local models via Ollama, etc.)
- A chatbot UI for non-technical users

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         User Interface                            │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  CLI Chat    │  │  Wizard GUI  │  │  Standalone Chatbot UI │  │
│  │  docgen chat │  │  /chat tab   │  │  (Vaadin/React/HTML)   │  │
│  └──────┬──────┘  └──────┬───────┘  └───────────┬────────────┘  │
│         │                │                       │                │
│         └────────────────┼───────────────────────┘                │
│                          │                                        │
│                          ▼                                        │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              docgen Python MCP Client                      │   │
│  │                                                            │   │
│  │  - Connects to Embabel MCP server via SSE                  │   │
│  │  - Discovers available tools (narration, tts, compose...)  │   │
│  │  - Manages conversation state                              │   │
│  │  - Streams responses to UI                                 │   │
│  └───────────────────────┬───────────────────────────────────┘   │
│                          │ MCP (SSE / Streamable HTTP)            │
│                          ▼                                        │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              Embabel Agent (JVM / Spring Boot)              │   │
│  │                                                            │   │
│  │  Agents:                                                   │   │
│  │    NarrationAgent   — draft/revise narration from docs     │   │
│  │    TTSAgent         — generate speech, manage voices       │   │
│  │    PipelineAgent    — orchestrate generate-all steps       │   │
│  │    ScriptAgent      — generate Playwright/Manim code       │   │
│  │    DebugAgent       — diagnose compose/validation errors   │   │
│  │                                                            │   │
│  │  Tools (MCP-exposed):                                      │   │
│  │    @Export generate_narration(segment, guidance, sources)   │   │
│  │    @Export run_tts(segment, voice, model)                   │   │
│  │    @Export run_pipeline(steps, options)                     │   │
│  │    @Export generate_capture_script(test_file, segment)     │   │
│  │    @Export diagnose_error(error_log, segment)              │   │
│  │    @Export suggest_visual_map(project_dir)                 │   │
│  │                                                            │   │
│  │  Planning: GOAP selects optimal action sequence            │   │
│  │  LLM: Configurable — OpenAI, Anthropic, Ollama, Azure     │   │
│  └───────────────────────────────────────────────────────────┘   │
│                          │                                        │
│                          ▼                                        │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │              Existing docgen Pipeline                       │   │
│  │  tts.py, timestamps.py, compose.py, validate.py, etc.     │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Embabel as MCP Server, docgen as MCP Client

Embabel runs as a separate Spring Boot service exposing tools via MCP over SSE. The Python docgen codebase connects as an MCP client using the official `mcp` Python SDK. This keeps the two codebases cleanly separated:

- **Embabel side (JVM):** Agent definitions, planning, LLM abstraction, domain models
- **docgen side (Python):** Pipeline execution, file I/O, ffmpeg, Playwright, existing CLI

### 2. Provider Abstraction Layer

Before Embabel integration, we first need to abstract the current direct OpenAI calls:

```python
# Current (hard-coded):
client = openai.OpenAI()
response = client.chat.completions.create(model="gpt-4o", ...)

# Target (abstracted):
provider = get_ai_provider(config)  # OpenAI, Anthropic, Ollama, or Embabel-via-MCP
response = provider.chat(model=config.llm_model, messages=[...])
```

This abstraction benefits docgen even without Embabel — it enables local model usage, Azure OpenAI, etc.

### 3. Chatbot Interface Options

Three tiers of chatbot integration:

1. **CLI chat** (`docgen chat`) — terminal-based conversational interface using the MCP client
2. **Wizard chat tab** — add a `/chat` endpoint and chat panel to the existing Flask wizard
3. **Standalone chatbot UI** — Embabel's Vaadin-based chatbot template or a custom React/HTML frontend

### 4. Progressive Enhancement

The Embabel integration is additive, not a rewrite:
- All existing CLI commands continue to work
- Direct OpenAI calls remain as the default provider
- Embabel is an optional backend activated via config
- The chatbot is a new interface, not a replacement for the wizard

## Items

### Issue 11: AI Provider Abstraction Layer (`ai_provider.py`)
- [ ] Create `AIProvider` protocol/interface with methods: `chat()`, `tts()`, `transcribe()`
- [ ] Implement `OpenAIProvider` wrapping current direct calls
- [ ] Implement `EmbabelProvider` connecting via MCP client to Embabel server
- [ ] Implement `OllamaProvider` for local model support (chat only; TTS falls back to OpenAI)
- [ ] Config: `ai.provider` in `docgen.yaml` (`openai`, `embabel`, `ollama`)
- [ ] Config: `ai.embabel_url` for MCP server endpoint (default `http://localhost:8080/sse`)
- [ ] Config: `ai.ollama_url` for local Ollama endpoint (default `http://localhost:11434`)
- [ ] Refactor `wizard.py`, `tts.py`, `timestamps.py` to use `AIProvider` instead of direct `openai` calls
- [ ] Maintain backward compatibility: if no provider configured, default to `openai` with existing behavior
- [ ] Unit tests with mock providers

### Issue 12: Embabel Agent Definitions (JVM Side)
- [ ] Create Embabel Spring Boot project (`docgen-agent/`) in repo or as a companion repo
- [ ] Define domain model classes: `NarrationRequest`, `TTSRequest`, `PipelineRequest`, `ScriptRequest`
- [ ] Implement `NarrationAgent` — accepts source docs + guidance, generates narration via LLM
- [ ] Implement `TTSAgent` — wraps TTS generation with voice/model selection
- [ ] Implement `PipelineAgent` — orchestrates multi-step pipeline via GOAP planning
- [ ] Implement `ScriptAgent` — generates Playwright capture scripts or Manim scene code
- [ ] Implement `DebugAgent` — analyzes compose/validation errors and suggests fixes
- [ ] Export all agent goals as MCP tools with `@Export(remote = true)`
- [ ] Configure LLM mixing: use GPT-4o for narration, local model for simple classification
- [ ] Docker Compose setup for running Embabel alongside docgen
- [ ] Integration tests verifying MCP tool discovery and invocation

### Issue 13: Python MCP Client Integration (`mcp_client.py`)
- [ ] Add `mcp` Python SDK as optional dependency (`pip install docgen[embabel]`)
- [ ] Implement `EmbabelClient` class wrapping MCP `ClientSession`
- [ ] Connect to Embabel SSE endpoint with auto-reconnect
- [ ] Discover available tools on connection
- [ ] Implement tool invocation wrappers for each agent tool
- [ ] Handle streaming responses for chat interactions
- [ ] Connection health checking and graceful degradation (fall back to direct OpenAI if Embabel unavailable)
- [ ] Config integration: read `ai.embabel_url` from `docgen.yaml`
- [ ] Unit tests with mocked MCP server

### Issue 14: CLI Chat Interface (`docgen chat`)
- [ ] New CLI command: `docgen chat [--provider embabel|openai|ollama]`
- [ ] Terminal-based conversational loop with prompt
- [ ] Support natural language commands: "generate narration for segment 03", "run the pipeline", "what went wrong with compose?"
- [ ] Stream responses token-by-token to terminal
- [ ] Maintain conversation history within session
- [ ] Tool call visualization: show when the agent invokes pipeline tools
- [ ] Handle multi-turn conversations with context
- [ ] Exit with `/quit`, `/exit`, or Ctrl+C
- [ ] `--non-interactive` mode for scripted usage: `echo "generate narration for 03" | docgen chat`

### Issue 15: Wizard Chatbot Panel
- [ ] Add `/chat` route to Flask wizard
- [ ] Add chat panel UI to `wizard.html` (collapsible sidebar or tab)
- [ ] Server-Sent Events (SSE) endpoint for streaming chat responses
- [ ] Chat can reference current segment context (active tab in wizard)
- [ ] Support commands: "revise this narration to be more conversational", "generate TTS for this segment", "what's wrong with the compose output?"
- [ ] Show agent tool calls in chat (e.g., "Running TTS... done" with progress)
- [ ] Persist chat history per session
- [ ] Degrade gracefully: if no AI provider configured, show helpful setup message

### Issue 16: Script Generation Agent
- [ ] Embabel agent that generates Playwright capture scripts from test file analysis
- [ ] Input: test file path, segment narration, desired demo flow
- [ ] Output: Python script compatible with `PlaywrightRunner` contract (writes MP4 to `DOCGEN_PLAYWRIGHT_OUTPUT`)
- [ ] Generate Manim scene code from narration + segment description
- [ ] Validate generated code: syntax check, import verification
- [ ] Iterative refinement: "make the animation slower", "add a highlight on the login button"
- [ ] Template library: common patterns (form fill, navigation, dashboard overview)

### Issue 17: Error Diagnosis Agent
- [ ] Embabel agent that analyzes pipeline errors and suggests fixes
- [ ] Input: error log, segment config, pipeline state
- [ ] Handles: FREEZE GUARD, missing audio, ffmpeg failures, Playwright timeouts, VHS errors
- [ ] Suggests concrete fixes: "your Manim scene is 5s shorter than narration, add a 5s wait at the end"
- [ ] Can auto-fix common issues when given permission
- [ ] Integrates with `docgen validate` output for proactive suggestions

### Issue 18: Local Model Support (Ollama)
- [ ] `OllamaProvider` implementation using Ollama REST API
- [ ] Support chat/completion for narration generation
- [ ] TTS fallback to OpenAI (Ollama doesn't do TTS natively)
- [ ] Whisper fallback to OpenAI or local whisper.cpp
- [ ] Config: `ai.ollama_model` (default: `llama3.2`)
- [ ] Test with common local models: llama3.2, mistral, codellama
- [ ] Document setup instructions for Ollama

## Integration with Milestone 4 (Playwright Test Video)

The Embabel agents enhance the Playwright test video integration from Milestone 4:

- **ScriptAgent** can analyze existing Playwright tests and generate the `visual_map` configuration
- **ScriptAgent** can generate narration anchor mappings by reading test selectors and suggesting matching phrases
- **DebugAgent** can diagnose sync issues between test video events and narration timing
- **PipelineAgent** orchestrates the full test-to-video flow conversationally

## Dependencies

- Embabel Agent Framework 0.3.x (JVM, Spring Boot)
- MCP Python SDK (`mcp` on PyPI)
- Java 21+ runtime (for Embabel)
- Docker (optional, for containerized Embabel deployment)

## Risks

- **Operational complexity**: Running a JVM service alongside a Python CLI adds deployment burden. Mitigation: Docker Compose, optional activation, graceful fallback.
- **Embabel maturity**: Framework is relatively new (Rod Johnson / Spring lineage, but early versions). Mitigation: thin integration layer, easy to swap for alternative MCP server.
- **Latency**: MCP round-trips add latency vs direct API calls. Mitigation: async operations, streaming, caching.
- **Model quality for code generation**: LLM-generated Playwright/Manim code may need iteration. Mitigation: validation loops, template library, human review step.
