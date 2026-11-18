"""Named P1 acceptance scenarios on real overlays, never the host shell."""
import errno
import json
import os
import shutil
import time

import pytest

from lilguy.sandbox.backend import RunSpec, SessionConfig
from lilguy.sandbox.bwrap import BwrapBackend

pytestmark = pytest.mark.sandbox


@pytest.fixture
def session(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    backend = BwrapBackend()
    s = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", timeout_s=5))
    try:
        yield backend, s
    finally:
        backend.discard(s)


def test_three_layers_net_effect_and_top_rollback(session):
    backend, s = session
    # Fixture data added before commands; no commit occurs in this test.
    (s.workspace / "a").write_text("original")
    for content in ("one", "two", "three"):
        result = backend.run(s, RunSpec(argv=["python3", "-c",
            "from pathlib import Path; import sys; Path('a').write_text(sys.argv[1])", content]))
        assert result.exit_code == 0, result.stderr
    entries = backend.session_diff(s)
    assert len(s.uppers) == 3
    assert len(entries) == 1
    assert entries[0].op == "modified"
    assert entries[0].size_before == len("original")
    assert entries[0].size_after == len("three")
    backend.rollback_step(s)
    assert backend.resolve(s, "a").read_text() == "two"
    assert (s.workspace / "a").read_text() == "original"


def test_directory_rename_probe_and_mv_fallback(session, record_property):
    backend, s = session
    (s.workspace / "tree" / "sub").mkdir(parents=True)
    (s.workspace / "tree" / "sub" / "a").write_text("preserved")
    result = backend.run(s, RunSpec(argv=["python3", "-c", """import os,json
try:
 os.rename('tree','renamed')
 print(json.dumps({'errno':0}))
except OSError as e:
 print(json.dumps({'errno':e.errno}))
"""]))
    assert result.exit_code == 0, result.stderr
    observed = json.loads(result.stdout)["errno"]
    assert observed in (0, errno.EXDEV)
    record_property("native_rename_errno", observed)
    if observed == errno.EXDEV:
        result = backend.run(s, RunSpec(argv=["mv", "--", "tree", "renamed"]))
        assert result.exit_code == 0, result.stderr
    entries = backend.session_diff(s)
    assert any(e.path == "tree/sub/a" and e.op == "deleted" for e in entries)
    assert any(e.path == "renamed/sub/a" and e.op == "added" for e in entries)
    assert backend.resolve(s, "tree/sub/a") is None
    assert backend.resolve(s, "renamed/sub/a").read_text() == "preserved"
    assert (s.workspace / "tree" / "sub" / "a").read_text() == "preserved"
    assert not (s.workspace / "renamed").exists()


def test_delete_and_recreate_directory_is_opaque(session):
    backend, s = session
    (s.workspace / "d").mkdir()
    (s.workspace / "d" / "old").write_text("old")
    result = backend.run(s, RunSpec(shell="rm -rf -- d; mkdir d; printf new > d/new"))
    assert result.exit_code == 0, result.stderr
    assert os.getxattr(s.uppers[-1] / "d", "user.overlay.opaque") == b"y"
    entries = backend.session_diff(s)
    assert any(e.path == "d" and e.op == "replaced_dir" for e in entries)
    assert any(e.path == "d/old" and e.op == "deleted" for e in entries)
    assert any(e.path == "d/new" and e.op == "added" for e in entries)


def test_hardlink_copyup_keeps_host_inode_and_other_content(session):
    backend, s = session
    (s.workspace / "a").write_text("old")
    os.link(s.workspace / "a", s.workspace / "b")
    host_inode = (s.workspace / "a").stat().st_ino
    result = backend.run(s, RunSpec(shell="printf new > a; cat b"))
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "old"
    assert backend.resolve(s, "a").read_text() == "new"
    assert (s.workspace / "a").stat().st_ino == host_inode
    assert (s.workspace / "b").stat().st_ino == host_inode
    assert (s.workspace / "a").read_text() == "old"
    assert (s.workspace / "b").read_text() == "old"


def test_100mb_append_measures_copyup(tmp_path, record_property):
    if shutil.disk_usage(tmp_path).free < 1024 * 1024 * 1024:
        pytest.skip("refusing 100MB fixture with less than 1GiB free scratch space")
    ws = tmp_path / "workspace"
    ws.mkdir()
    size = 100_000_000
    with (ws / "large").open("wb") as stream:
        block = b"x" * 1_000_000
        for _ in range(100):
            stream.write(block)
    backend = BwrapBackend()
    s = backend.open_session(ws, SessionConfig(state_dir=tmp_path / "state", timeout_s=5,
                            max_file_bytes=128 * 1024 * 1024, max_upper_bytes=160 * 1024 * 1024))
    try:
        start = time.perf_counter()
        result = backend.run(s, RunSpec(shell="printf y >> large"))
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert result.exit_code == 0, result.stderr
        resolved = backend.resolve(s, "large")
        assert resolved.stat().st_size == size + 1
        assert (ws / "large").stat().st_size == size
        assert result.step_diff[0].op == "modified"
        record_property("copyup_wall_ms", elapsed_ms)
        record_property("copyup_allocated_bytes", resolved.stat().st_blocks * 512)
    finally:
        backend.discard(s)


def test_type_replacement_duplicate_diff_commits_and_undoes(session):
    backend, s = session
    (s.workspace / "d").mkdir()
    (s.workspace / "d" / "a").write_text("old")
    # Capture the actual opening state for this fixture before untrusted execution.
    from lilguy.policy.commit import capture_snapshot, save_snapshot, commit, diff_hash, undo
    save_snapshot(s.directory, capture_snapshot(s.workspace))
    result = backend.run(s, RunSpec(shell="rm -rf -- d; printf new > d"))
    assert result.exit_code == 0, result.stderr
    entries = backend.session_diff(s)
    assert sum(e.path == "d" for e in entries) == 2
    digest = diff_hash(entries, s, backend.resolve)
    commit_id = commit(s, approved_hash=digest)
    assert (s.workspace / "d").read_text() == "new"
    undo(s.workspace, s.cfg.state_dir, commit_id)
    assert (s.workspace / "d" / "a").read_text() == "old"
