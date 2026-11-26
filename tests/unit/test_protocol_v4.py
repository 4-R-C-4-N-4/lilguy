"""Interface v4: framed, unindented output and specific fs.edit refusals; v1–v3 unchanged."""
from pathlib import Path

import pytest

from lilguy import _typed_step
from lilguy import protocol as p

TOOLS = p.load_tools(version=5)  # the frozen v1-v5 surface (v6 adds archive tools)
V3_GOLDEN = Path(__file__).with_name("interface_v3_system_prompt.txt")
V4_GOLDEN = Path(__file__).with_name("interface_v4_system_prompt.txt")


def test_v4_prompt_is_frozen_and_v3_is_unchanged():
    assert p.system_prompt(TOOLS, version=3) == V3_GOLDEN.read_text(encoding="utf8")
    assert p.system_prompt(TOOLS, version=4) == V4_GOLDEN.read_text(encoding="utf8"), (
        "The v4 system prompt changed. If intended, regenerate the golden and the v4 data.")


def test_v4_prompt_adds_only_the_two_sentences():
    v3, v4 = p.system_prompt(TOOLS, version=3), p.system_prompt(TOOLS, version=4)
    assert "occurs more than once, put old in <<< >>> with a neighbouring line" in v4
    assert "exactly as printed: copy it without adding or removing spaces" in v4
    assert len(v4.splitlines()) == len(v3.splitlines())


def test_v4_output_is_framed_and_byte_exact():
    text = p.render_observation(exit_code=0, stdout="jobs:\n  - name: rotate\n", version=4)
    assert text.split("\n")[:5] == ["exit=0", "stdout (2 lines) <<<", "jobs:", "  - name: rotate", ">>>"]
    assert p.observation_stdout(text) == "jobs:\n  - name: rotate"


def test_v4_frames_stderr_too():
    text = p.render_observation(exit_code=1, stderr="  oops\n", version=4)
    assert "stderr (1 lines) <<<\n  oops\n>>>" in text


@pytest.mark.parametrize("version", [1, 2, 3])
def test_earlier_versions_keep_the_indented_format(version):
    text = p.render_observation(exit_code=0, stdout="a\n", version=version)
    assert "stdout (1 lines):\n  a" in text and "<<<" not in text
    assert p.observation_stdout(text) == "a"


def test_quoted_answer_reads_v4_output():
    from lilguy import loop
    observation = p.render_observation(exit_code=0, stdout="4\n", version=4)
    quote = p.quoted_answer([loop.Turn(p.Action.run("grep -c x f"), observation, False)])
    assert quote is not None and quote.text == "4"


# --- fs.edit refusals -------------------------------------------------------------------------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "parts.txt").write_text("item: bolts\nqty: 5\n\nitem: nuts\nqty: 5\n")
    return tmp_path


def _refusal(monkeypatch, interface, old):
    monkeypatch.setattr(_typed_step, "INTERFACE", interface)
    with pytest.raises(ValueError) as exc:
        _typed_step.edit("parts.txt", old, "qty: 8")
    return str(exc.value)


def test_v4_refusal_counts_and_locates_repeated_text(workspace, monkeypatch):
    message = _refusal(monkeypatch, 4, "qty: 5")
    assert message == ("old text occurs 2 times in parts.txt (lines 2, 5); "
                       "put old in <<< >>> with a neighbouring line so it occurs once")


def test_v4_refusal_says_not_found(workspace, monkeypatch):
    assert _refusal(monkeypatch, 4, "qty: 9") == "old text not found in parts.txt"
    assert "check spaces" in _refusal(monkeypatch, 4, "  qty: 5")


def test_v3_refusal_is_unchanged(workspace, monkeypatch):
    assert _refusal(monkeypatch, 3, "qty: 5") == "Expected UTF-8 text and exactly one literal match"


def test_a_block_with_a_neighbouring_line_edits_exactly_one(workspace, monkeypatch):
    monkeypatch.setattr(_typed_step, "INTERFACE", 4)
    _typed_step.edit("parts.txt", "item: nuts\nqty: 5\n", "item: nuts\nqty: 8\n")
    assert (workspace / "parts.txt").read_text() == "item: bolts\nqty: 5\n\nitem: nuts\nqty: 8\n"
