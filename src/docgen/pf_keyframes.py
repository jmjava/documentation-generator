"""Vision-LLM-driven keyframe selection for the audio-driven demo pipeline.

The audio-driven sync flow:

1. Source video is captured at native speed by Playwright.
2. ONE TTS pass renders every ``narration_steps[*].say`` into a single MP3.
3. Whisper word timings give us a per-line ``(start_ms, end_ms)`` window
   inside that MP3 (see :mod:`docgen.pf_align`).
4. **This module** samples candidate frames from the source video and asks
   a vision LLM to pick the one that BEST shows what each narration line
   describes.
5. The renderer concats those chosen stills into a slideshow MP4 — each
   image held for its line's Whisper-aligned duration — and muxes the
   single TTS MP3 under it as the LAST step.

Why a vision LLM (and not "frame at action timestamp")? Playwright's
screencast service has a ~200 ms warmup; very early actions like
``page.goto`` fire before the first frame lands in the WebM, so a
naive timestamp pick would land on the wrong visible state (e.g. typing
already in progress when narration says "Open the home page"). Letting
a vision model match by *meaning* sidesteps the warmup hole entirely:
it just won't pick frames whose visible state contradicts the line.

Cost is bounded: the request is a single batched call (one prompt for
all steps), and candidate count is capped (default 30). Images are sent
at ``detail: "high"`` so the model can actually read input-field text
and small status indicators — at ``detail: "low"`` it confuses
mid-typing prefixes with fully-typed values. For a typical 5-line demo
the incremental cost is small (well under a cent per render).
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VISION_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class KeyframeCandidate:
    """One sampled frame from the source video, in chronological order."""

    path: Path
    t_seconds: float
    index: int


def extract_candidates(
    video: Path,
    work_dir: Path,
    *,
    interval_sec: float = 0.20,
    max_count: int = 30,
) -> list[KeyframeCandidate]:
    """Sample frames from ``video`` at roughly ``interval_sec`` apart.

    ffmpeg is invoked once per timestamp (rather than ``-vf fps=...``) so
    each frame seek is accurate — webm keyframe density is too low for
    the latter to land on a useful frame for short videos.

    Caps at ``max_count`` so the vision call stays bounded for longer
    demos. The first and last frames of the video are always included
    so the LLM has the true "before" and "after" states available.
    """
    _ensure_ffmpeg()
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    duration = _probe_duration_sec(video)
    if duration <= 0:
        raise RuntimeError(
            f"video {video} has zero / unprobeable duration; cannot extract keyframes"
        )

    n = max(2, min(max_count, int(duration / max(interval_sec, 0.05)) + 1))
    if n == 1:
        timestamps = [duration / 2.0]
    else:
        # Span 0 → just-before-end so we always include earliest + latest
        # frames the recording captured.
        last_t = max(0.0, duration - 0.04)
        step = last_t / (n - 1) if n > 1 else 0.0
        timestamps = [round(i * step, 3) for i in range(n)]

    candidates: list[KeyframeCandidate] = []
    for i, t in enumerate(timestamps):
        out_png = work_dir / f"cand_{i:03d}_t{int(t * 1000):05d}.png"
        # ``-ss`` AFTER ``-i`` for accurate per-frame seek (webm keyframes
        # are sparse; fast seek would land on the wrong frame).
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-ss",
            f"{t:.3f}",
            "-frames:v",
            "1",
            str(out_png),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg keyframe extract failed at t={t}: "
                f"{proc.stderr[-400:]}"
            )
        candidates.append(
            KeyframeCandidate(path=out_png, t_seconds=t, index=i)
        )
    return candidates


def match_steps_to_keyframes(
    candidates: list[KeyframeCandidate],
    steps: list[dict[str, Any]],
    *,
    openai_client: Any | None = None,
    model: str = VISION_MODEL,
) -> list[KeyframeCandidate]:
    """Vision LLM picks one candidate per narration step in a single call.

    Sends every candidate image (``detail: "high"``) plus the ordered
    narration list and asks for a strict JSON mapping
    ``{"matches": [{"step": int, "candidate": int}, ...]}``.

    Validation:

    * Returned list must have exactly ``len(steps)`` entries.
    * Every ``candidate`` index must be in ``[0, len(candidates))``.
    * Indices must be monotonically non-decreasing (the demo runs
      forward in time; later lines cannot reuse earlier frames).
      Mild violations are clamped forward; structural violations raise.
    """
    if not steps:
        return []
    if not candidates:
        raise RuntimeError("no candidate keyframes to match")

    try:
        import openai
    except ImportError as exc:  # pragma: no cover - defensive
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            "openai package not available — needed for vision keyframe match",
            install_hint="pip install openai",
        ) from exc

    if openai_client is None:
        openai_client = openai.OpenAI()

    content: list[dict[str, Any]] = [
        {"type": "text", "text": _build_user_prompt(steps, len(candidates))}
    ]
    for c in candidates:
        content.append(_image_block(c.path, c.index))

    try:
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=600,
        )
    except openai.AuthenticationError as exc:
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            f"OpenAI rejected OPENAI_API_KEY for vision: {exc}",
            install_hint=(
                "Set a valid OPENAI_API_KEY whose project has chat-completions "
                f"+ {VISION_MODEL} (vision) access."
            ),
        ) from exc
    except openai.PermissionDeniedError as exc:
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            f"OPENAI_API_KEY lacks vision permissions: {exc}",
            install_hint="Use a key whose project has access to gpt-4o-mini vision.",
        ) from exc
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"OpenAI vision network error: {exc} — re-run when connectivity is "
            "restored."
        ) from exc

    raw = ""
    try:
        raw = resp.choices[0].message.content or "{}"
    except (AttributeError, IndexError) as exc:
        raise RuntimeError(
            f"vision LLM response missing content: {exc}"
        ) from exc

    indices = parse_match_response(
        raw, n_steps=len(steps), n_candidates=len(candidates)
    )
    return [candidates[i] for i in indices]


_SYSTEM_PROMPT = """You match candidate video frames to narration lines for a software demo.

You will receive (1) a numbered, ordered list of narration lines and (2) N candidate frames sampled from one short demo recording, in chronological order.

For each narration line, choose the SINGLE candidate frame that best shows the on-screen state the line describes.

Hard rules — any violation is a bug:
- Return a JSON object EXACTLY of the form: {"matches": [{"step": int, "candidate": int}, ...]}
- Exactly one entry per narration line, ``step`` values 0..M-1 in order.
- ``candidate`` values are 0..N-1 (zero-based; the FIRST image is candidate 0).
- ``candidate`` indices MUST be monotonically non-decreasing across steps.
- No commentary, no markdown, no prose — just the JSON object.

GUIDING PRINCIPLE — pick the SETTLED frame for each line.

A "settled" frame is one where the user-visible STATE described by the line has fully taken effect AND no later action's effect is yet visible. Never pick mid-transition / mid-animation / mid-typing / mid-render frames; never pick a frame that already shows the EFFECT of a later line.

Read the line's verb to figure out what state to look for. The same principle applies regardless of UI framework or widget type:

* Verbs about ARRIVING / OPENING ("opens", "loads", "navigates to", "appears", "is shown")
  → The described element is fully RENDERED and idle. No spinners, no skeletons, no half-loaded content. For a fresh page or view this means inputs are still in their default / empty state, lists are empty (or show their placeholder), counters are at zero, etc. — the "before any user interaction" snapshot.

* Verbs about ENTERING DATA ("types", "enters", "fills in", "writes", "pastes", "selects from dropdown", "uploads", "drags into")
  → The input now contains the FULL target value visibly displayed (whole string in a text field, the chosen option visible in a closed dropdown, the file name shown next to an upload control, the slider thumb at its target value). Reject frames showing only a PREFIX or partial value, an open dropdown menu mid-selection, or any other mid-edit state.

* Verbs about TOGGLING / CHOOSING ("checks", "unchecks", "toggles", "selects radio", "switches on/off", "enables", "disables")
  → The control is in its TARGET state and its visual indicator clearly shows it: checkbox is filled / has a checkmark, radio button has its dot, switch shows the on/off color, toggle's label / aria-state matches.

* Verbs about CLICKING / SUBMITTING / TRIGGERING ("clicks", "presses", "submits", "confirms", "saves", "applies")
  → Prefer a frame just AFTER the click has registered: the button no longer shows its hover / pressed style, its loading indicator (if any) has cleared, but the resulting state-change has not yet rendered downstream. If no such between-frame exists, pick the earliest frame that shows the button's effect.

* Verbs about RESULTS / STATE CHANGES ("the result appears", "shows", "updates", "becomes <state>", "is added", "is removed", "highlighted", "completed", "succeeds", "fails", "error appears")
  → The new content is fully VISIBLE: result text is fully rendered, the new row / list item is present and styled, the status badge / pill shows the new state and color, the error / toast / banner is fully on-screen. Reject frames where the region is still empty, still showing the previous state, still mid-fade-in, or only partially populated.

* Verbs about CLOSING / DISMISSING / DISAPPEARING ("closes", "dismisses", "hides", "collapses", "is removed")
  → The element is GONE from the frame (or fully collapsed), and the surrounding layout has settled into its new arrangement.

When two or more candidates equally satisfy a line, pick the EARLIEST one — closer to the action's natural moment in the recording — unless an even earlier frame is the one settling out a previous line."""


def _build_user_prompt(
    steps: list[dict[str, Any]], n_candidates: int
) -> str:
    """Render the narration list as the text portion of the user message."""
    lines = [
        f"Candidates: {n_candidates} frames in chronological order, "
        "indexed 0..{n_minus_1} (0 = earliest, {n_minus_1} = latest).".format(
            n_minus_1=n_candidates - 1
        ),
        "",
        "Narration lines (in order):",
    ]
    for i, s in enumerate(steps):
        api = str(s.get("api_name") or "?")
        say = str(s.get("say") or "").strip()
        lines.append(f'  {i}. ({api}) "{say}"')
    return "\n".join(lines)


def _image_block(path: Path, idx: int) -> dict[str, Any]:
    """Encode ``path`` as an image_url chat content block.

    We send candidates at ``detail: "high"`` because the discriminating
    differences between adjacent frames in a UI demo are typically small
    (a few characters in a text input, a checkbox state, a status
    badge). At ``detail: "low"`` the image is downsampled to a 512px
    thumbnail before the model sees it — too coarse to read input field
    text reliably, which causes the matcher to pick mid-typing frames
    over fully-typed ones. The token cost is bounded: the matcher caps
    candidate count at ``extract_candidates(max_count=...)`` and the
    request is a single batched call per render.
    """
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{data}",
            "detail": "high",
        },
    }


def parse_match_response(
    raw: str, *, n_steps: int, n_candidates: int
) -> list[int]:
    """Parse + validate the vision LLM's JSON, returning the indices.

    Returns ``[candidate_index_for_step_0, ..., candidate_index_for_step_M-1]``.
    Raises with the offending raw output on any structural error.
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"vision LLM returned non-JSON: {raw[:300]}"
        ) from exc
    if not isinstance(obj, dict):
        raise RuntimeError(f"vision LLM JSON not an object: {raw[:300]}")
    matches = obj.get("matches")
    if not isinstance(matches, list):
        raise RuntimeError(
            f"vision LLM JSON missing/invalid 'matches' list: {raw[:300]}"
        )
    if len(matches) != n_steps:
        raise RuntimeError(
            f"vision LLM returned {len(matches)} matches, expected {n_steps}"
        )

    result = [-1] * n_steps
    last_cand = -1
    for m in matches:
        if not isinstance(m, dict):
            raise RuntimeError(f"match entry not an object: {m!r}")
        step = m.get("step")
        cand = m.get("candidate")
        if not isinstance(step, int) or not (0 <= step < n_steps):
            raise RuntimeError(f"step index out of range or not int: {m!r}")
        if not isinstance(cand, int) or not (0 <= cand < n_candidates):
            raise RuntimeError(
                f"candidate index out of range or not int: {m!r}"
            )
        if cand < last_cand:
            # Soft repair: clamp forward instead of erroring out. The vision
            # model occasionally returns adjacent indices in slightly wrong
            # order; preserving monotonicity preserves a watchable demo.
            cand = last_cand
        result[step] = cand
        last_cand = cand

    missing = [i for i, c in enumerate(result) if c < 0]
    if missing:
        raise RuntimeError(
            f"vision LLM did not assign candidates for steps: {missing}"
        )
    return result


def _probe_duration_sec(video: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        ToolingMissing = _ToolingMissingError()
        raise ToolingMissing(
            "ffmpeg / ffprobe not found on PATH — needed for keyframe extraction",
            install_hint=(
                "Install ffmpeg: https://ffmpeg.org/download.html "
                "(brew install ffmpeg / apt-get install ffmpeg)"
            ),
        )


def _ToolingMissingError() -> type[Exception]:
    """Lazy-import ``demo_function.ToolingMissingError`` to avoid a cycle.

    ``demo_function`` imports this module at render time, so importing it
    back at module-import time would deadlock.
    """
    from docgen.demo_function import ToolingMissingError as _T

    return _T


__all__ = [
    "KeyframeCandidate",
    "VISION_MODEL",
    "extract_candidates",
    "match_steps_to_keyframes",
    "parse_match_response",
]
