"""Development-only rename probe for interface v8 (docs/plan/INTERFACE-V8.md). Never training
data, never held-out.

Each task has a v6 oracle (list, then `mv`) and a v8 oracle (list, then `tool fs.rename`),
selected per version: the module default `Task.oracle` is the v8 oracle; `ORACLES_V6` gives the
v6 replacement by task id, the same shape `dev.oracles_v3.ORACLES` uses for `fast12_runner.with_
oracle`. Contents are small distinct text stand-ins (file extensions like .png name a role, not
real image bytes). Written from docs/plan/INTERFACE-V8.md's acceptance list, not from held-out
traces or task text; audited against every frozen held-out suite (tests/unit/test_focus_rename.py).

    .venv/bin/python -m dev.focus_runner SERVER GGUF OUT --set rename --interface 8
"""
from dev.dev_workspace import Task
from lilguy.loop import policy_of

TASKS = (
    Task(
        'rename_scan_spaces',
        'In scans/, replace the spaces in the .png scan names with dashes. Leave '
        "scans/notes.txt and other/keep me.txt alone.",
        {'scans/scan 1.png': 'scan one\n', 'scans/scan 2.png': 'scan two\n',
         'scans/scan 10.png': 'scan ten\n', 'scans/notes.txt': 'scan notes\n',
         'other/keep me.txt': 'keep me\n'},
        ('tool fs.list\npath: scans',
         'tool fs.rename\npath: scans\nrule: spaces_to_dashes\nglob: *.png',
         'done\nThe three renames are staged and pending your approval.'),
        {'scans/scan 1.png': None, 'scans/scan 2.png': None, 'scans/scan 10.png': None,
         'scans/scan-1.png': 'scan one\n', 'scans/scan-2.png': 'scan two\n',
         'scans/scan-10.png': 'scan ten\n'},
        policy_end='pending',
    ),
    Task(
        'zero_pad_scans',
        'In scans/, pad the numbers in the .png scan names to three digits '
        '(scan-1.png becomes scan-001.png). Leave scans/readme.txt and index.txt alone.',
        {'scans/scan-1.png': 'one\n', 'scans/scan-2.png': 'two\n', 'scans/scan-3.png': 'three\n',
         'scans/scan-12.png': 'twelve\n', 'scans/readme.txt': 'readme\n', 'index.txt': 'index\n'},
        ('tool fs.list\npath: scans',
         'tool fs.rename\npath: scans\nrule: zero_pad\nwidth: 3\nglob: scan-*.png',
         'done\nThe four renames are staged and pending your approval.'),
        {'scans/scan-1.png': None, 'scans/scan-2.png': None, 'scans/scan-3.png': None,
         'scans/scan-12.png': None, 'scans/scan-001.png': 'one\n', 'scans/scan-002.png': 'two\n',
         'scans/scan-003.png': 'three\n', 'scans/scan-012.png': 'twelve\n'},
        policy_end='pending',
    ),
    Task(
        'zero_pad_two_digits',
        'In scans/, pad the page numbers to two digits (page1.txt becomes page01.txt). '
        'page10.txt already has two digits.',
        {'scans/page1.txt': 'one\n', 'scans/page2.txt': 'two\n', 'scans/page10.txt': 'ten\n'},
        ('tool fs.list\npath: scans', 'tool fs.rename\npath: scans\nrule: zero_pad\nwidth: 2',
         'done\nThe two renames are staged and pending your approval.'),
        {'scans/page1.txt': None, 'scans/page2.txt': None,
         'scans/page01.txt': 'one\n', 'scans/page02.txt': 'two\n'},
        policy_end='pending',
    ),
    Task(
        'collision_existing_target',
        'In scans/, pad the page numbers to two digits (page1.txt becomes page01.txt).',
        {'scans/page1.txt': 'one\n', 'scans/page01.txt': 'old one\n'},
        ('tool fs.list\npath: scans',
         'tool fs.rename\npath: scans\nrule: zero_pad\nwidth: 2',
         'ask\nscans/page01.txt already exists; which should keep the name?'),
        {}, terminal='ask',
    ),
    Task(
        'collision_two_sources',
        'In scans/, pad the page numbers to three digits (page1.txt becomes page001.txt).',
        {'scans/page1.txt': 'first copy\n', 'scans/page01.txt': 'second copy\n',
         'scans/page2.txt': 'two\n'},
        ('tool fs.list\npath: scans',
         'tool fs.rename\npath: scans\nrule: zero_pad\nwidth: 3',
         'ask\nscans/page1.txt and scans/page01.txt both become scans/page001.txt; which should '
         'keep the name?'),
        {}, terminal='ask',
    ),
)

# The v6 replacement for each task: list, then `mv` (no fs.rename at v6). For the two collisions
# the correct v6 behaviour is also to ask without touching anything: a blind `mv` would silently
# overwrite one source, which the oracle must never do.
ORACLES_V6 = {
    'rename_scan_spaces': (
        'tool fs.list\npath: scans',
        "run\nmv -- 'scans/scan 1.png' 'scans/scan-1.png' && mv -- 'scans/scan 2.png' "
        "'scans/scan-2.png' && mv -- 'scans/scan 10.png' 'scans/scan-10.png'",
        'done\nThe three renames are staged and pending your approval.',
    ),
    'zero_pad_scans': (
        'tool fs.list\npath: scans',
        'run\nmv -- scans/scan-1.png scans/scan-001.png && mv -- scans/scan-2.png '
        'scans/scan-002.png && mv -- scans/scan-3.png scans/scan-003.png && mv -- '
        'scans/scan-12.png scans/scan-012.png',
        'done\nThe four renames are staged and pending your approval.',
    ),
    'zero_pad_two_digits': (
        'tool fs.list\npath: scans',
        'run\nmv -- scans/page1.txt scans/page01.txt && mv -- scans/page2.txt scans/page02.txt',
        'done\nThe two renames are staged and pending your approval.',
    ),
    'collision_existing_target': (
        'tool fs.list\npath: scans',
        'ask\nscans/page01.txt already exists; which should keep the name?',
    ),
    'collision_two_sources': (
        'tool fs.list\npath: scans',
        'ask\nscans/page1.txt and scans/page01.txt both become scans/page001.txt; which should '
        'keep the name?',
    ),
}

ASK = frozenset(task.id for task in TASKS if task.terminal == 'ask')
GROUPS = {'spaces to dashes': TASKS[:1], 'zero pad': TASKS[1:3], 'collisions (ask)': TASKS[3:]}


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    """Shared grader for both the ask-terminal collision tasks and the pending-rename tasks.

    Interface v8 is built on v3+: `done` carries no text (the user reviews lilguy's staged
    plan and diff, not the model's words), so only `policy`, `changes` and `terminal` are
    checked here -- there is no answer text to grade for a `done`.
    """
    failures = []
    if not original_unchanged or changes != task.changes:
        failures.append('originals or staged effects differ from expected')
    if terminal != task.terminal:
        failures.append(f'expected {task.terminal}')
    policies = tuple(policy_of(obs) for _, obs, _ in events)
    if task.terminal == 'ask':
        if changes:
            failures.append('an ask must stage nothing')
        if any(p != 'ok' for p in policies):
            failures.append('a refused rename is a plain failed step (policy ok), not a policy stop')
        rename_calls = [(a, obs, err) for a, obs, err in events if a.tool == 'fs.rename']
        for _, obs, err in rename_calls:
            if not err or 'refused' not in obs:
                failures.append('a tried fs.rename that collides must fail with a refusal')
    else:
        if not policies or policies[-1] != task.policy_end or any(p != 'ok' for p in policies[:-1]):
            failures.append('no authoritative pending stop on the final tool turn')
    return failures
