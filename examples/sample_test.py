"""Sample test demonstrating the @pytest.mark.docgen(...) marker shape.

The marker is read statically by `docgen demo-function --manifest <file>::<test>`
via `ast` (no import / no exec). The keyword args mirror the YAML keys.

Note: this file does NOT need pytest to be installed at read time — the marker
is parsed from source. The triple-quoted text below intentionally talks about
``pytest.mark.docgen`` to verify the AST-based loader is not fooled by
docstring text (regression guard for F7).
"""

import pytest


@pytest.mark.docgen(
    identifier="course-builder/src/lessons/compileLesson.ts:compileLesson",
    intent="Compiles a lesson markdown file into structured checkpoints and emits a status badge.",
    setup={"fixtures": ["tests/fixtures/lessons/intro.md"]},
    demonstration={
        "kind": "playwright",
        "url": "http://127.0.0.1:3000/lessons/new",
        "actions": [
            {
                "kind": "type",
                "selector": '[data-testid="title"]',
                "value": "Intro to TS",
                "delay_ms": 30,
                "say": "We name the lesson — Intro to TS.",
            },
            {
                "kind": "click",
                "selector": '[data-testid="compile"]',
                "say": "Clicking compile runs the lesson generator.",
            },
            {
                "kind": "wait_for_text",
                "selector": '[data-testid="status"]',
                "text": "compiled",
                "timeout_ms": 10000,
                "say": "When the status badge flips to compiled the lesson is ready.",
            },
            {"kind": "wait", "ms": 600},
        ],
    },
    assertions_to_surface=[
        "lesson.status === 'compiled'",
        "checkpoint count = 3",
    ],
    output_budget={
        "duration_seconds": 30,
        "segments": 1,
        "resolution": "1280x720",
        # 0.7 = play back at 70% speed; narration clips stay at natural pace
        # and are placed at `t_action / playback_speed_factor` in the slowed
        # timeline. See docs/demo-function.md.
        "playback_speed_factor": 0.7,
    },
)
def test_lesson_compile():
    """Render the compileLesson demo (sample for docgen demo-function)."""
    pass
