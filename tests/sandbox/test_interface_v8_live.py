"""Interface v8 live: fs.rename controls, exact previews, collisions, and end-to-end approval.

Per docs/plan/INTERFACE-V8.md and dev/focus_rename.py (disposable fixtures; never training
data, never held-out).
"""
from __future__ import annotations

import hashlib
import io
import sys

import pytest

from dev import fast12_runner as fr, focus_rename
from lilguy import do, protocol
from lilguy.policy import approval, cli as decision_cli

pytestmark = pytest.mark.sandbox
V8 = 8
V6 = 6

ROSTER = [(task, focus_rename.grade) for task in focus_rename.TASKS]


# --- 1/2: calibration controls, v8 and v6 -------------------------------------------------------

@pytest.mark.parametrize('task,grade', ROSTER, ids=[row[0].id for row in ROSTER])
def test_v8_controls(tmp_path, task, grade):
    tools = protocol.load_tools(version=V8)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, grade, version=V8)
    assert oracle['infra_error'] is None, oracle
    assert oracle['failures'] == [], (oracle['failures'], oracle['events'])
    assert oracle['terminal'] == task.terminal
    null = fr.run_false_done(tmp_path / 'null', task, tools, grade, version=V8)
    assert null['infra_error'] is None and null['failures'], null


@pytest.mark.parametrize('task,grade', ROSTER, ids=[row[0].id for row in ROSTER])
def test_v6_controls(tmp_path, task, grade):
    tools = protocol.load_tools(version=V6)
    v6_task = fr.with_oracle(task, focus_rename.ORACLES_V6[task.id])
    oracle = fr.run_oracle(tmp_path / 'oracle', v6_task, tools, grade, version=V6)
    assert oracle['infra_error'] is None, oracle
    assert oracle['failures'] == [], (oracle['failures'], oracle['events'])
    assert oracle['terminal'] == v6_task.terminal
    null = fr.run_false_done(tmp_path / 'null', v6_task, tools, grade, version=V6)
    assert null['infra_error'] is None and null['failures'], null


# --- 3: exact preview of the fs.rename observation ----------------------------------------------

@pytest.mark.parametrize('task_id', ['rename_scan_spaces', 'zero_pad_scans'])
def test_exact_preview(tmp_path, task_id):
    task = next(t for t in focus_rename.TASKS if t.id == task_id)
    tools = protocol.load_tools(version=V8)
    oracle = fr.run_oracle(tmp_path / 'o', task, tools, focus_rename.grade, version=V8)
    assert oracle['infra_error'] is None and oracle['failures'] == [], oracle
    rename_event = next(e for e in oracle['events'] if e['action']['tool'] == 'fs.rename')
    obs = rename_event['observation']
    # Build the expected preview straight from the task's own expected changes: every delete
    # paired with the add of identical content, sorted by the old path.
    deleted = sorted(path for path, text in task.changes.items() if text is None)
    pairing = []
    for old in deleted:
        old_text = task.files[old]
        new = next(p for p, t in task.changes.items() if t == old_text and p != old)
        pairing.append((old, new))
    pairing.sort(key=lambda pair: pair[0])
    count = len(pairing)
    header = f"renamed {count} file{'s' if count != 1 else ''} in scans:"
    body = [f"  {old} -> {new}" for old, new in pairing]
    assert header in obs
    for line in body:
        assert line in obs
    # the lines appear in order, right after the header
    start = obs.index(header)
    block = obs[start:start + len(header) + 1 + sum(len(line) + 1 for line in body)]
    assert block.splitlines() == [header] + body
    assert 'policy: pending (' in obs
    changes_line = next(line for line in obs.splitlines() if line.startswith('changes: '))
    for old in deleted:
        assert f'deleted {old}' in changes_line
    for _, new in pairing:
        assert f'added {new}' in changes_line


# --- 4: collisions stage nothing and leave the workspace byte-identical -------------------------

def _tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('task_id', ['collision_existing_target', 'collision_two_sources'])
def test_collisions_stage_nothing(tmp_path, task_id):
    task = next(t for t in focus_rename.TASKS if t.id == task_id)
    tools = protocol.load_tools(version=V8)
    root = tmp_path / 'o'
    oracle = fr.run_oracle(root, task, tools, focus_rename.grade, version=V8)
    assert oracle['infra_error'] is None and oracle['failures'] == [], oracle
    assert oracle['terminal'] == 'ask'
    assert oracle['changes'] == {}
    rename_event = next(e for e in oracle['events'] if e['action']['tool'] == 'fs.rename')
    assert rename_event['is_error']
    obs = rename_event['observation']
    assert 'exit=0' not in obs.split('\n', 1)[0]
    assert 'refused:' in obs and 'collision' in obs
    assert 'page1.txt' in obs and 'page01.txt' in obs  # the colliding pair is named
    workspace = root / 'work'
    expected = {rel: hashlib.sha256(text.encode('utf8')).hexdigest() for rel, text in task.files.items()}
    assert _tree_hashes(workspace) == expected


# --- 5: end to end, approve + commit through do.drive --------------------------------------------

def _script(monkeypatch, replies):
    it = iter(replies)
    monkeypatch.setattr(do, '_chat_complete', lambda *a, **k: next(it, 'done'))


def _workspace(tmp_path, files):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    for rel, text in files.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return workspace, tmp_path / 'state'


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_rename_review(summary, pairing):
    """The pending review shows exactly the mapping, every pair content-confirmed, nothing else."""
    header = 'Renames (computed by lilguy from the rule and the staged changes):'
    lines = summary.splitlines()
    start = lines.index(header)
    block = [line for line in lines[start + 1:] if line.startswith('   ')]
    assert block == [f'   renamed {old} -> {new}' for old, new in pairing], summary
    assert '! not part of the rename' not in summary


def test_end_to_end_spaces(tmp_path, monkeypatch):
    task = next(t for t in focus_rename.TASKS if t.id == 'rename_scan_spaces')
    rename_line = next(line for line in task.oracle if line.startswith('tool fs.rename'))
    extra_files = {'scans/notes.txt': task.files['scans/notes.txt'], 'other/keep me.txt': task.files['other/keep me.txt']}
    files = {k: v for k, v in task.files.items() if k not in extra_files}
    all_files = {**files, **extra_files}
    workspace, state = _workspace(tmp_path, all_files)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in all_files}

    _script(monkeypatch, [rename_line, 'done'])
    record, session_dir = do.drive('rename the scans', workspace, state, skip_preflight=True, version=V8)
    assert session_dir is not None

    for rel in all_files:
        assert (workspace / rel).read_bytes() == before_bytes[rel]
    assert _tree_hashes(workspace) == {rel: hashlib.sha256(b).hexdigest() for rel, b in before_bytes.items()}
    assert not (workspace / 'scans/scan-1.png').exists()

    deleted = sorted(path for path, text in task.changes.items() if text is None)
    added = {new: old for old in deleted
             for new, text in task.changes.items() if text is not None and text == task.files[old]}
    pairing = sorted((old, new) for new, old in added.items())

    with approval.decision_session(session_dir) as session:
        summary = approval.summarize(session)
    _assert_rename_review(summary, pairing)

    monkeypatch.setattr(sys, 'stdin', io.StringIO('y\n'))
    assert decision_cli.apply_now(session_dir) == 0

    expected_names = set(extra_files) | set(files) - set(deleted) | {new for _, new in pairing}
    final_names = {p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()}
    assert final_names == expected_names
    for old, new in pairing:
        assert not (workspace / old).exists()
        assert (workspace / new).read_bytes() == before_bytes[old]
    for rel in extra_files:
        assert (workspace / rel).read_bytes() == before_bytes[rel]


def test_end_to_end_zero_pad(tmp_path, monkeypatch):
    task = next(t for t in focus_rename.TASKS if t.id == 'zero_pad_scans')
    rename_line = next(line for line in task.oracle if line.startswith('tool fs.rename'))
    workspace, state = _workspace(tmp_path, task.files)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in task.files}

    _script(monkeypatch, [rename_line, 'done'])
    record, session_dir = do.drive('pad the scan numbers', workspace, state, skip_preflight=True, version=V8)
    assert session_dir is not None

    for rel in task.files:
        assert (workspace / rel).read_bytes() == before_bytes[rel]
    assert _tree_hashes(workspace) == {rel: hashlib.sha256(b).hexdigest() for rel, b in before_bytes.items()}

    deleted = sorted(path for path, text in task.changes.items() if text is None)
    added = {new: old for old in deleted
             for new, text in task.changes.items() if text is not None and text == task.files[old]}
    pairing = sorted((old, new) for new, old in added.items())

    with approval.decision_session(session_dir) as session:
        summary = approval.summarize(session)
    _assert_rename_review(summary, pairing)

    monkeypatch.setattr(sys, 'stdin', io.StringIO('y\n'))
    assert decision_cli.apply_now(session_dir) == 0

    expected_names = set(task.files) - set(deleted) | {new for _, new in pairing}
    final_names = {p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()}
    assert final_names == expected_names
    for old, new in pairing:
        assert not (workspace / old).exists()
        assert (workspace / new).read_bytes() == before_bytes[old]


# --- 6: a collision commits nothing ---------------------------------------------------------------

def test_end_to_end_collision(tmp_path, monkeypatch):
    task = next(t for t in focus_rename.TASKS if t.id == 'collision_existing_target')
    rename_line = next(line for line in task.oracle if line.startswith('tool fs.rename'))
    workspace, state = _workspace(tmp_path, task.files)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in task.files}

    _script(monkeypatch, [rename_line, 'ask\nscans/page01.txt already exists; which should keep the name?'])
    record, session_dir = do.drive('pad the page numbers', workspace, state, skip_preflight=True, version=V8)

    for rel in task.files:
        assert (workspace / rel).read_bytes() == before_bytes[rel]
    assert record.terminal == 'ask'

    if session_dir is not None:
        from lilguy.sandbox.diff import session_diff
        from lilguy.sandbox import persist
        assert not (session_dir / 'approval-request.json').exists()
        session = persist.load_session(session_dir)
        assert session_diff(session) == []


# --- 7: fs.rename is not served on v6 --------------------------------------------------------------

def test_rename_is_not_served_on_v6():
    tools_v6 = protocol.load_tools(version=V6)
    assert 'fs.rename' not in tools_v6
    with pytest.raises(protocol.ProtocolError, match='unknown tool'):
        protocol.parse_action('tool fs.rename\npath: scans\nrule: spaces_to_dashes', tools_v6, version=V6)

    from lilguy import mcp_server
    v6_mcp_tools = mcp_server.build_v1_tools(version=V6)
    assert 'fs.rename' not in v6_mcp_tools
    v8_mcp_tools = mcp_server.build_v1_tools(version=V8)
    assert 'fs.rename' in v8_mcp_tools


# --- 8: edge cases ---------------------------------------------------------------------------

def test_arrow_in_name_end_to_end(tmp_path, monkeypatch):
    """A literal '->' inside a file name must not confuse the exact preview or the review."""
    from lilguy._typed_step import rename_target
    files = {'scans/a b -> c.txt': 'arrow file\n', 'scans/x y.txt': 'other file\n'}
    workspace, state = _workspace(tmp_path, files)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in files}

    old_name = 'a b -> c.txt'
    new_name = rename_target(old_name, 'spaces_to_dashes')
    old_path, new_path = f'scans/{old_name}', f'scans/{new_name}'

    rename_line = 'tool fs.rename\npath: scans\nrule: spaces_to_dashes\nglob: a b*.txt'
    _script(monkeypatch, [rename_line, 'done'])
    record, session_dir = do.drive('rename the scans', workspace, state, skip_preflight=True, version=V8)
    assert session_dir is not None

    for rel in files:
        assert (workspace / rel).read_bytes() == before_bytes[rel]

    with approval.decision_session(session_dir) as session:
        summary = approval.summarize(session)
    _assert_rename_review(summary, [(old_path, new_path)])

    monkeypatch.setattr(sys, 'stdin', io.StringIO('y\n'))
    assert decision_cli.apply_now(session_dir) == 0

    assert not (workspace / old_path).exists()
    assert (workspace / new_path).read_bytes() == before_bytes[old_path]
    assert (workspace / 'scans/x y.txt').read_bytes() == before_bytes['scans/x y.txt']


def test_target_is_directory_or_symlink_refuses_and_stages_nothing(tmp_path, monkeypatch):
    """A rename target that already exists -- as a directory or as a symlink -- is a refusal
    naming the collision; nothing is staged and the real workspace (including the symlink
    itself) is left byte- and link-identical."""
    import os as _os
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    scans = workspace / 'scans'
    scans.mkdir()
    (scans / 'a b.txt').write_text('a b contents\n')
    target_dir = scans / 'a-b.txt'
    target_dir.mkdir()
    (target_dir / 'inner.txt').write_text('inner\n')
    (scans / 'c d.txt').write_text('c d contents\n')
    (workspace / 'elsewhere.txt').write_text('elsewhere contents\n')
    _os.symlink('../elsewhere.txt', scans / 'c-d.txt')
    state = tmp_path / 'state'

    before_tree = _tree_hashes(workspace)
    before_link = _os.readlink(scans / 'c-d.txt')

    rename_line = 'tool fs.rename\npath: scans\nrule: spaces_to_dashes'
    _script(monkeypatch, [rename_line,
                          'ask\nscans/a-b.txt and scans/c-d.txt already exist; which should keep the name?'])
    record, session_dir = do.drive('rename the scans', workspace, state, skip_preflight=True, version=V8)
    assert record.terminal == 'ask'

    rename_turn = next(t for t in record.turns if t.action.tool == 'fs.rename')
    assert rename_turn.is_error
    obs = rename_turn.observation
    assert 'exit=0' not in obs.split('\n', 1)[0]
    assert 'refused:' in obs and 'collision' in obs
    assert 'changes: none' in obs

    if session_dir is not None:
        from lilguy.sandbox.diff import session_diff
        from lilguy.sandbox import persist
        assert not (session_dir / 'approval-request.json').exists()
        session = persist.load_session(session_dir)
        assert session_diff(session) == []

    assert _tree_hashes(workspace) == before_tree
    assert target_dir.is_dir() and not target_dir.is_symlink()
    assert (scans / 'c-d.txt').is_symlink()
    assert _os.readlink(scans / 'c-d.txt') == before_link


def test_zero_pad_25_files_sorted_review_and_exact_result(tmp_path, monkeypatch):
    """25 files zero-padded to width 3: workspace stays byte-identical before approval, the
    review lists all 25 pairs sorted with no '!' lines, and the commit yields exactly the
    padded names with the original bytes."""
    files = {f'scans/page{i}.txt': f'page {i} contents\n' for i in range(1, 26)}
    workspace, state = _workspace(tmp_path, files)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in files}
    before_tree = _tree_hashes(workspace)

    rename_line = 'tool fs.rename\npath: scans\nrule: zero_pad\nwidth: 3'
    _script(monkeypatch, [rename_line, 'done'])
    record, session_dir = do.drive('pad the scan numbers', workspace, state, skip_preflight=True, version=V8)
    assert session_dir is not None

    assert _tree_hashes(workspace) == before_tree

    pairing = sorted((f'scans/page{i}.txt', f'scans/page{i:03d}.txt') for i in range(1, 26))
    with approval.decision_session(session_dir) as session:
        summary = approval.summarize(session, limit=100)
    _assert_rename_review(summary, pairing)

    monkeypatch.setattr(sys, 'stdin', io.StringIO('y\n'))
    assert decision_cli.apply_now(session_dir) == 0

    expected_names = {f'scans/page{i:03d}.txt' for i in range(1, 26)}
    final_names = {p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()}
    assert final_names == expected_names
    for old, new in pairing:
        assert not (workspace / old).exists()
        assert (workspace / new).read_bytes() == before_bytes[old]


def test_mode_preserved_through_rename(tmp_path, monkeypatch):
    """A renamed file keeps its permission bits (sandbox fs.rename is not a copy+rewrite)."""
    import stat as _stat
    files = {'scans/scan 1.png': 'scan one\n', 'scans/run me.sh': '#!/bin/sh\necho hi\n'}
    workspace, state = _workspace(tmp_path, files)
    (workspace / 'scans/scan 1.png').chmod(0o640)
    (workspace / 'scans/run me.sh').chmod(0o755)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in files}

    rename_line = 'tool fs.rename\npath: scans\nrule: spaces_to_dashes'
    _script(monkeypatch, [rename_line, 'done'])
    record, session_dir = do.drive('rename the scans', workspace, state, skip_preflight=True, version=V8)
    assert session_dir is not None

    monkeypatch.setattr(sys, 'stdin', io.StringIO('y\n'))
    assert decision_cli.apply_now(session_dir) == 0

    assert not (workspace / 'scans/scan 1.png').exists()
    assert not (workspace / 'scans/run me.sh').exists()
    new_png = workspace / 'scans/scan-1.png'
    new_sh = workspace / 'scans/run-me.sh'
    assert new_png.read_bytes() == before_bytes['scans/scan 1.png']
    assert new_sh.read_bytes() == before_bytes['scans/run me.sh']
    assert _stat.S_IMODE(new_png.stat().st_mode) == 0o640
    assert _stat.S_IMODE(new_sh.stat().st_mode) == 0o755


def test_unrelated_files_untouched_by_rename_commit(tmp_path, monkeypatch):
    """Files outside the rename's folder, and files in the same folder excluded by glob, keep
    their bytes and mtimes unchanged after the rename is committed."""
    import time
    files = {
        'scans/scan 1.png': 'scan one\n',
        'scans/notes.txt': 'notes, excluded by glob\n',
        'other/keep me.txt': 'keep me, different folder\n',
    }
    workspace, state = _workspace(tmp_path, files)
    before_bytes = {rel: (workspace / rel).read_bytes() for rel in files}
    # Age the two files that must stay untouched so their mtime is distinguishable from "now".
    old_time = time.time() - 10_000
    for rel in ('scans/notes.txt', 'other/keep me.txt'):
        _os_utime(workspace / rel, (old_time, old_time))
    before_mtimes = {rel: (workspace / rel).stat().st_mtime_ns for rel in files}

    rename_line = 'tool fs.rename\npath: scans\nrule: spaces_to_dashes\nglob: *.png'
    _script(monkeypatch, [rename_line, 'done'])
    record, session_dir = do.drive('rename the scans', workspace, state, skip_preflight=True, version=V8)
    assert session_dir is not None

    monkeypatch.setattr(sys, 'stdin', io.StringIO('y\n'))
    assert decision_cli.apply_now(session_dir) == 0

    assert not (workspace / 'scans/scan 1.png').exists()
    assert (workspace / 'scans/scan-1.png').read_bytes() == before_bytes['scans/scan 1.png']
    for rel in ('scans/notes.txt', 'other/keep me.txt'):
        assert (workspace / rel).read_bytes() == before_bytes[rel]
        assert (workspace / rel).stat().st_mtime_ns == before_mtimes[rel]


def _os_utime(path, times):
    import os
    os.utime(path, times)
