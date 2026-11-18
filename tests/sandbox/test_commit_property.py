"""Property: commit(real layered diff) matches actual merged view, then undo restores base."""
import json

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from lilguy.sandbox.backend import RunSpec, SessionConfig

pytestmark = pytest.mark.sandbox


@pytest.fixture(scope="module", autouse=True)
def require_sandbox():
    from lilguy.probe import run_probe
    failures = [r.detail for r in run_probe() if r.required and r.status == "fail"]
    if failures:
        pytest.skip("sandbox unavailable: " + "; ".join(failures))


operations = st.lists(st.tuples(st.sampled_from(["write", "delete"]),
                                st.sampled_from(["a", "b", "nested/c"]),
                                st.text(alphabet="abc123", max_size=12)), min_size=1, max_size=5)


@given(operations)
@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_commit_matches_real_merged_overlay_and_undo(tmp_path, ops):
    import tempfile
    from pathlib import Path
    from lilguy.sandbox.bwrap import BwrapBackend
    from lilguy.policy.commit import commit, diff_hash, undo
    from lilguy.sandbox.diff import session_diff
    from lilguy.sandbox.layers import resolve
    with tempfile.TemporaryDirectory(dir=tmp_path) as root:
        root = Path(root)
        ws = root / "ws"
        ws.mkdir()
        (ws / "a").write_text("original")
        (ws / "nested").mkdir()
        (ws / "nested" / "c").write_text("base")
        before = {p.relative_to(ws).as_posix(): p.read_text() for p in ws.rglob("*") if p.is_file()}
        backend = BwrapBackend()
        session = backend.open_session(ws, SessionConfig(state_dir=root / "state", timeout_s=2))
        script = """import json,sys
from pathlib import Path
op,name,content=json.loads(sys.argv[1])
p=Path(name)
if op=='write':
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(content)
else:
 p.unlink(missing_ok=True)
"""
        try:
            for op in ops:
                result = backend.run(session, RunSpec(argv=["python3", "-c", script, json.dumps(op)]))
                assert result.exit_code == 0, result.stderr
            view = backend.run(session, RunSpec(argv=["python3", "-c",
                "import json; from pathlib import Path; print(json.dumps({p.as_posix():p.read_text() for p in Path('.').rglob('*') if p.is_file()}))"]))
            assert view.exit_code == 0, view.stderr
            expected = json.loads(view.stdout)
            entries = session_diff(session)
            approved = diff_hash(entries, session, resolve)  # trusted fixture approver, never model output
            commit_id = commit(session, approved_hash=approved)
            actual = {p.relative_to(ws).as_posix(): p.read_text() for p in ws.rglob("*") if p.is_file()}
            assert actual == expected
            undo(ws, session.cfg.state_dir, commit_id)
            restored = {p.relative_to(ws).as_posix(): p.read_text() for p in ws.rglob("*") if p.is_file()}
            assert restored == before
        finally:
            backend.discard(session)
