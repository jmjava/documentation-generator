"""Tests for docgen.vhs error pattern scanning."""

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
