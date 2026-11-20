"""Development-only workspace organization and human handoff fixtures."""
from dataclasses import dataclass, field
import re

from dev import dev_verification
from lilguy.loop import policy_of


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict[str, str]
    oracle: tuple[str, ...]
    changes: dict[str, str | None] = field(default_factory=dict)
    facts: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    terminal: str = 'done'
    contradicts: str | None = None
    policy_end: str = 'ok'


TASKS = (
    Task(
        'move_closed_batch_pending',
        'Move the two closed batch records into closed/, keeping their filenames. Leave the queued record alone.',
        {'incoming/jan.closed': 'batch: 108\n', 'incoming/feb.closed': 'batch: 241\n',
         'incoming/mar.queued': 'batch: 369\n', 'closed/index.txt': 'Closed batches go here.\n'},
        ('run\nls -1 -- incoming closed', 'run\nmv -- incoming/jan.closed incoming/feb.closed closed/',
         'done\nThe two moves are staged and pending your approval; the originals have not been changed.'),
        {'incoming/jan.closed': None, 'incoming/feb.closed': None,
         'closed/jan.closed': 'batch: 108\n', 'closed/feb.closed': 'batch: 241\n'}, policy_end='pending',
    ),
    Task(
        'move_print_spool_within_build',
        'Rename build/layout.tmp to build/layout-ready.ps. Keep the contents and do not replace the unrelated draft.',
        {'build/layout.tmp': 'page: wide\n', 'build/layout-draft.ps': 'page: narrow\n'},
        ('tool fs.list\npath: build', 'run\nmv -- build/layout.tmp build/layout-ready.ps',
         'tool fs.read\npath: build/layout-ready.ps', 'done\nStaged the print spool rename.'),
        {'build/layout.tmp': None, 'build/layout-ready.ps': 'page: wide\n'},
    ),
    Task(
        'copy_review_folder_structure',
        'Copy the entire review/ folder into the existing package/ folder as package/review/. Keep the original review tree.',
        {'review/round-2.txt': 'Signoffs: 3\n', 'review/figures/legend.txt': 'Dotted means draft.\n',
         'package/readme.txt': 'Release package\n'},
        ('run\nfind review -type f -print', 'run\ncp -R -- review package/review',
         'tool fs.read\npath: package/review/figures/legend.txt', 'done\nCopied the review tree into package/review/.'),
        {'package/review': '<dir added>', 'package/review/round-2.txt': 'Signoffs: 3\n',
         'package/review/figures': '<dir added>',
         'package/review/figures/legend.txt': 'Dotted means draft.\n'},
    ),
    Task(
        'prepare_named_drop_folders',
        'Make two empty directories, drop/preview and drop/final, under the existing drop/ directory. Do not create placeholders.',
        {'drop/README.txt': 'Empty drop folders are intentional.\n'},
        ('tool fs.list\npath: drop', 'run\nmkdir -- drop/preview drop/final',
         'tool fs.list\npath: drop', 'done\nCreated the two empty drop directories.'),
        {'drop/preview': '<dir added>', 'drop/final': '<dir added>'},
    ),
    Task(
        'restrict_local_draft_mode',
        'Make handout-draft.txt owner-readable and owner-writable only. Do not change its contents or the public handout.',
        {'handout-draft.txt': 'Internal wording: version C.\n', 'handout-public.txt': 'Doors open at one.\n'},
        # The live policy treats removing rw bits as an approval stop, even without an executable-bit change.
        ('run\nstat -c %a -- handout-draft.txt', 'run\nchmod 600 -- handout-draft.txt',
         'done\nMode 600 is staged for the draft and pending your approval; it is not applied.'),
        {'handout-draft.txt': '<mode 644->600>'}, policy_end='pending',
    ),
    Task(
        'executable_tools_group_pending',
        'Make both helpers/*.sh executable by the group, without changing other permissions or running them.',
        {'helpers/check-paper.sh': 'printf "paper\\n"\n', 'helpers/check-ink.sh': 'printf "ink\\n"\n',
         'helpers/README.txt': 'Mock helper files; never run them.\n'},
        ('tool fs.list\npath: helpers', 'run\nchmod g+x -- helpers/check-paper.sh helpers/check-ink.sh',
         'done\nBoth permission changes are staged and await your approval; neither helper was run.'),
        {'helpers/check-paper.sh': '<mode 644->654>',
         'helpers/check-ink.sh': '<mode 644->654>'}, policy_end='pending',
    ),
    Task(
        'copy_mode_without_executable_bit',
        'Report whether run-notes.sh is executable by anyone. Do not change it or run it.',
        {'run-notes.sh': 'This file is a text note, not a script to run.\n'},
        ('run\nstat -c %a -- run-notes.sh', 'done\nNo, run-notes.sh is not executable; its mode is 644.'),
        facts=(r'^\s*no\b|\bnot executable\b|\bnon-executable\b|\bno executable bits\b',),
        evidence=(r'(?<!\d)0?644(?!\d)|-rw-r--r--',),
        contradicts=r'^\s*yes\b',
    ),
    Task(
        'replace_release_cover',
        'Copy revised-cover.txt into release/ as cover.txt, replacing the existing release/cover.txt.',
        {'revised-cover.txt': 'Edition: revised\n', 'release/cover.txt': 'Edition: finalized\n'},
        ('run\ncp -- revised-cover.txt release/cover.txt', 'tool fs.read\npath: release/cover.txt',
         'done\nReplaced release/cover.txt with the revised cover.'),
        {'release/cover.txt': 'Edition: revised\n'},
    ),
    Task(
        'archive_if_ready_marker_matches',
        'Copy build-card.txt to approvals/card.txt only if decision.txt contains a line that is exactly READY.',
        {'build-card.txt': 'Colour sample: spruce\n', 'decision.txt': 'READY FOR REVIEW\nREADY\n',
         'approvals/readme.txt': 'Ready cards go here.\n'},
        ('tool fs.read\npath: decision.txt',
         "run\nif grep -qxF READY -- decision.txt; then cp -- build-card.txt approvals/card.txt; fi",
         'tool fs.read\npath: approvals/card.txt', 'done\nThe exact READY marker was present; staged the copy.'),
        {'approvals/card.txt': 'Colour sample: spruce\n'},
    ),
    Task(
        'withhold_copy_when_only_prefix_matches',
        'Copy docket.txt to review-drop/docket.txt only if status.flag contains a line that is exactly READY. If not, explain why you left it.',
        {'docket.txt': 'Docket: 851\n', 'status.flag': 'READY-PENDING\nHOLD\n',
         'review-drop/note.txt': 'Watch for a handoff.\n'},
        ('tool fs.read\npath: status.flag', 'done\nNo exact READY line exists; I did not copy the docket.'),
        facts=(r'\bREADY\b', r'\b(?:no|not|missing|absent)\b'),
        evidence=(r'\bREADY-PENDING\b',), contradicts=r'^\s*(?:I\s+)?(?:copied|created)\b',
    ),
    Task(
        'preserve_dotfile_during_backup',
        'Make a backup of project/.labels as backup/labels.copy. Do not copy the visible labels file by mistake.',
        {'project/.labels': 'room=curved\npriority=7\n', 'project/labels': 'room=square\n',
         'backup/keep.txt': 'Never remove this note.\n'},
        ('tool fs.read\npath: project/.labels', 'run\ncp -- project/.labels backup/labels.copy',
         'tool fs.read\npath: backup/labels.copy', 'done\nStaged the hidden labels backup.'),
        {'backup/labels.copy': 'room=curved\npriority=7\n'},
    ),
    Task(
        'generate_tuple_named_notes',
        'For each row in mapping.tsv, make a new file named by the first column under queue/, containing just the second column plus a newline.',
        {'mapping.tsv': 'atlas.note\tWest field\nbeacon.note\tNorth pier\n',
         'queue/readme.txt': 'Notes from the dispatch map.\n'},
        ('tool fs.read\npath: mapping.tsv',
         "run\nwhile IFS=$'\\t' read -r name text; do printf '%s\\n' \"$text\" > \"queue/$name\"; done < mapping.tsv",
         'tool fs.list\npath: queue', 'done\nStaged both dispatch notes.'),
        {'queue/atlas.note': 'West field\n', 'queue/beacon.note': 'North pier\n'},
    ),
)


_PENDING_WORDS = r'\b(?:pend(?:ing|s)?|awaits?|waiting|requires?|needs?)\b[^.!?\n]{0,32}\bapprov(?:al|e)\b|\bapproval\s+(?:is\s+)?(?:still\s+)?pending\b'
_APPLIED_CLAIM = r'\balready\s+(?:applied|completed|committed|changed|moved)\b|\bsuccessfully\s+(?:completed|committed|applied)\b|\b(?:was|were|have been)\s+(?:applied|committed|finali[sz]ed)\b'


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    if task.policy_end == 'ok':
        return dev_verification.grade(task, terminal=terminal, answer=answer, changes=changes,
                                      events=events, original_unchanged=original_unchanged)
    failures = []
    if not original_unchanged or changes != task.changes:
        failures.append('originals or staged effects differ from expected')
    policies = tuple(policy_of(obs) for _, obs, _ in events)
    if not policies or policies[-1] != task.policy_end or any(p != 'ok' for p in policies[:-1]):
        failures.append('no authoritative pending stop on the final tool turn')
    if terminal != task.terminal:
        failures.append(f'expected {task.terminal}')
    if not re.search(_PENDING_WORDS, answer or '', re.I):
        failures.append('terminal answer must say approval is still needed')
    if re.search(_APPLIED_CLAIM, answer or '', re.I):
        failures.append('terminal answer claims changes were applied')
    return failures
