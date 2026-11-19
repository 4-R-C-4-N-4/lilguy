"""Red-first unit tests for the fs.list / fs.grep helpers in lilguy/_typed_step.py.

These exercise the sandboxed helper functions directly (benign fixtures only, no live
sandbox/MCP wiring). Written before the implementation exists so they fail first (ImportError /
AttributeError), then pass once list_ and grep are added.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lilguy import _typed_step


# --- fixtures -------------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("alpha\nbeta\nALPHA again\n")
    (tmp_path / ".hidden.txt").write_text("secret\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("gamma beta\ndelta\n")
    (sub / ".hiddendir").mkdir()
    (sub / ".hiddendir" / "c.txt").write_text("nested\n")
    deep = sub / "deep"
    deep.mkdir()
    (deep / "d.txt").write_text("deepest beta\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(stdout_fn, *args, **kwargs):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        stdout_fn(*args, **kwargs)
    return buf.getvalue()


# --- fs.list ----------------------------------------------------------------------------------

def test_list_default_is_one_level_and_hides_dotfiles(workspace):
    out = run(_typed_step.list_, ".")
    names = {line.split()[-1] for line in out.splitlines() if line.strip()}
    assert "a.txt" in names
    assert "sub" in names
    assert ".hidden.txt" not in names
    assert "sub/b.txt" not in names  # depth 1: no descending into sub


def test_list_show_hidden_includes_dotfiles(workspace):
    out = run(_typed_step.list_, ".", show_hidden=True)
    names = {line.split()[-1] for line in out.splitlines() if line.strip()}
    assert ".hidden.txt" in names


def test_list_depth_recurses_additional_levels(workspace):
    out = run(_typed_step.list_, ".", depth=2)
    names = {line.split()[-1] for line in out.splitlines() if line.strip()}
    assert "sub/b.txt" in names
    assert "sub/deep" in names
    assert "sub/deep/d.txt" not in names  # depth 2 stops before the 3rd level


def test_list_depth_does_not_descend_into_symlinked_directories(workspace):
    target = workspace / "sub"
    link = workspace / "link_to_sub"
    link.symlink_to(target, target_is_directory=True)
    out = run(_typed_step.list_, ".", depth=3)
    lines = [line for line in out.splitlines() if "link_to_sub" in line]
    assert any(line.split()[-1] == "link_to_sub" for line in lines)
    assert not any(line.split()[-1].startswith("link_to_sub/") for line in lines)


def test_list_detailed_false_prints_bare_paths(workspace):
    out = run(_typed_step.list_, ".", detailed=False)
    for line in out.splitlines():
        if line.strip():
            assert " " not in line


def test_list_detailed_true_prefixes_type_and_size(workspace):
    out = run(_typed_step.list_, ".", detailed=True)
    rows = {line.split()[-1]: line for line in out.splitlines() if line.strip()}
    assert rows["a.txt"].startswith("f")
    assert rows["sub"].startswith("d")


def test_list_rejects_path_outside_workspace(workspace):
    with pytest.raises(ValueError):
        run(_typed_step.list_, "../escape")


def test_list_rejects_nonexistent_path(workspace):
    with pytest.raises(ValueError):
        run(_typed_step.list_, "does-not-exist")


def test_list_on_file_lists_the_file_itself(workspace):
    out = run(_typed_step.list_, "a.txt")
    names = {line.split()[-1] for line in out.splitlines() if line.strip()}
    assert names == {"a.txt"}


# --- fs.grep ----------------------------------------------------------------------------------

def test_grep_literal_match_prefixes_relative_path(workspace):
    out = run(_typed_step.grep, "beta", ".")
    assert "a.txt:beta" in out
    assert "sub/b.txt:gamma beta" in out


def test_grep_is_literal_by_default_not_regex(workspace):
    (workspace / "re.txt").write_text("a.c\nabc\n")
    out = run(_typed_step.grep, "a.c", ".", glob="re.txt")
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].endswith("a.c")


def test_grep_regex_mode(workspace):
    (workspace / "re.txt").write_text("a.c\nabc\n")
    out = run(_typed_step.grep, r"a.c", ".", glob="re.txt", regex=True)
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 2


def test_grep_ignore_case(workspace):
    out = run(_typed_step.grep, "alpha", "a.txt", ignore_case=True)
    assert out.count("alpha") + out.count("ALPHA") >= 2


def test_grep_case_sensitive_by_default(workspace):
    out = run(_typed_step.grep, "ALPHA", "a.txt")
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "ALPHA again" in lines[0]


def test_grep_line_numbers(workspace):
    out = run(_typed_step.grep, "beta", "a.txt", line_numbers=True)
    assert "a.txt:2:beta" in out


def test_grep_invert_match(workspace):
    out = run(_typed_step.grep, "beta", "a.txt", invert=True)
    names_lines = [line for line in out.splitlines() if line.strip()]
    assert any("alpha" in line for line in names_lines)
    assert not any(line.endswith("beta") for line in names_lines)


def test_grep_non_recursive_skips_subdirectories(workspace):
    out = run(_typed_step.grep, "beta", ".", recursive=False)
    assert "a.txt:beta" in out
    assert "sub/b.txt" not in out


def test_grep_recursive_default_descends(workspace):
    out = run(_typed_step.grep, "beta", ".")
    assert "sub/b.txt" in out
    assert "sub/deep/d.txt" in out


def test_grep_does_not_descend_into_hidden_directories_without_show(workspace):
    out = run(_typed_step.grep, "nested", ".")
    assert "nested" not in out  # .hiddendir/c.txt is not reached by default traversal choice


def test_grep_glob_filters_filenames(workspace):
    (workspace / "other.log").write_text("beta\n")
    out = run(_typed_step.grep, "beta", ".", glob="*.txt")
    assert "other.log" not in out
    assert "a.txt:beta" in out


def test_grep_filenames_only_dedupes_and_omits_line_text(workspace):
    out = run(_typed_step.grep, "beta", "sub/b.txt", filenames_only=True)
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines == ["sub/b.txt"]


def test_grep_max_results_caps_output(workspace):
    big = workspace / "big.txt"
    big.write_text("match\n" * 50)
    out = run(_typed_step.grep, "match", "big.txt", max_results=5)
    assert len([line for line in out.splitlines() if line.strip()]) == 5


def test_grep_skips_binary_files_without_crashing(workspace):
    (workspace / "bin.dat").write_bytes(b"\xff\xfe\x00beta\x00")
    out = run(_typed_step.grep, "beta", ".")
    assert "bin.dat" not in out  # binary files are skipped, not crashed on


def test_grep_does_not_follow_symlinked_files(workspace):
    target = workspace / "a.txt"
    link = workspace / "link.txt"
    link.symlink_to(target)
    out = run(_typed_step.grep, "beta", ".")
    assert "link.txt" not in out


def test_grep_rejects_path_outside_workspace(workspace):
    with pytest.raises(ValueError):
        run(_typed_step.grep, "beta", "../escape")


def test_grep_rejects_nonexistent_path(workspace):
    with pytest.raises(ValueError):
        run(_typed_step.grep, "beta", "nope")


# --- CLI dispatch (main()) -------------------------------------------------------------------

def test_cli_dispatches_fs_list(workspace):
    proc = subprocess.run(
        [sys.executable, "-c", Path(_typed_step.__file__).read_text(),
         "fs.list", "--", json.dumps({"path": "."})],
        cwd=workspace, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "a.txt" in proc.stdout


def test_cli_dispatches_fs_grep(workspace):
    proc = subprocess.run(
        [sys.executable, "-c", Path(_typed_step.__file__).read_text(),
         "fs.grep", "--", json.dumps({"pattern": "beta", "path": "."})],
        cwd=workspace, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "a.txt:beta" in proc.stdout
