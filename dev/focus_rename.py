"""Development-only rename probe for interface v8 (docs/plan/INTERFACE-V8.md). Never training
data, never held-out.

Each task has a v6 oracle (list, then `mv`/`cp`) and a v8 oracle (list, then `tool fs.rename`
when that is the right tool), selected per version: the module default `Task.oracle` is the v8
oracle; `ORACLES_V6` gives the v6 replacement by task id, the same shape `dev.oracles_v3.ORACLES`
uses for `fast12_runner.with_oracle`. Call `oracles(version)` (used by `dev.focus_runner`) to pick
the right dict: `ORACLES_V6` below version 8, nothing above it. Contents are small distinct text
stand-ins (file extensions like .png name a role, not real image bytes). Written from
docs/plan/INTERFACE-V8.md's acceptance list, not from held-out traces or task text; audited
against every frozen held-out suite (tests/unit/test_focus_rename.py).

Four groups (20 tasks): 'spaces to dashes' (6), 'zero pad' (7), 'collisions (ask)' (3), and
'not a bulk rename (twins)' (4) -- near-misses where fs.rename is *not* the right tool (a single
named rename, a copy that keeps the originals, lowercasing, and stripping a literal prefix are
none of fs.rename's two rules), so the correct oracle on both v6 and v8 is a scripted `mv`/`cp`.

    .venv/bin/python -m dev.focus_runner SERVER GGUF OUT --set rename --interface 8
"""
from dev.dev_workspace import Task
from lilguy.loop import policy_of

TASKS = (
    # --- spaces to dashes (6) --------------------------------------------------------------
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
        'spaces_photo_set',
        'Rename the .jpg files in photos/ so spaces become dashes. Leave photos/caption.txt '
        'and archive/old photo.jpg alone.',
        {'photos/photo one.jpg': 'one\n', 'photos/photo two.jpg': 'two\n',
         'photos/photo three.jpg': 'three\n', 'photos/photo four.jpg': 'four\n',
         'photos/caption.txt': 'caption\n', 'archive/old photo.jpg': 'old\n'},
        ('tool fs.list\npath: photos',
         'tool fs.rename\npath: photos\nrule: spaces_to_dashes\nglob: *.jpg',
         'done\nThe four renames are staged and pending your approval.'),
        {'photos/photo one.jpg': None, 'photos/photo two.jpg': None,
         'photos/photo three.jpg': None, 'photos/photo four.jpg': None,
         'photos/photo-one.jpg': 'one\n', 'photos/photo-two.jpg': 'two\n',
         'photos/photo-three.jpg': 'three\n', 'photos/photo-four.jpg': 'four\n'},
        policy_end='pending',
    ),
    Task(
        'spaces_music_tracks',
        'music/: replace spaces with dashes in the track names.',
        {'music/track one.wav': 'one\n', 'music/track two.wav': 'two\n',
         'music/track-three.wav': 'three\n'},
        ('tool fs.list\npath: music', 'tool fs.rename\npath: music\nrule: spaces_to_dashes',
         'done\nThe two renames are staged and pending your approval.'),
        {'music/track one.wav': None, 'music/track two.wav': None,
         'music/track-one.wav': 'one\n', 'music/track-two.wav': 'two\n'},
        policy_end='pending',
    ),
    Task(
        'spaces_docs_already_dashed',
        'In docs/, rename the files so spaces become dashes. docs/already-fine.md has no '
        'spaces so leave it as is.',
        {'docs/file one.md': 'file one\n', 'docs/another one.md': 'another one\n',
         'docs/already-fine.md': 'fine\n'},
        ('tool fs.list\npath: docs', 'tool fs.rename\npath: docs\nrule: spaces_to_dashes',
         'done\nThe two renames are staged and pending your approval.'),
        {'docs/file one.md': None, 'docs/another one.md': None,
         'docs/file-one.md': 'file one\n', 'docs/another-one.md': 'another one\n'},
        policy_end='pending',
    ),
    Task(
        'spaces_receipts_no_glob',
        'Rename the files in receipts/ so spaces in the names become dashes.',
        {'receipts/receipt jan.pdf': 'jan\n', 'receipts/receipt feb.pdf': 'feb\n',
         'receipts/receipt mar.pdf': 'mar\n', 'receipts/summary.csv': 'summary\n'},
        ('tool fs.list\npath: receipts', 'tool fs.rename\npath: receipts\nrule: spaces_to_dashes',
         'done\nThe three renames are staged and pending your approval.'),
        {'receipts/receipt jan.pdf': None, 'receipts/receipt feb.pdf': None,
         'receipts/receipt mar.pdf': None, 'receipts/receipt-jan.pdf': 'jan\n',
         'receipts/receipt-feb.pdf': 'feb\n', 'receipts/receipt-mar.pdf': 'mar\n'},
        policy_end='pending',
    ),
    Task(
        'spaces_videos_clips',
        'Rename the .mp4 clips in videos/ to use dashes instead of spaces. Leave '
        'videos/notes.txt and other/keep.txt alone.',
        {'videos/intro take.mp4': 'intro\n', 'videos/outro take.mp4': 'outro\n',
         'videos/clip one.mp4': 'one\n', 'videos/clip two.mp4': 'two\n',
         'videos/clip three.mp4': 'three\n', 'videos/notes.txt': 'notes\n',
         'other/keep.txt': 'keep\n'},
        ('tool fs.list\npath: videos', 'tool fs.rename\npath: videos\nrule: spaces_to_dashes\nglob: *.mp4',
         'done\nThe five renames are staged and pending your approval.'),
        {'videos/intro take.mp4': None, 'videos/outro take.mp4': None, 'videos/clip one.mp4': None,
         'videos/clip two.mp4': None, 'videos/clip three.mp4': None,
         'videos/intro-take.mp4': 'intro\n', 'videos/outro-take.mp4': 'outro\n',
         'videos/clip-one.mp4': 'one\n', 'videos/clip-two.mp4': 'two\n',
         'videos/clip-three.mp4': 'three\n'},
        policy_end='pending',
    ),
    # --- zero pad (7) -----------------------------------------------------------------------
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
        'zero_pad_invoices_width4',
        'Pad the invoice numbers in invoices/ to four digits.',
        {'invoices/invoice1.pdf': 'one\n', 'invoices/invoice2.pdf': 'two\n',
         'invoices/invoice15.pdf': 'fifteen\n', 'invoices/readme.txt': 'readme\n'},
        ('tool fs.list\npath: invoices', 'tool fs.rename\npath: invoices\nrule: zero_pad\nwidth: 4',
         'done\nThe three renames are staged and pending your approval.'),
        {'invoices/invoice1.pdf': None, 'invoices/invoice2.pdf': None, 'invoices/invoice15.pdf': None,
         'invoices/invoice0001.pdf': 'one\n', 'invoices/invoice0002.pdf': 'two\n',
         'invoices/invoice0015.pdf': 'fifteen\n'},
        policy_end='pending',
    ),
    Task(
        'zero_pad_photos_width3',
        'In photos2/, zero-pad the image numbers in the .jpg files to three digits. '
        'Leave photos2/log.txt alone.',
        {'photos2/img1.jpg': 'one\n', 'photos2/img2.jpg': 'two\n', 'photos2/img3.jpg': 'three\n',
         'photos2/log.txt': 'log\n'},
        ('tool fs.list\npath: photos2',
         'tool fs.rename\npath: photos2\nrule: zero_pad\nwidth: 3\nglob: *.jpg',
         'done\nThe three renames are staged and pending your approval.'),
        {'photos2/img1.jpg': None, 'photos2/img2.jpg': None, 'photos2/img3.jpg': None,
         'photos2/img001.jpg': 'one\n', 'photos2/img002.jpg': 'two\n', 'photos2/img003.jpg': 'three\n'},
        policy_end='pending',
    ),
    Task(
        'zero_pad_chapters_width2',
        'Pad the chapter numbers in chapters/ to two digits. chapter09.txt already has two '
        'digits.',
        {'chapters/chapter1.txt': 'one\n', 'chapters/chapter2.txt': 'two\n',
         'chapters/chapter09.txt': 'nine\n'},
        ('tool fs.list\npath: chapters', 'tool fs.rename\npath: chapters\nrule: zero_pad\nwidth: 2',
         'done\nThe two renames are staged and pending your approval.'),
        {'chapters/chapter1.txt': None, 'chapters/chapter2.txt': None,
         'chapters/chapter01.txt': 'one\n', 'chapters/chapter02.txt': 'two\n'},
        policy_end='pending',
    ),
    Task(
        'zero_pad_tracks_width4',
        'zero-pad the track numbers to four digits in tracks/',
        {f'tracks/track{i}.mp3': f'track {i}\n' for i in range(1, 9)},
        ('tool fs.list\npath: tracks', 'tool fs.rename\npath: tracks\nrule: zero_pad\nwidth: 4',
         'done\nThe eight renames are staged and pending your approval.'),
        {**{f'tracks/track{i}.mp3': None for i in range(1, 9)},
         **{f'tracks/track{i:04d}.mp3': f'track {i}\n' for i in range(1, 9)}},
        policy_end='pending',
    ),
    Task(
        'zero_pad_receipts2_width2',
        'Pad the numbers in receipts2/ to two digits.',
        {'receipts2/receipt1.csv': 'one\n', 'receipts2/receipt2.csv': 'two\n'},
        ('tool fs.list\npath: receipts2', 'tool fs.rename\npath: receipts2\nrule: zero_pad\nwidth: 2',
         'done\nThe two renames are staged and pending your approval.'),
        {'receipts2/receipt1.csv': None, 'receipts2/receipt2.csv': None,
         'receipts2/receipt01.csv': 'one\n', 'receipts2/receipt02.csv': 'two\n'},
        policy_end='pending',
    ),
    # --- collisions (ask) (3) ----------------------------------------------------------------
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
    Task(
        'collision_spaces_target_exists',
        'In notes/, replace the spaces in file names with dashes.',
        {'notes/file one.txt': 'a\n', 'notes/file-one.txt': 'existing\n'},
        ('tool fs.list\npath: notes',
         'tool fs.rename\npath: notes\nrule: spaces_to_dashes',
         'ask\nnotes/file-one.txt already exists; which should keep the name?'),
        {}, terminal='ask',
    ),
    # --- not a bulk rename (twins) (4) --------------------------------------------------------
    Task(
        'twin_rename_single_file',
        'Rename docs2/old_name.txt to docs2/new_name.txt.',
        {'docs2/old_name.txt': 'content\n', 'docs2/other.txt': 'keep\n'},
        ('tool fs.list\npath: docs2', 'run\nmv -- docs2/old_name.txt docs2/new_name.txt',
         'done\nRenamed.'),
        {'docs2/old_name.txt': None, 'docs2/new_name.txt': 'content\n'},
        policy_end='pending',
    ),
    Task(
        'twin_copy_with_dashes',
        'Copy the files in notes2/ into archive2/, replacing spaces with dashes in the new '
        'names.',
        {'notes2/plan a.txt': 'plan a\n', 'notes2/plan b.txt': 'plan b\n'},
        ('tool fs.list\npath: notes2',
         "run\nmkdir -p archive2 && cp -- 'notes2/plan a.txt' 'archive2/plan-a.txt' && "
         "cp -- 'notes2/plan b.txt' 'archive2/plan-b.txt'",
         'done\nCopied.'),
        {'archive2': '<dir added>', 'archive2/plan-a.txt': 'plan a\n',
         'archive2/plan-b.txt': 'plan b\n'},
        policy_end='ok',
    ),
    Task(
        'twin_lowercase_names',
        'Lowercase all the file names in uploads/.',
        {'uploads/IMG_One.png': 'one\n', 'uploads/IMG_Two.png': 'two\n'},
        ('tool fs.list\npath: uploads',
         "run\nmv -- uploads/IMG_One.png uploads/img_one.png && "
         "mv -- uploads/IMG_Two.png uploads/img_two.png",
         'done\nThe two renames are staged and pending your approval.'),
        {'uploads/IMG_One.png': None, 'uploads/IMG_Two.png': None,
         'uploads/img_one.png': 'one\n', 'uploads/img_two.png': 'two\n'},
        policy_end='pending',
    ),
    Task(
        'twin_strip_prefix',
        "Remove the 'draft-' prefix from the file names in drafts/.",
        {'drafts/draft-report.txt': 'report\n', 'drafts/draft-notes.txt': 'notes\n',
         'drafts/final.txt': 'final\n'},
        ('tool fs.list\npath: drafts',
         "run\nmv -- drafts/draft-report.txt drafts/report.txt && "
         "mv -- drafts/draft-notes.txt drafts/notes.txt",
         'done\nThe two renames are staged and pending your approval.'),
        {'drafts/draft-report.txt': None, 'drafts/draft-notes.txt': None,
         'drafts/report.txt': 'report\n', 'drafts/notes.txt': 'notes\n'},
        policy_end='pending',
    ),
)

# The v6 replacement for each task: list, then `mv`/`cp` (no fs.rename at v6). For the three
# collisions the correct v6 behaviour is also to ask without touching anything: a blind `mv`
# would silently overwrite one source, which the oracle must never do. Twins (fs.rename is not
# the right tool on *either* version) get the identical oracle on both versions.
ORACLES_V6 = {
    'rename_scan_spaces': (
        'tool fs.list\npath: scans',
        "run\nmv -- 'scans/scan 1.png' 'scans/scan-1.png' && mv -- 'scans/scan 2.png' "
        "'scans/scan-2.png' && mv -- 'scans/scan 10.png' 'scans/scan-10.png'",
        'done\nThe three renames are staged and pending your approval.',
    ),
    'spaces_photo_set': (
        'tool fs.list\npath: photos',
        "run\nmv -- 'photos/photo one.jpg' 'photos/photo-one.jpg' && "
        "mv -- 'photos/photo two.jpg' 'photos/photo-two.jpg' && "
        "mv -- 'photos/photo three.jpg' 'photos/photo-three.jpg' && "
        "mv -- 'photos/photo four.jpg' 'photos/photo-four.jpg'",
        'done\nThe four renames are staged and pending your approval.',
    ),
    'spaces_music_tracks': (
        'tool fs.list\npath: music',
        "run\nmv -- 'music/track one.wav' 'music/track-one.wav' && "
        "mv -- 'music/track two.wav' 'music/track-two.wav'",
        'done\nThe two renames are staged and pending your approval.',
    ),
    'spaces_docs_already_dashed': (
        'tool fs.list\npath: docs',
        "run\nmv -- 'docs/file one.md' 'docs/file-one.md' && "
        "mv -- 'docs/another one.md' 'docs/another-one.md'",
        'done\nThe two renames are staged and pending your approval.',
    ),
    'spaces_receipts_no_glob': (
        'tool fs.list\npath: receipts',
        "run\nmv -- 'receipts/receipt jan.pdf' 'receipts/receipt-jan.pdf' && "
        "mv -- 'receipts/receipt feb.pdf' 'receipts/receipt-feb.pdf' && "
        "mv -- 'receipts/receipt mar.pdf' 'receipts/receipt-mar.pdf'",
        'done\nThe three renames are staged and pending your approval.',
    ),
    'spaces_videos_clips': (
        'tool fs.list\npath: videos',
        "run\nmv -- 'videos/intro take.mp4' 'videos/intro-take.mp4' && "
        "mv -- 'videos/outro take.mp4' 'videos/outro-take.mp4' && "
        "mv -- 'videos/clip one.mp4' 'videos/clip-one.mp4' && "
        "mv -- 'videos/clip two.mp4' 'videos/clip-two.mp4' && "
        "mv -- 'videos/clip three.mp4' 'videos/clip-three.mp4'",
        'done\nThe five renames are staged and pending your approval.',
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
    'zero_pad_invoices_width4': (
        'tool fs.list\npath: invoices',
        'run\nmv -- invoices/invoice1.pdf invoices/invoice0001.pdf && '
        'mv -- invoices/invoice2.pdf invoices/invoice0002.pdf && '
        'mv -- invoices/invoice15.pdf invoices/invoice0015.pdf',
        'done\nThe three renames are staged and pending your approval.',
    ),
    'zero_pad_photos_width3': (
        'tool fs.list\npath: photos2',
        'run\nmv -- photos2/img1.jpg photos2/img001.jpg && '
        'mv -- photos2/img2.jpg photos2/img002.jpg && '
        'mv -- photos2/img3.jpg photos2/img003.jpg',
        'done\nThe three renames are staged and pending your approval.',
    ),
    'zero_pad_chapters_width2': (
        'tool fs.list\npath: chapters',
        'run\nmv -- chapters/chapter1.txt chapters/chapter01.txt && '
        'mv -- chapters/chapter2.txt chapters/chapter02.txt',
        'done\nThe two renames are staged and pending your approval.',
    ),
    'zero_pad_tracks_width4': (
        'tool fs.list\npath: tracks',
        'run\n' + ' && '.join(f'mv -- tracks/track{i}.mp3 tracks/track{i:04d}.mp3' for i in range(1, 9)),
        'done\nThe eight renames are staged and pending your approval.',
    ),
    'zero_pad_receipts2_width2': (
        'tool fs.list\npath: receipts2',
        'run\nmv -- receipts2/receipt1.csv receipts2/receipt01.csv && '
        'mv -- receipts2/receipt2.csv receipts2/receipt02.csv',
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
    'collision_spaces_target_exists': (
        'tool fs.list\npath: notes',
        'ask\nnotes/file-one.txt already exists; which should keep the name?',
    ),
    'twin_rename_single_file': (
        'tool fs.list\npath: docs2', 'run\nmv -- docs2/old_name.txt docs2/new_name.txt',
        'done\nRenamed.',
    ),
    'twin_copy_with_dashes': (
        'tool fs.list\npath: notes2',
        "run\nmkdir -p archive2 && cp -- 'notes2/plan a.txt' 'archive2/plan-a.txt' && "
        "cp -- 'notes2/plan b.txt' 'archive2/plan-b.txt'",
        'done\nCopied.',
    ),
    'twin_lowercase_names': (
        'tool fs.list\npath: uploads',
        "run\nmv -- uploads/IMG_One.png uploads/img_one.png && "
        "mv -- uploads/IMG_Two.png uploads/img_two.png",
        'done\nThe two renames are staged and pending your approval.',
    ),
    'twin_strip_prefix': (
        'tool fs.list\npath: drafts',
        "run\nmv -- drafts/draft-report.txt drafts/report.txt && "
        "mv -- drafts/draft-notes.txt drafts/notes.txt",
        'done\nThe two renames are staged and pending your approval.',
    ),
}
ASK = frozenset(task.id for task in TASKS if task.terminal == 'ask')
TWINS = frozenset({'twin_rename_single_file', 'twin_copy_with_dashes', 'twin_lowercase_names',
                    'twin_strip_prefix'})
GROUPS = {
    'spaces to dashes': TASKS[:6],
    'zero pad': TASKS[6:13],
    'collisions (ask)': TASKS[13:16],
    'not a bulk rename (twins)': TASKS[16:],
}

ORACLES = {}  # the module default Task.oracle is already the v8 oracle; nothing to override


def oracles(version):
    """Version-aware oracle selection for dev.focus_runner: v6 replacements below v8, the
    module default (v8-shaped, or identical-on-both-versions for twins) at and above it."""
    return ORACLES_V6 if version < 8 else {}


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    """Shared grader for the ask-terminal collision tasks, the pending-rename tasks, and the
    twins (whose correct final policy may be 'ok' -- e.g. a copy that only adds files -- rather
    than 'pending'; `task.policy_end` already carries whichever is correct, so no twin-specific
    branch is needed here).

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
            failures.append(f'no authoritative {task.policy_end!r} stop on the final tool turn')
    return failures
