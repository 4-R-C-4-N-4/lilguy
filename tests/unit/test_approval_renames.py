"""Unit tests for lilguy.policy.renames and the rename block in approval.summarize()."""
import json

from lilguy.policy import approval, renames
from lilguy.policy.renames import rename_plan


def _change(op, path, kind="file", size_before=None, size_after=None):
    return {"op": op, "path": path, "kind": kind, "size_before": size_before,
            "size_after": size_after, "mode_before": None, "mode_after": None,
            "symlink_target": None, "is_binary": False}


def _request(tool, args, changes, **extra):
    # step_paths defaults to covering every change, so existing tests that don't care about the
    # step_paths restriction keep getting the old, unrestricted behaviour unless they override it.
    request = {"session_id": "s", "workspace": "/ws", "diff_hash": "abc123",
               "rule": "any_delete_outside", "summary": None,
               "command": {"tool": tool, "args": args}, "changes": changes,
               "new_paths": [c["path"] for c in changes if c["op"] == "added"],
               "stopped": [], "exit_code": 0, "layers": 1,
               "step_paths": [c["path"] for c in changes]}
    request.update(extra)
    return request


# --- rename_plan() ------------------------------------------------------------------------------

def test_non_rename_tool_returns_none():
    request = _request("fs.append", [["path", "a.txt"]], [])
    assert rename_plan(request) is None


def test_spaces_to_dashes_confirmed_pair_without_session():
    changes = [
        _change("deleted", "scans/scan 1.png", size_before=100, size_after=None),
        _change("added", "scans/scan-1.png", size_before=None, size_after=100),
    ]
    request = _request("fs.rename", [["path", "scans"], ["rule", "spaces_to_dashes"],
                                      ["glob", "<5 chars>"]], changes)
    plan = rename_plan(request)
    assert plan.pairs == [("scans/scan 1.png", "scans/scan-1.png")]
    assert plan.unexplained == []


def test_zero_pad_width_3_confirmed_pair():
    changes = [
        _change("deleted", "scan2.png", size_before=50, size_after=None),
        _change("added", "scan002.png", size_before=None, size_after=50),
    ]
    request = _request("fs.rename", [["path", "."], ["rule", "zero_pad"], ["width", 3]], changes)
    plan = rename_plan(request)
    assert plan.pairs == [("scan2.png", "scan002.png")]
    assert plan.unexplained == []


def test_size_mismatch_leaves_both_sides_unexplained():
    changes = [
        _change("deleted", "scan2.png", size_before=50, size_after=None),
        _change("added", "scan002.png", size_before=None, size_after=51),
    ]
    request = _request("fs.rename", [["rule", "zero_pad"], ["width", 3]], changes)
    plan = rename_plan(request)
    assert plan.pairs == []
    assert ("deleted", "scan2.png") in plan.unexplained
    assert ("added", "scan002.png") in plan.unexplained


def test_extra_modified_file_is_flagged_unexplained():
    changes = [
        _change("deleted", "scan2.png", size_before=50, size_after=None),
        _change("added", "scan002.png", size_before=None, size_after=50),
        _change("modified", "notes.txt", size_before=10, size_after=12),
    ]
    request = _request("fs.rename", [["rule", "zero_pad"], ["width", 3]], changes)
    plan = rename_plan(request)
    assert plan.pairs == [("scan2.png", "scan002.png")]
    assert plan.unexplained == [("modified", "notes.txt")]


def test_malformed_request_is_not_explained_without_raising():
    request = {"command": {"tool": "fs.rename", "args": "garbage"}, "changes": "also garbage"}
    plan = rename_plan(request)
    assert plan is not None
    assert plan.pairs == []
    assert plan.unexplained == []


def test_control_characters_in_names_pass_through_cleanly():
    changes = [
        _change("deleted", "sc an\x07.png", size_before=10, size_after=None),
        _change("added", "sc-an\x07.png", size_before=None, size_after=10),
    ]
    request = _request("fs.rename", [["rule", "spaces_to_dashes"]], changes)
    plan = rename_plan(request)
    assert plan.pairs == [("sc an\x07.png", "sc-an\x07.png")]
    assert approval._clean(plan.pairs[0][0]) == "sc an\\x07.png"
    assert approval._clean(plan.pairs[0][1]) == "sc-an\\x07.png"


# --- summarize() -----------------------------------------------------------------------------

def _staged_session(tmp_path):
    from lilguy.sandbox import layers
    from lilguy.sandbox.backend import SessionConfig

    ws = tmp_path / "ws"
    (ws / "scans").mkdir(parents=True)
    (ws / "scans" / "scan 1.png").write_bytes(b"x" * 10)
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    layers.new_layer(session)
    return session


def test_summarize_includes_renamed_line_for_rename_request(tmp_path, monkeypatch):
    session = _staged_session(tmp_path)
    # Byte-level confirmation needs a real overlay whiteout + staged copy, which unit tests
    # cannot create without root; per sandbox/diff.py this layer is exercised in tests by
    # stubbing the overlay primitive, here the equivalent staged-bytes check.
    monkeypatch.setattr(renames, "_confirm_bytes", lambda s, old, new: True)

    changes = [
        _change("deleted", "scans/scan 1.png", size_before=10, size_after=None),
        _change("added", "scans/scan-1.png", size_before=None, size_after=10),
    ]
    request = _request("fs.rename",
                        [["path", "scans"], ["rule", "spaces_to_dashes"], ["glob", "<5 chars>"]],
                        changes, new_paths=["scans/scan-1.png"])
    (session.directory / "approval-request.json").write_text(json.dumps(request, sort_keys=True))

    text = approval.summarize(session)
    assert "renamed scans/scan 1.png -> scans/scan-1.png" in text
    assert "! not part of the rename" not in text


def test_summarize_flags_unconfirmed_pair_when_bytes_differ(tmp_path, monkeypatch):
    session = _staged_session(tmp_path)
    monkeypatch.setattr(renames, "_confirm_bytes", lambda s, old, new: False)

    changes = [
        _change("deleted", "scans/scan 1.png", size_before=10, size_after=None),
        _change("added", "scans/scan-1.png", size_before=None, size_after=10),
    ]
    request = _request("fs.rename",
                        [["path", "scans"], ["rule", "spaces_to_dashes"], ["glob", "<5 chars>"]],
                        changes, new_paths=["scans/scan-1.png"])
    (session.directory / "approval-request.json").write_text(json.dumps(request, sort_keys=True))

    text = approval.summarize(session)
    assert "renamed scans/scan 1.png -> scans/scan-1.png" not in text
    assert "! not part of the rename: deleted scans/scan 1.png" in text
    assert "! not part of the rename: added scans/scan-1.png" in text


def test_step_paths_restricts_confirmed_pairs_to_pending_step(tmp_path, monkeypatch):
    """Only changes inside step_paths (the pending step's own diff) can be a confirmed rename
    pair; a byte/size-consistent delete+add pair from an earlier session step is reported as
    unexplained even though it would otherwise look like a valid rename."""
    monkeypatch.setattr(renames, "_confirm_bytes", lambda s, old, new: True)
    changes = [
        _change("deleted", "scans/a b.txt", size_before=5, size_after=None),
        _change("added", "scans/a-b.txt", size_before=None, size_after=5),
        _change("deleted", "scans/c d.txt", size_before=7, size_after=None),
        _change("added", "scans/c-d.txt", size_before=None, size_after=7),
    ]
    request = _request("fs.rename", [["rule", "spaces_to_dashes"]], changes,
                        step_paths=["scans/c d.txt", "scans/c-d.txt"],
                        new_paths=["scans/a-b.txt", "scans/c-d.txt"])

    plan = rename_plan(request)
    assert plan.pairs == [("scans/c d.txt", "scans/c-d.txt")]
    assert ("deleted", "scans/a b.txt") in plan.unexplained
    assert ("added", "scans/a-b.txt") in plan.unexplained

    session = _staged_session(tmp_path)
    (session.directory / "approval-request.json").write_text(json.dumps(request, sort_keys=True))
    text = approval.summarize(session)
    assert "renamed scans/c d.txt -> scans/c-d.txt" in text
    assert "! not part of the rename: deleted scans/a b.txt" in text
    assert "! not part of the rename: added scans/a-b.txt" in text


def test_without_step_paths_confirms_all_pairs():
    """Previous behaviour: a request with no 'step_paths' key does not restrict anything, so
    every size-consistent delete+add pair is confirmed as a rename."""
    changes = [
        _change("deleted", "scans/a b.txt", size_before=5, size_after=None),
        _change("added", "scans/a-b.txt", size_before=None, size_after=5),
        _change("deleted", "scans/c d.txt", size_before=7, size_after=None),
        _change("added", "scans/c-d.txt", size_before=None, size_after=7),
    ]
    request = _request("fs.rename", [["rule", "spaces_to_dashes"]], changes)
    del request["step_paths"]
    plan = rename_plan(request)
    assert plan.pairs == [("scans/a b.txt", "scans/a-b.txt"), ("scans/c d.txt", "scans/c-d.txt")]
    assert plan.unexplained == []


def test_summarize_byte_identical_for_non_rename_request(tmp_path):
    """summarize() output for a non-fs.rename request must never gain the rename block."""
    from lilguy.sandbox import layers
    from lilguy.sandbox.backend import SessionConfig

    ws = tmp_path / "ws"
    ws.mkdir()
    session = layers.open_session(ws, SessionConfig(state_dir=tmp_path / "state"))
    layers.new_layer(session)

    changes = [_change("added", "notes.txt", size_before=None, size_after=5)]
    request = _request("exec", [], changes, new_paths=["notes.txt"])
    request["command"] = {"argv": ["sh", "-c", "echo hi > notes.txt"]}
    (session.directory / "approval-request.json").write_text(json.dumps(request, sort_keys=True))

    text = approval.summarize(session)
    assert "Renames (computed by lilguy" not in text
    assert "renamed " not in text
    assert text == approval.summarize(session)
