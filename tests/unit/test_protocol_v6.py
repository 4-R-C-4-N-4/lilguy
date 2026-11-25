"""Interface v6: typed permission and archive tools (docs/plan/INTERFACE-V6.md); v1-v5 unchanged."""
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
    assert "use fs.chmod and the archive tools rather than chmod or tar" in prompt
    assert "fs.chmod" not in v5 and "archive." not in v5


def test_tools_are_gated_by_version_and_the_frozen_manifest_is_unchanged():
    for version in (1, 2, 3, 4, 5):
        assert tuple(p.load_tools(version=version)) == p.TOOLS_V1
        assert tuple(build_v1_tools(version)) == ("run", *p.TOOLS_V1)
    assert tuple(V6) == p.TOOLS_V1 + p.TOOLS_V6
    assert tuple(build_v1_tools(6)) == ("run", *p.TOOLS_V1, *p.TOOLS_V6)
    assert tuple(p.load_tools()) == p.TOOLS_V1  # the shipped interface (v4)


def test_v6_actions_round_trip_and_the_grammar_names_every_tool():
    action = p.Action.call("fs.chmod", path="draft.txt", user="read write", group="none", others="none")
    text = p.render_action(action, V6, version=6)
    assert text == "tool fs.chmod\npath: draft.txt\nuser: read write\ngroup: none\nothers: none"
    parsed = p.parse_action(text, V6, version=6)
    assert (parsed.kind, parsed.tool, parsed.args) == ("tool", "fs.chmod", action.args)
    grammar = p.grammar(V6, version=6)
    for name in p.TOOLS_V6:
        assert name in grammar
    assert '"read write execute"' in grammar and '"add execute"' in grammar


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


def test_chmod_owner_only_is_one_call_and_add_is_relative(ws, capsys):
    (ws / "draft.txt").write_text("d\n")
    os.chmod(ws / "draft.txt", 0o644)
    step.chmod("draft.txt", user="read write", group="none", others="none")
    assert _mode(ws / "draft.txt") == 0o600
    assert capsys.readouterr().out == "draft.txt: rw-r--r-- -> rw-------\n"
    step.chmod("draft.txt", group="add execute")
    assert _mode(ws / "draft.txt") == 0o610
    step.chmod("draft.txt", user="remove write", others="read")
    assert _mode(ws / "draft.txt") == 0o414
    with pytest.raises(ValueError, match="Nothing to change"):
        step.chmod("draft.txt")
    with pytest.raises(ValueError, match="No such file or directory"):
        step.chmod("missing.sh", user="add execute")


def test_chmod_globs_recurses_and_never_follows_symlinks(ws, capsys):
    (ws / "helpers").mkdir()
    for name in ("a.sh", "b.sh", "README"):
        (ws / "helpers" / name).write_text("x\n")
        os.chmod(ws / "helpers" / name, 0o644)
    step.chmod("helpers/*.sh", group="add execute")
    assert [_mode(ws / "helpers" / n) for n in ("a.sh", "b.sh", "README")] == [0o654, 0o654, 0o644]
    with pytest.raises(ValueError, match="No such file or directory"):
        step.chmod("helpers/*.py", user="add execute")
    (ws / "bin").mkdir()
    (ws / "bin" / "x").write_text("x\n")
    (ws / "bin" / "link").symlink_to("x")
    os.chmod(ws / "bin" / "x", 0o644)
    step.chmod("bin", others="add execute", recursive=True)
    assert _mode(ws / "bin" / "x") == 0o645
    with pytest.raises(ValueError, match="symbolic link"):
        step.chmod("bin/link", user="add execute")


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


def test_chmod_glob_cannot_leave_the_workspace(ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "x.sh").write_text("x\n")
    with pytest.raises(ValueError, match="workspace-relative"):
        step.chmod(f"../{outside.name}/*.sh", user="add execute")
    with pytest.raises(ValueError, match="workspace-relative"):
        step.chmod(f"{outside}/*.sh", user="add execute")
