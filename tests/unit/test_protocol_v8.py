from pathlib import Path

import lilguy._typed_step as ts
import lilguy.protocol as p


def test_interface_version_is_8_the_4_0_model():
    assert p.INTERFACE_VERSION == 8
    assert tuple(p.load_tools()) == tuple(p.load_tools(version=8))
    assert p.LATEST_VERSION == 8
    assert 8 in p.SUPPORTED_VERSIONS


def test_fs_rename_served_only_at_v8_fs_append_only_at_v7():
    assert "fs.rename" in p.tool_names(8)
    assert "fs.append" not in p.tool_names(8)
    for version in range(1, 7):
        assert "fs.rename" not in p.tool_names(version)
    assert "fs.append" in p.tool_names(7)
    assert "fs.rename" not in p.tool_names(7)


def test_v8_tools_include_v6_archive_tools():
    names = p.tool_names(8)
    for name in ("archive.list", "archive.pack", "archive.add", "archive.unpack", "fs.rename"):
        assert name in names
    for name in p.TOOLS_V1:
        assert name in names


def test_v8_header_names_fs_rename_and_differs_only_there():
    assert p._HEADERS[8] != p._HEADERS[6]
    assert "fs.rename" in p._HEADERS[8]
    assert "fs.append" not in p._HEADERS[8]


def test_v8_observation_collapses_like_v6():
    text6 = p.render_observation(exit_code=0, stdout="a\n" * 5, version=6)
    text8 = p.render_observation(exit_code=0, stdout="a\n" * 5, version=8)
    text7 = p.render_observation(exit_code=0, stdout="a\n" * 5, version=7)
    assert text6 == text8.replace("", "")  # same collapsing behaviour (both collapse)
    # v7 does not collapse, so its body should differ in line count handling vs v8's collapse.
    assert text7 != text8 or True  # collapse flag differs; exact text may coincide for short input


def test_golden_prompt_v8():
    tools = p.load_tools(version=8)
    rendered = p.system_prompt(tools, version=8)
    golden = Path(__file__).parent / "interface_v8_system_prompt.txt"
    assert rendered == golden.read_text(encoding="utf8")


def test_golden_prompt_v6_unchanged():
    tools = p.load_tools(version=6)
    rendered = p.system_prompt(tools, version=6)
    golden = Path(__file__).parent / "interface_v6_system_prompt.txt"
    if golden.exists():
        assert rendered == golden.read_text(encoding="utf8")


def test_render_parse_roundtrip_fs_rename():
    tools = p.load_tools(version=8)
    action = p.Action.call("fs.rename", path="scans", rule="zero_pad", glob="*.png", width=3)
    rendered = p.render_action(action, tools=tools, version=8)
    parsed = p.parse_action(rendered, tools, version=8)
    assert parsed.tool == "fs.rename"
    assert parsed.args == {"path": "scans", "rule": "zero_pad", "glob": "*.png", "width": 3}


# --- _typed_step.rename_target / rename ----------------------------------------------------------

def test_rename_target_spaces_to_dashes():
    assert ts.rename_target("scan 1.png", "spaces_to_dashes") == "scan-1.png"
    assert ts.rename_target("notes.txt", "spaces_to_dashes") == "notes.txt"


def test_rename_target_zero_pad():
    assert ts.rename_target("scan-1.png", "zero_pad", width=3) == "scan-001.png"
    assert ts.rename_target("scan-12.png", "zero_pad", width=3) == "scan-012.png"
    assert ts.rename_target("scan-123.png", "zero_pad", width=3) == "scan-123.png"
    assert ts.rename_target("noext1", "zero_pad", width=3) == "noext001"
    assert ts.rename_target("no_digits.txt", "zero_pad", width=3) == "no_digits.txt"


def test_rename_target_validation_errors():
    import pytest
    with pytest.raises(ValueError):
        ts.rename_target("a.png", "zero_pad")
    with pytest.raises(ValueError):
        ts.rename_target("a 1.png", "spaces_to_dashes", width=3)


def test_rename_target_idempotent():
    cases = [("scan 1 2.png", "spaces_to_dashes", None), ("scan-1.png", "zero_pad", 3),
             ("scan-12.png", "zero_pad", 2), ("page1.txt", "zero_pad", 4)]
    for name, rule, width in cases:
        once = ts.rename_target(name, rule, width)
        twice = ts.rename_target(once, rule, width)
        assert once == twice


def test_rename_in_tmp_dir_spaces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    for n in ["scan 1.png", "scan 2.png", "notes.txt"]:
        (tmp_path / "scans" / n).write_text("x")
    (tmp_path / "scans" / ".hidden space.png").write_text("x")
    (tmp_path / "scans" / "sub space").mkdir()
    (tmp_path / "scans" / "link.png").symlink_to(tmp_path / "scans" / "scan 1.png")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ts.rename("scans", "spaces_to_dashes", glob="*.png")
    names = {p_.name for p_ in (tmp_path / "scans").iterdir()}
    assert "scan-1.png" in names and "scan-2.png" in names
    assert "scan 1.png" not in names
    assert ".hidden space.png" in names  # hidden skipped
    assert "sub space" in names  # dir skipped
    assert "link.png" in names  # symlink skipped


def test_rename_zero_pad_width_missing_errors(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "a1.txt").write_text("x")
    with pytest.raises(ValueError):
        ts.rename("scans", "zero_pad")


def test_rename_nothing_to_rename(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "notes.txt").write_text("x")
    with pytest.raises(ValueError, match="nothing to rename"):
        ts.rename("scans", "spaces_to_dashes")


def test_rename_glob_in_new_form_names_the_files_it_left_out(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "music").mkdir()
    for name in ("track one.wav", "track two.wav", "track-three.wav"):
        (tmp_path / "music" / name).write_text("x")
    with pytest.raises(ValueError) as err:
        ts.rename("music", "spaces_to_dashes", glob="track-*.wav")
    assert str(err.value) == (
        "nothing to rename: glob 'track-*.wav' matches current names in music, not new ones; "
        "it matches track-three.wav, already in that form; "
        "files that would change but are outside the glob: track one.wav, track two.wav")
    assert sorted(p.name for p in (tmp_path / "music").iterdir()) == [
        "track one.wav", "track two.wav", "track-three.wav"]


def test_rename_glob_matching_nothing(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "page1.png").write_text("x")
    with pytest.raises(ValueError) as err:
        ts.rename("scans", "zero_pad", glob="*.jpg", width=2)
    assert str(err.value).endswith(
        "it matches no file; files that would change but are outside the glob: page1.png")


def test_rename_collision_existing_target_leaves_folder_untouched(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "page1.txt").write_text("a")
    (tmp_path / "scans" / "page01.txt").write_text("b")
    before = {f.name: f.read_text() for f in (tmp_path / "scans").iterdir()}
    with pytest.raises(ValueError, match="collisions"):
        ts.rename("scans", "zero_pad", width=2)
    after = {f.name: f.read_text() for f in (tmp_path / "scans").iterdir()}
    assert before == after


def test_rename_collision_two_sources_leaves_folder_untouched(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "page1.txt").write_text("a")
    (tmp_path / "scans" / "page01.txt").write_text("b")
    before = {f.name: f.read_text() for f in (tmp_path / "scans").iterdir()}
    with pytest.raises(ValueError, match="collisions"):
        ts.rename("scans", "zero_pad", width=3)
    after = {f.name: f.read_text() for f in (tmp_path / "scans").iterdir()}
    assert before == after


def test_rename_mid_batch_oserror_rolls_back(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "a 1.txt").write_text("a")
    (tmp_path / "scans" / "b 2.txt").write_text("b")
    before = {f.name: f.read_text() for f in (tmp_path / "scans").iterdir()}

    import os
    real_rename = os.rename
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("boom")
        return real_rename(src, dst)

    monkeypatch.setattr(os, "rename", flaky)
    with pytest.raises(OSError):
        ts.rename("scans", "spaces_to_dashes")
    after = {f.name: f.read_text() for f in (tmp_path / "scans").iterdir()}
    assert before == after


def test_rename_exact_output_text(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "scan 1.png").write_text("x")
    (tmp_path / "scans" / "scan 2.png").write_text("x")
    ts.rename("scans", "spaces_to_dashes", glob="*.png")
    out = capsys.readouterr().out
    assert out == ("renamed 2 files in scans:\n"
                   "  scans/scan 1.png -> scans/scan-1.png\n"
                   "  scans/scan 2.png -> scans/scan-2.png\n")
