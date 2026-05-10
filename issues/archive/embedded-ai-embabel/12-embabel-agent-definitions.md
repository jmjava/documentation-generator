# Issue: Embabel Agent Definitions (JVM Side)

**Milestone:** 5 — Embedded AI via Embabel & Chatbot Interface
**Priority:** High
**Depends on:** Issue 11 (provider abstraction)

## Summary

Create the Embabel Spring Boot application that hosts the AI agents for docgen. These agents are exposed as MCP tools that the Python docgen client can invoke for narration generation, TTS orchestration, pipeline management, script generation, and error diagnosis.

## Background

Embabel is a JVM-based agent framework that uses Goal-Oriented Action Planning (GOAP) to dynamically plan action sequences. By defining docgen-specific agents, we get:

- **Planning**: the agent figures out the optimal sequence of steps (e.g., "to produce a demo video, I need to generate narration, then TTS, then compose...")
- **Tool use**: agents can invoke docgen CLI commands as tools
- **LLM mixing**: use GPT-4o for narration quality, cheaper models for classification
- **MCP exposure**: all agents automatically available to Python via MCP protocol

## Acceptance Criteria

- [ ] Create Embabel Spring Boot project:
  - Option A: `docgen-agent/` subdirectory in this repo
  - Option B: Companion repo `docgen-agent` (linked from README)
- [ ] Domain model classes (Kotlin data classes):
  ```kotlin
  data class NarrationRequest(val segment: String, val guidance: String, val sources: List<String>)
  data class NarrationResponse(val text: String, val wordCount: Int)
  data class TTSRequest(val segment: String, val voice: String, val model: String)
  data class PipelineRequest(val steps: List<String>, val options: Map<String, Any>)
  data class ScriptRequest(val testFile: String, val segment: String, val description: String)
  data class DiagnosisRequest(val errorLog: String, val segment: String, val context: Map<String, Any>)
  ```
- [ ] Agent implementations:
  - `NarrationAgent` — generates/revises narration from source docs + guidance
  - `TTSAgent` — wraps TTS generation with voice/model selection and preview
  - `PipelineAgent` — orchestrates multi-step pipeline via GOAP planning
  - `ScriptAgent` — generates Playwright capture scripts or Manim scene code
  - `DebugAgent` — analyzes compose/validation errors and suggests fixes
- [ ] All agent goals exported as MCP tools: `@Export(remote = true)`
- [ ] LLM configuration:
  - GPT-4o for narration generation (quality-critical)
  - Local model via Ollama for simple classification/routing
  - Configurable in `application.yml`
- [ ] Docker Compose setup for running Embabel alongside docgen:
  ```yaml
  services:
    docgen-agent:
      build: ./docgen-agent
      ports: ["8080:8080"]
      environment:
        - OPENAI_API_KEY=${OPENAI_API_KEY}
        - SPRING_AI_OPENAI_API_KEY=${OPENAI_API_KEY}
  ```
- [ ] Integration tests verifying MCP tool discovery and invocation
- [ ] Health endpoint for connection checking

## Technical Notes

### Agent architecture

Each agent is an `@EmbabelComponent` with `@Action` methods:

```kotlin
@Agent("Narration generation agent for docgen")
class NarrationAgent {

    @Action("Generate narration from source documents")
    @Export(remote = true)
    fun generateNarration(request: NarrationRequest): NarrationResponse {
        // LLM call with docgen-specific system prompt
    }

    @Action("Revise existing narration based on feedback")
    @Export(remote = true)
    fun reviseNarration(segment: String, currentText: String, feedback: String): NarrationResponse {
        // LLM call with revision context
    }
}
```

### MCP server configuration

```yaml
# application.yml
spring:
  ai:
    mcp:
      server:
        type: SYNC
    openai:
      api-key: ${OPENAI_API_KEY}
```

## Files to Create

- **Create:** `docgen-agent/` (Spring Boot project)
  - `pom.xml` or `build.gradle.kts`
  - `src/main/kotlin/com/docgen/agent/`
    - `DocgenAgentApplication.kt`
    - `agents/NarrationAgent.kt`
    - `agents/TTSAgent.kt`
    - `agents/PipelineAgent.kt`
    - `agents/ScriptAgent.kt`
    - `agents/DebugAgent.kt`
    - `model/` (domain classes)
  - `src/main/resources/application.yml`
  - `Dockerfile`
- **Create:** `docker-compose.yml` (root level, optional)
