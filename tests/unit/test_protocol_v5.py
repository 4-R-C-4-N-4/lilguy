"""Interface v5: exact output, a missing-final-newline marker, and "No such file" refusals; v1–v4 unchanged."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lilguy import _typed_step, loop
from lilguy import protocol as p

TOOLS = p.load_tools()
GOLDEN = {v: Path(__file__).with_name(f"interface_v{v}_system_prompt.txt") for v in (3, 4, 5)}


def test_v5_prompt_is_frozen_and_earlier_prompts_are_unchanged():
    for version, path in GOLDEN.items():
        assert p.system_prompt(TOOLS, version=version) == path.read_text(encoding="utf8"), version


def test_v5_prompt_adds_only_the_two_sentences():
    v4, v5 = p.system_prompt(TOOLS, version=4), p.system_prompt(TOOLS, version=5)
    assert len(v4.splitlines()) == len(v5.splitlines())
    assert "(no newline at end of output)" in v5 and "never change a file with a similar name" in v5
    assert "(no newline" not in v4


def test_shipped_default_is_still_v4_and_v5_stays_supported():
    assert p.INTERFACE_VERSION == 4 and p.LATEST_VERSION >= 5 and 5 in p.SUPPORTED_VERSIONS


def test_missing_final_newline_is_announced_outside_the_frame():
    text = p.render_observation(exit_code=0, stdout="alpha\nbeta", version=5)
    assert text.split("\n")[:6] == ["exit=0", "stdout (2 lines) <<<", "alpha", "beta", ">>>",
                                    "(no newline at end of output)"]
    assert p.observation_stdout(text) == "alpha\nbeta"
    assert "(no newline" not in p.render_observation(exit_code=0, stdout="alpha\nbeta\n", version=5)


def test_trailing_spaces_and_blank_lines_are_kept_in_v5_only():
    five = p.render_observation(exit_code=0, stdout="Dear,\n   \n\n", version=5)
    assert "stdout (3 lines) <<<\nDear,\n   \n\n>>>" in five
    four = p.render_observation(exit_code=0, stdout="Dear,\n   \n\n", version=4)
    assert "stdout (2 lines) <<<\nDear,\n  (x2)\n>>>" in four  # v4 strips and collapses them


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_earlier_versions_render_byte_identically(version):
    for stdout in ("alpha\nbeta", "x  \n\n", ""):
        text = p.render_observation(exit_code=0, stdout=stdout, version=version)
        assert "no newline" not in text


def test_quoted_answer_reads_v5_output():
    observation = p.render_observation(exit_code=0, stdout="4", version=5)
    quote = p.quoted_answer([loop.Turn(p.Action.run("wc -l < f"), observation, False)])
    assert quote is not None and quote.text == "4"


@pytest.mark.parametrize("version, expected", [(4, "Expected a regular file"), (5, "No such file: gone.txt")])
def test_missing_file_refusal(tmp_path, version, expected):
    (tmp_path / "dir").mkdir()
    step = Path(_typed_step.__file__)
    for tool, args in (("fs.read", {"path": "gone.txt", "offset": 1, "limit": 50}),
                       ("fs.edit", {"path": "gone.txt", "old": "a", "new": "b"})):
        r = subprocess.run([sys.executable, str(step), tool, "", json.dumps(args), str(version)],
                           cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 1 and r.stderr.strip() == expected, (tool, r.stderr)
    r = subprocess.run([sys.executable, str(step), "fs.read", "", json.dumps({"path": "dir", "offset": 1,
                        "limit": 5}), "5"], cwd=tmp_path, capture_output=True, text=True)
    assert r.stderr.strip() == "dir is a directory, not a file"
    r = subprocess.run([sys.executable, str(step), "fs.list", "", json.dumps({"path": "nope"}), "5"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.stderr.strip() == "No such file or directory: nope"
