"""Interactive chat interface for docgen — conversational pipeline control.

``docgen chat`` provides a terminal-based conversational interface backed by
the active AI provider.  Users can generate narration, run pipeline steps,
diagnose errors, and iterate on demo videos through natural language.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.ai_provider import AIProvider
    from docgen.config import Config

_SYSTEM_PROMPT = """\
You are an AI assistant for **docgen**, a Python CLI tool that generates \
narrated demo videos from Markdown, Manim animations, VHS terminal recordings, \
and Playwright browser captures.

You help users with:
- Writing and revising narration scripts for demo segments
- Configuring docgen.yaml (visual_map, segments, TTS settings)
- Running pipeline steps (tts, manim, vhs, compose, validate, concat)
- Diagnosing errors (FREEZE GUARD, A/V drift, missing files)
- Generating Playwright capture scripts or Manim scene code

When the user asks you to perform an action, explain what you would do and \
provide the relevant docgen command. When asked about their project, use the \
context provided.

Keep responses concise and actionable. Use code blocks for commands and config."""


def _build_context(config: Config | None) -> str:
    """Build project context to include in the system prompt."""
    if not config:
        return ""

    parts = ["", "## Current project context"]

    segments = config.segments_all
    if segments:
        names = [f"  {s}: {config.resolve_segment_name(s)}" for s in segments]
        parts.append(f"Segments ({len(segments)}):")
        parts.extend(names)

    vmap = config.visual_map
    if vmap:
        parts.append("Visual map:")
        for seg_id, vm in vmap.items():
            parts.append(f"  {seg_id}: type={vm.get('type', 'vhs')}")

    if config.narration_dir.exists():
        narr_files = list(config.narration_dir.glob("*.md"))
        parts.append(f"Narration files: {len(narr_files)}")

    if config.audio_dir.exists():
        audio_files = list(config.audio_dir.glob("*.mp3"))
        parts.append(f"Audio files: {len(audio_files)}")

    if config.recordings_dir.exists():
        rec_files = list(config.recordings_dir.glob("*.mp4"))
        parts.append(f"Recording files: {len(rec_files)}")

    return "\n".join(parts)


def run_chat(
    config: Config | None,
    provider: AIProvider,
    *,
    non_interactive: bool = False,
    model: str | None = None,
) -> None:
    """Run the interactive chat loop."""
    context = _build_context(config)
    system_message = _SYSTEM_PROMPT + context

    history: list[dict[str, str]] = [
        {"role": "system", "content": system_message},
    ]

    chat_model = model
    if not chat_model and config:
        chat_model = config.ai_config.get("chat_model") or config.wizard_config.get("llm_model")

    if non_interactive:
        _run_non_interactive(provider, history, chat_model)
        return

    print("docgen chat — type /help for commands, /quit to exit")
    print()

    while True:
        try:
            user_input = input("docgen> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            if _handle_slash_command(user_input, config, history):
                continue
            else:
                break

        history.append({"role": "user", "content": user_input})

        try:
            response = provider.chat(
                messages=history,
                model=chat_model,
                temperature=0.7,
            )
        except Exception as exc:
            print(f"\n[error] AI provider call failed: {exc}\n")
            history.pop()
            continue

        history.append({"role": "assistant", "content": response})
        print(f"\n{response}\n")


def _run_non_interactive(
    provider: AIProvider,
    history: list[dict[str, str]],
    model: str | None,
) -> None:
    """Read stdin, send one message, print response, exit."""
    user_input = sys.stdin.read().strip()
    if not user_input:
        return

    history.append({"role": "user", "content": user_input})
    try:
        response = provider.chat(messages=history, model=model, temperature=0.7)
        print(response)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_slash_command(
    cmd: str,
    config: Config | None,
    history: list[dict[str, str]],
) -> bool:
    """Handle slash commands. Return True to continue loop, False to exit."""
    cmd_lower = cmd.lower().strip()

    if cmd_lower in ("/quit", "/exit", "/q"):
        print("Bye!")
        return False

    if cmd_lower == "/help":
        print("""
Commands:
  /help     — show this help
  /status   — show project status
  /clear    — clear conversation history
  /quit     — exit chat

You can also ask in natural language:
  "generate narration for segment 03"
  "what went wrong with compose?"
  "write a Playwright capture script for the login flow"
""")
        return True

    if cmd_lower == "/status":
        if not config:
            print("  No docgen.yaml found.")
        else:
            print(f"  Config: {config.yaml_path}")
            print(f"  Segments: {', '.join(config.segments_all)}")
            for seg_id in config.segments_all:
                name = config.resolve_segment_name(seg_id)
                has_narr = "✓" if (config.narration_dir / f"{name}.md").exists() else "·"
                has_audio = "✓" if (config.audio_dir / f"{name}.mp3").exists() else "·"
                has_rec = "✓" if (config.recordings_dir / f"{name}.mp4").exists() else "·"
                vtype = config.visual_map.get(seg_id, {}).get("type", "?")
                print(f"    {seg_id} ({name}): narr={has_narr} audio={has_audio} rec={has_rec} type={vtype}")
            ai_cfg = config.ai_config
            print(f"  AI provider: {ai_cfg.get('provider', 'openai')}")
        return True

    if cmd_lower == "/clear":
        system = history[0] if history else {"role": "system", "content": _SYSTEM_PROMPT}
        history.clear()
        history.append(system)
        print("  Conversation cleared.")
        return True

    print(f"  Unknown command: {cmd}. Type /help for available commands.")
    return True
