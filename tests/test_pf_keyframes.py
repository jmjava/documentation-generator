"""Unit tests for :mod:`docgen.pf_keyframes` — vision-LLM keyframe matcher.

These tests cover the *matching* logic in isolation: response parsing,
prompt construction, the OpenAI vision call wrapping, and the strict
JSON validation contract. None of them touch the network or shell out
to ffmpeg — the candidate frames are dummy PNG bytes on disk and the
OpenAI client is a fake whose ``chat.completions.create`` returns a
canned JSON string.

The frame-extraction helper (``extract_candidates``) is tested by
asserting the ffmpeg invocation is well-formed via shell-level mocks;
end-to-end correctness of the slideshow video is exercised in the
integration test against a real Playwright recording.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docgen import pf_keyframes
from docgen.pf_keyframes import KeyframeCandidate


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


# 1x1 PNG — minimum viable image for base64-embedding tests.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63000100000005000100621d6c4f0000000049454e44ae426082"
)


def _make_candidate(
    tmp_path: Path, idx: int, *, t: float = 0.0
) -> KeyframeCandidate:
    """Write a tiny PNG and wrap it as a candidate at index ``idx``."""
    p = tmp_path / f"cand_{idx:03d}.png"
    p.write_bytes(_PNG_1x1)
    return KeyframeCandidate(path=p, t_seconds=t, index=idx)


def _steps(*lines: str) -> list[dict[str, Any]]:
    return [
        {"say": line, "api_name": f"page.action_{i}"}
        for i, line in enumerate(lines)
    ]


class _FakeChatCompletions:
    """Fake ``client.chat.completions.create`` that records its call args."""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        msg = type(
            "Msg",
            (),
            {"content": self._payload},
        )()
        choice = type("Choice", (), {"message": msg})()
        return type("Resp", (), {"choices": [choice]})()


class _FakeOpenAIClient:
    """Two-deep client object: ``client.chat.completions.create(...)``."""

    def __init__(self, payload: str) -> None:
        self.completions = _FakeChatCompletions(payload)
        self.chat = type("Chat", (), {"completions": self.completions})()


# ---------------------------------------------------------------------------
# parse_match_response
# ---------------------------------------------------------------------------


def test_parse_match_response_valid_monotonic() -> None:
    raw = json.dumps(
        {
            "matches": [
                {"step": 0, "candidate": 0},
                {"step": 1, "candidate": 2},
                {"step": 2, "candidate": 5},
            ]
        }
    )
    assert pf_keyframes.parse_match_response(
        raw, n_steps=3, n_candidates=10
    ) == [0, 2, 5]


def test_parse_match_response_clamps_minor_decrease() -> None:
    """LLM occasionally swaps adjacent indices; we clamp forward, not raise."""
    raw = json.dumps(
        {
            "matches": [
                {"step": 0, "candidate": 3},
                {"step": 1, "candidate": 2},  # dip below previous
                {"step": 2, "candidate": 4},
            ]
        }
    )
    assert pf_keyframes.parse_match_response(
        raw, n_steps=3, n_candidates=8
    ) == [3, 3, 4]


def test_parse_match_response_rejects_non_json() -> None:
    with pytest.raises(RuntimeError, match="non-JSON"):
        pf_keyframes.parse_match_response(
            "not json at all", n_steps=1, n_candidates=4
        )


def test_parse_match_response_rejects_wrong_length() -> None:
    raw = json.dumps({"matches": [{"step": 0, "candidate": 0}]})
    with pytest.raises(RuntimeError, match="expected 3"):
        pf_keyframes.parse_match_response(raw, n_steps=3, n_candidates=4)


def test_parse_match_response_rejects_missing_matches_field() -> None:
    raw = json.dumps({"answers": [{"step": 0, "candidate": 0}]})
    with pytest.raises(RuntimeError, match="'matches'"):
        pf_keyframes.parse_match_response(raw, n_steps=1, n_candidates=4)


def test_parse_match_response_rejects_candidate_out_of_range() -> None:
    raw = json.dumps({"matches": [{"step": 0, "candidate": 99}]})
    with pytest.raises(RuntimeError, match="candidate index out of range"):
        pf_keyframes.parse_match_response(raw, n_steps=1, n_candidates=4)


def test_parse_match_response_rejects_unassigned_step() -> None:
    # Two entries both targeting step 0 leaves step 1 unassigned.
    raw = json.dumps(
        {
            "matches": [
                {"step": 0, "candidate": 0},
                {"step": 0, "candidate": 1},
            ]
        }
    )
    with pytest.raises(RuntimeError, match="did not assign"):
        pf_keyframes.parse_match_response(raw, n_steps=2, n_candidates=4)


def test_parse_match_response_rejects_step_out_of_range() -> None:
    raw = json.dumps({"matches": [{"step": 5, "candidate": 0}]})
    with pytest.raises(RuntimeError, match="step index out of range"):
        pf_keyframes.parse_match_response(raw, n_steps=1, n_candidates=4)


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------


def test_build_user_prompt_lists_each_step_with_index_and_api() -> None:
    steps = _steps("Open the home page.", "Click the button.")
    prompt = pf_keyframes._build_user_prompt(steps, n_candidates=7)
    # Header announces candidate count + zero-based numbering.
    assert "7 frames" in prompt
    assert "0..6" in prompt
    # Each line is rendered with its index and api_name.
    assert '0. (page.action_0) "Open the home page."' in prompt
    assert '1. (page.action_1) "Click the button."' in prompt


# ---------------------------------------------------------------------------
# match_steps_to_keyframes (with injected fake client)
# ---------------------------------------------------------------------------


def test_match_steps_to_keyframes_returns_chosen_in_order(
    tmp_path: Path,
) -> None:
    candidates = [_make_candidate(tmp_path, i, t=i * 0.2) for i in range(5)]
    steps = _steps("Step one.", "Step two.", "Step three.")
    payload = json.dumps(
        {
            "matches": [
                {"step": 0, "candidate": 0},
                {"step": 1, "candidate": 2},
                {"step": 2, "candidate": 4},
            ]
        }
    )
    client = _FakeOpenAIClient(payload)

    chosen = pf_keyframes.match_steps_to_keyframes(
        candidates, steps, openai_client=client
    )

    assert [c.index for c in chosen] == [0, 2, 4]
    # Verify the LLM saw N+1 content blocks (1 text + N images) and JSON mode.
    kwargs = client.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["response_format"] == {"type": "json_object"}
    user_msg = kwargs["messages"][1]
    assert user_msg["role"] == "user"
    assert len(user_msg["content"]) == 1 + len(candidates)
    image_blocks = [
        b for b in user_msg["content"] if b["type"] == "image_url"
    ]
    assert len(image_blocks) == len(candidates)
    for b in image_blocks:
        assert b["image_url"]["detail"] == "high"
        assert b["image_url"]["url"].startswith("data:image/png;base64,")


def test_match_steps_to_keyframes_empty_steps_returns_empty(
    tmp_path: Path,
) -> None:
    candidates = [_make_candidate(tmp_path, 0)]
    client = _FakeOpenAIClient("{}")

    assert (
        pf_keyframes.match_steps_to_keyframes(
            candidates, [], openai_client=client
        )
        == []
    )
    # No call should have been made for an empty steps list.
    assert client.completions.last_kwargs is None


def test_match_steps_to_keyframes_no_candidates_raises(
    tmp_path: Path,
) -> None:
    client = _FakeOpenAIClient("{}")
    with pytest.raises(RuntimeError, match="no candidate keyframes"):
        pf_keyframes.match_steps_to_keyframes(
            [], _steps("Only step."), openai_client=client
        )


def test_match_steps_to_keyframes_propagates_parse_errors(
    tmp_path: Path,
) -> None:
    candidates = [_make_candidate(tmp_path, i) for i in range(3)]
    steps = _steps("Step one.", "Step two.")
    # LLM returns wrong shape — match function must surface a clear error.
    client = _FakeOpenAIClient(json.dumps({"matches": "broken"}))

    with pytest.raises(RuntimeError, match="'matches'"):
        pf_keyframes.match_steps_to_keyframes(
            candidates, steps, openai_client=client
        )


def test_match_steps_to_keyframes_uses_default_vision_model(
    tmp_path: Path,
) -> None:
    candidates = [_make_candidate(tmp_path, i) for i in range(2)]
    steps = _steps("Single step.")
    client = _FakeOpenAIClient(
        json.dumps({"matches": [{"step": 0, "candidate": 0}]})
    )
    pf_keyframes.match_steps_to_keyframes(
        candidates, steps, openai_client=client
    )
    assert client.completions.last_kwargs["model"] == pf_keyframes.VISION_MODEL


# ---------------------------------------------------------------------------
# extract_candidates (ffmpeg invocations are mocked)
# ---------------------------------------------------------------------------


def test_extract_candidates_invokes_ffmpeg_per_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke test: ensure we ask ffmpeg for one frame per sampled timestamp."""
    video = tmp_path / "src.mp4"
    video.write_bytes(b"\x00")  # ffmpeg gets monkey-patched; bytes don't matter.

    # Pretend ffmpeg / ffprobe exist on PATH.
    monkeypatch.setattr(pf_keyframes.shutil, "which", lambda _name: "/usr/bin/" + _name)
    monkeypatch.setattr(pf_keyframes, "_probe_duration_sec", lambda _v: 1.0)

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *_a: Any, **_kw: Any) -> Any:
        calls.append(list(cmd))
        # Touch the output PNG so the candidate file exists.
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_PNG_1x1)
        return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(pf_keyframes.subprocess, "run", fake_run)

    work_dir = tmp_path / "kf"
    out = pf_keyframes.extract_candidates(
        video, work_dir, interval_sec=0.25, max_count=4
    )

    # We requested 1.0s / 0.25s = 4 frames; the impl rounds up to ``+1``
    # boundaries so we expect at least 4 candidates.
    assert len(out) >= 2
    assert len(out) == len(calls)
    for c in out:
        assert c.path.exists()
    # Every ffmpeg call should use accurate seek (``-ss`` AFTER ``-i``).
    for cmd in calls:
        assert cmd[0] == "ffmpeg"
        i_idx = cmd.index("-i")
        ss_idx = cmd.index("-ss")
        assert ss_idx > i_idx, "fast seek would land on wrong frame"
        assert "-frames:v" in cmd
        assert cmd[cmd.index("-frames:v") + 1] == "1"


def test_extract_candidates_raises_when_duration_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "src.mp4"
    video.write_bytes(b"\x00")
    monkeypatch.setattr(pf_keyframes.shutil, "which", lambda _name: "/usr/bin/" + _name)
    monkeypatch.setattr(pf_keyframes, "_probe_duration_sec", lambda _v: 0.0)

    with pytest.raises(RuntimeError, match="zero / unprobeable duration"):
        pf_keyframes.extract_candidates(video, tmp_path / "kf")


def test_extract_candidates_raises_when_ffmpeg_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "src.mp4"
    video.write_bytes(b"\x00")
    monkeypatch.setattr(pf_keyframes.shutil, "which", lambda _name: "/usr/bin/" + _name)
    monkeypatch.setattr(pf_keyframes, "_probe_duration_sec", lambda _v: 0.5)

    def boom(cmd: list[str], *_a: Any, **_kw: Any) -> Any:
        return type(
            "R", (), {"returncode": 1, "stderr": "decoder explosion", "stdout": ""}
        )()

    monkeypatch.setattr(pf_keyframes.subprocess, "run", boom)

    with pytest.raises(RuntimeError, match="keyframe extract failed"):
        pf_keyframes.extract_candidates(video, tmp_path / "kf")
