"""Tests for docgen.vhs error pattern scanning and tape linting."""

from __future__ import annotations

from pathlib import Path

from docgen.vhs import VHSRunner


def test_scan_output_clean():
    errors = VHSRunner._scan_output("Rendering tape...\nDone.")
    assert errors == []


def test_scan_output_command_not_found():
    errors = VHSRunner._scan_output("bash: kubectl: command not found")
    assert len(errors) == 1
    assert "command not found" in errors[0]


def test_scan_output_no_such_file():
    errors = VHSRunner._scan_output("cat: /tmp/missing: No such file or directory")
    assert len(errors) == 1


def test_scan_output_permission_denied():
    errors = VHSRunner._scan_output("bash: /root/secret: Permission denied")
    assert len(errors) == 1


def test_scan_output_multiple():
    text = "line1\nbash: foo: command not found\nline3\nerror: something broke\n"
    errors = VHSRunner._scan_output(text)
    assert len(errors) == 2


def test_scan_tape_for_risky_commands_detects_python_and_curl(tmp_path: Path) -> None:
    tape = tmp_path / "demo.tape"
    tape.write_text(
        '\n'.join(
            [
                'Set Shell "bash --norc --noprofile"',
                'Type "python app.py"',
                "Enter",
                'Type "curl http://localhost:8080/health"',
                "Enter",
            ]
        ),
        encoding="utf-8",
    )
    issues = VHSRunner.scan_tape_for_risky_commands(tape)
    assert len(issues) == 2
    assert "python" in issues[0].text.lower()
    assert "curl" in issues[1].text.lower()


def test_scan_tape_for_risky_commands_ignores_echo_simulation(tmp_path: Path) -> None:
    tape = tmp_path / "demo.tape"
    tape.write_text(
        '\n'.join(
            [
                'Type "echo \'$ python app.py\'"',
                "Enter",
                'Type "echo \'[ok] done\'"',
                "Enter",
            ]
        ),
        encoding="utf-8",
    )
    issues = VHSRunner.scan_tape_for_risky_commands(tape)
    assert issues == []
