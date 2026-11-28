"""Interface v6: typed archive tools (docs/plan/INTERFACE-V6.md); v1-v5 unchanged."""
import gzip
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from lilguy import _typed_step as step
from lilguy import protocol as p
from lilguy.mcp_server import InterfaceV1, build_v1_tools

GOLDEN = Path(__file__).with_name("interface_v6_system_prompt.txt")
V6 = p.load_tools(version=6)


def test_v6_prompt_is_frozen_and_adds_only_the_tools_and_one_habit():
    prompt = p.system_prompt(V6, version=6)
    assert prompt == GOLDEN.read_text(encoding="utf8")
    v5 = p.system_prompt(p.load_tools(version=5), version=5)
    assert prompt.startswith(v5.split("- Use a tool below")[0])
    assert "use the archive tools rather than tar" in prompt and "archive.unpack with member" in prompt
    assert "archive." not in v5 and "fs.chmod" not in prompt  # measured twice and dropped


def test_tools_are_gated_by_version_and_the_frozen_manifest_is_unchanged():
    for version in (1, 2, 3, 4, 5):
        assert tuple(p.load_tools(version=version)) == p.TOOLS_V1
        assert tuple(build_v1_tools(version)) == ("run", *p.TOOLS_V1)
    assert tuple(V6) == p.TOOLS_V1 + p.TOOLS_V6
    assert tuple(build_v1_tools(6)) == ("run", *p.TOOLS_V1, *p.TOOLS_V6)
    assert tuple(p.load_tools(version=6)) == p.TOOLS_V1 + p.TOOLS_V6  # 3.0's interface


def test_v6_actions_round_trip_and_the_grammar_names_every_tool():
    action = p.Action.call("archive.unpack", archive="settings.tar", into="out", member="colors.ini")
    text = p.render_action(action, V6, version=6)
    assert text == "tool archive.unpack\narchive: settings.tar\ninto: out\nmember: colors.ini"
    parsed = p.parse_action(text, V6, version=6)
    assert (parsed.kind, parsed.tool, parsed.args) == ("tool", "archive.unpack", action.args)
    grammar = p.grammar(V6, version=6)
    for name in p.TOOLS_V6:
        assert name in grammar
    assert "fs.chmod" not in grammar


def test_every_path_argument_is_checked_before_the_sandbox():
    server = InterfaceV1(build_v1_tools(6), open_guarded=None, interface=6)
    assert server._run_spec("archive.unpack", {"archive": "a.tar", "into": "../out"}) is None
    assert server._run_spec("archive.pack", {"archive": "/tmp/x.tar", "source": "d"}) is None
    assert server._run_spec("archive.pack", {"archive": "x.tar", "source": "d"}) is not None


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(step, "INTERFACE", 6)
    return tmp_path


def _mode(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


def _members(path):
    with tarfile.open(path) as tar:
        return {m.name: tar.extractfile(m).read().decode() for m in tar.getmembers() if m.isfile()}


def test_pack_with_exclude_top_folder_and_add(ws, capsys):
    (ws / "notes" / "later").mkdir(parents=True)
    (ws / "notes" / "a.txt").write_text("a\n")
    (ws / "notes" / "s.tmp").write_text("t\n")
    (ws / "notes" / "later" / "b.txt").write_text("b\n")
    step.archive_pack("notes.tar.gz", "notes", exclude="*.tmp")
    assert _members(ws / "notes.tar.gz") == {"notes/a.txt": "a\n", "notes/later/b.txt": "b\n"}
    step.archive_pack("flat.tar", "notes", top_folder=False)
    assert set(_members(ws / "flat.tar")) == {"a.txt", "s.tmp", "later/b.txt"}
    (ws / "extra.txt").write_text("e\n")
    step.archive_add("notes.tar.gz", "extra.txt")
    assert _members(ws / "notes.tar.gz") == {"notes/a.txt": "a\n", "notes/later/b.txt": "b\n", "extra.txt": "e\n"}
    (ws / "kit").mkdir()
    (ws / "kit" / "easel.txt").write_text("k\n")
    step.archive_add("notes.tar.gz", "kit/easel.txt")  # a file keeps its workspace path, as with tar
    assert "kit/easel.txt" in _members(ws / "notes.tar.gz")
    with pytest.raises(ValueError, match="must not be inside"):
        step.archive_pack("notes/self.tar", "notes")


def test_gzip_one_file_keeps_the_original_and_round_trips(ws):
    (ws / "server.log").write_text("up\n")
    step.archive_pack("server.log.gz", "server.log")
    assert (ws / "server.log").read_text() == "up\n"
    assert gzip.decompress((ws / "server.log.gz").read_bytes()) == b"up\n"
    with pytest.raises(ValueError, match="one file"):
        step.archive_pack("dir.gz", ".")


def test_list_and_compare(ws, capsys):
    (ws / "site").mkdir()
    (ws / "site" / "index.html").write_text("new\n")
    (ws / "site" / "about.html").write_text("same\n")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, text in (("site/index.html", "old\n"), ("site/about.html", "same\n"), ("site/gone.html", "g\n")):
            info = tarfile.TarInfo(name)
            info.size = len(text)
            tar.addfile(info, io.BytesIO(text.encode()))
    (ws / "backup.tar").write_bytes(buf.getvalue())
    step.archive_list("backup.tar")
    assert capsys.readouterr().out == "site/index.html 4 bytes\nsite/about.html 5 bytes\nsite/gone.html 2 bytes\n"
    step.archive_list("backup.tar", compare=True)
    assert capsys.readouterr().out == "site/index.html differs\nsite/about.html same\nsite/gone.html missing\n"


def test_unpack_keeps_existing_files_unless_overwrite_and_takes_one_member(ws, capsys):
    (ws / "src").mkdir()
    (ws / "src" / "config.ini").write_text("volume=9\n")
    (ws / "src" / "colors.ini").write_text("accent=teal\n")
    step.archive_pack("settings.tar", "src", top_folder=False)
    (ws / "config.ini").write_text("volume=3\n")
    capsys.readouterr()
    step.archive_unpack("settings.tar")
    assert (ws / "config.ini").read_text() == "volume=3\n" and (ws / "colors.ini").read_text() == "accent=teal\n"
    assert "kept existing: config.ini" in capsys.readouterr().out
    step.archive_unpack("settings.tar", overwrite=True)
    assert (ws / "config.ini").read_text() == "volume=9\n"
    step.archive_unpack("settings.tar", into="one", member="colors.ini")
    assert sorted(os.listdir(ws / "one")) == ["colors.ini"]
    with pytest.raises(ValueError, match="is not in"):
        step.archive_unpack("settings.tar", member="nope.ini")


def test_unpack_refuses_members_that_leave_the_destination(ws):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    (ws / "evil.tar").write_bytes(buf.getvalue())
    (ws / "d").mkdir()
    with pytest.raises(ValueError, match="refused member"):
        step.archive_unpack("evil.tar", into="d")
    assert not (ws / "escape.txt").exists()


def test_repacking_an_existing_archive_keeps_its_mode(ws):
    (ws / "a.txt").write_text("a\n")
    step.archive_pack("kit.tar", "a.txt")
    os.chmod(ws / "kit.tar", 0o640)
    (ws / "b.txt").write_text("b\n")
    step.archive_add("kit.tar", "b.txt")
    assert _mode(ws / "kit.tar") == 0o640


def test_pack_takes_several_space_separated_sources_without_changing_the_prompt(ws):
    (ws / "reports").mkdir()
    for name in ("north", "east", "south"):
        (ws / "reports" / f"{name}.txt").write_text(f"{name}\n")
    step.archive_pack("final.tar.gz", "reports/north.txt reports/east.txt")
    assert _members(ws / "final.tar.gz") == {"reports/north.txt": "north\n", "reports/east.txt": "east\n"}
    (ws / "my notes.txt").write_text("n\n")  # an existing name with a space is still one source
    step.archive_pack("notes.tar", "my notes.txt")
    assert _members(ws / "notes.tar") == {"my notes.txt": "n\n"}
    with pytest.raises(ValueError, match="No such file or directory: reports/west.txt"):
        step.archive_pack("x.tar", "reports/north.txt reports/west.txt")
    with pytest.raises(ValueError, match="one file"):
        step.archive_pack("two.gz", "reports/north.txt reports/east.txt")
    assert p.system_prompt(V6, version=6) == GOLDEN.read_text(encoding="utf8")  # behaviour only: prompt unchanged
