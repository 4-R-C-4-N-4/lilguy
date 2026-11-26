"""Interface v7: fs.append and never-collapsed output (docs/plan/INTERFACE-V7.md); v1-v6 unchanged."""
import os
import stat
from pathlib import Path

import pytest

from lilguy import _typed_step as step
from lilguy import protocol as p

GOLDEN = Path(__file__).with_name("interface_v7_system_prompt.txt")


def test_v7_prompt_is_frozen_and_v6_is_unchanged():
    v7 = p.system_prompt(p.load_tools(version=7), version=7)
    assert v7 == GOLDEN.read_text(encoding="utf8")
    v6 = p.system_prompt(p.load_tools(version=6), version=6)
    assert v6 == Path(__file__).with_name("interface_v6_system_prompt.txt").read_text(encoding="utf8")
    assert "fs.append" in v7 and "fs.append" not in v6
    assert tuple(p.load_tools(version=7)) == p.TOOLS_V1 + p.TOOLS_V7 + p.TOOLS_V6
    assert p.INTERFACE_VERSION == 6  # the shipped app stays on v6 until a v7-trained model ships


def test_repeated_lines_are_shown_as_printed_only_from_v7():
    out = "stack=8M\nstack=8M\n"
    v6 = p.render_observation(exit_code=0, stdout=out, version=6)
    v7 = p.render_observation(exit_code=0, stdout=out, version=7)
    assert "stack=8M  (x2)" in v6
    assert "(x2)" not in v7 and v7.count("stack=8M\n") == 2


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(step, "INTERFACE", 7)
    return tmp_path


def test_append_adds_a_missing_final_newline_and_ends_every_line(ws, capsys):
    (ws / "limits.ini").write_text("files=1024")
    step.append("limits.ini", "procs=512\nstack=8M")
    assert (ws / "limits.ini").read_text() == "files=1024\nprocs=512\nstack=8M\n"
    assert capsys.readouterr().out == "appended 2 lines to limits.ini (added the missing final newline first)\n"
    step.append("limits.ini", "alias gs='git status'\n")
    assert (ws / "limits.ini").read_text().endswith("stack=8M\nalias gs='git status'\n")
    assert capsys.readouterr().out == "appended 1 line to limits.ini\n"


def test_append_keeps_mode_and_refuses_missing_files_and_empty_input(ws):
    (ws / "run.sh").write_text("echo a\n")
    os.chmod(ws / "run.sh", 0o750)
    step.append("run.sh", "echo b")
    assert stat.S_IMODE((ws / "run.sh").stat().st_mode) == 0o750
    with pytest.raises(ValueError, match="No such file: notes.txt"):
        step.append("notes.txt", "x")
    with pytest.raises(ValueError, match="Nothing to append"):
        step.append("run.sh", "\n")


def test_empty_file_gets_no_leading_blank_line(ws):
    (ws / "empty.txt").write_text("")
    step.append("empty.txt", "first")
    assert (ws / "empty.txt").read_text() == "first\n"
