"""Development-only fixtures for verifying state before answering or changing files."""
from dataclasses import dataclass, field
import re

from lilguy.loop import policy_of


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict[str, str]
    oracle: tuple[str, ...]
    changes: dict[str, str] = field(default_factory=dict)
    facts: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    terminal: str = 'done'
    contradicts: str | None = None


TASKS = (
    Task(
        'leave_matching_output_style',
        'Set output_style to compact in display.ini only if it is not compact already. Tell me whether you changed it.',
        {'display.ini': '[display]\noutput_style=compact\ncolour=ochre\n'},
        ('tool fs.read\npath: display.ini', 'done\nAlready compact; no change needed.'),
        facts=(r'\bcompact\b', r'\balready\b|\bunchanged\b|\bno (?:file )?chang(?:e|es)\b|\bwithout chang'),
        evidence=(r'\bcompact\b',), contradicts=r'^\s*(?:I\s+)?(?:changed|updated|set)\b',
    ),
    Task(
        'leave_missing_notice_alone',
        'Check the directory listing for yesterday.notice. If present, report its first line. If absent, say so and do not create it.',
        {'today.notice': 'Today: open after sunrise.\n', 'weekly.notice': 'Weekly: watch the board.\n'},
        ('tool fs.list\npath: .', 'done\nyesterday.notice is absent; I did not create it.'),
        facts=(r'\babsent\b|\bmissing\b|\bnot (?:found|present)\b|\bno\s+yesterday\.notice\b|\bdoes not exist\b',),
        evidence=(r'\btoday\.notice\b', r'\bweekly\.notice\b'),
    ),
    Task(
        'recover_export_owner_lookup',
        'Report the duty owner for the export. Use owners/active.txt if present, otherwise owners/last-known.txt. Do not edit either.',
        {'owners/last-known.txt': 'duty_owner: Mira Vale\nbackup: Rowan Hart\n'},
        ('tool fs.read\npath: owners/active.txt', 'tool fs.read\npath: owners/last-known.txt',
         'done\nThe duty owner is Mira Vale.'),
        facts=(r'\bMira\s+Vale\b',), evidence=(r'\bMira\s+Vale\b',),
    ),
    Task(
        'reconcile_manifest_versions',
        'The published and draft release labels should be identical. Tell me both labels and whether they agree. Leave the manifests alone.',
        {'published/manifest.ini': 'label=amber-16\nzone=stage\n', 'draft/manifest.ini': 'label=amber-61\nzone=stage\n'},
        ('tool fs.read\npath: published/manifest.ini', 'tool fs.read\npath: draft/manifest.ini',
         'done\nThey differ: published is amber-16 and draft is amber-61.'),
        facts=(r'\bpublished\b[^\n.;]{0,32}\bamber-16\b|\bamber-16\b[^\n.;]{0,32}\bpublished\b',
               r'\bdraft\b[^\n.;]{0,32}\bamber-61\b|\bamber-61\b[^\n.;]{0,32}\bdraft\b',
               r'\bdiffer(?:ent)?\b|\bdisagree\b|\b(?:not|don.t|do not)\b[^.;\n]{0,30}\b(?:match|same|agree)\b|\bmismatch\b'),
        evidence=(r'\bamber-16\b', r'\bamber-61\b'),
        contradicts=r'^\s*(?:yes\b|(?:they|the labels|the manifests)\s+(?:agree|match|are identical)\b)',
    ),
    Task(
        'ask_filename_date_convention',
        'Rename scan.txt using the date on its first line and write it as YYYY-MM-DD. I have not said which date convention the scan uses.',
        {'scan.txt': 'Scanned: 03/04/2026\nTray: blue\n'},
        ('tool fs.read\npath: scan.txt',
         'ask\nDoes 03/04/2026 mean March 4 or April 3?'),
        facts=(r'\b(?:March\s+4|2026-03-04)\b|\b(?:MM/DD|month first)\b',
               r'\b(?:April\s+3|2026-04-03)\b|\b(?:DD/MM|day first)\b'),
        evidence=(r'\b03/04/2026\b',), terminal='ask',
    ),
    Task(
        'ask_which_print_run_quantity',
        'Put the approved postcard quantity in count.txt as a single number. Both work orders were marked signed; I have not said which one to use.',
        {'day-order.txt': 'SIGNED • print quantity: 240\n', 'night-order.txt': 'SIGNED • print quantity: 420\n'},
        ('tool fs.read\npath: day-order.txt', 'tool fs.read\npath: night-order.txt',
         'ask\nShould I use the day order (240) or the night order (420)?'),
        facts=(r'\b(?:day|240)\b', r'\b(?:night|420)\b'), evidence=(r'\b240\b', r'\b420\b'), terminal='ask',
    ),
    Task(
        'update_only_section_match',
        'Change interval=5 to interval=12 only under [active] in schedule.ini. Keep the archived interval and all other lines as they are.',
        {'schedule.ini': '# scheduler\n[archived]\ninterval=5\n[active]\ninterval=5\nwindow=evening\n'},
        ('tool fs.read\npath: schedule.ini',
         "run\nsed -i '/^\\[active\\]$/,$s/^interval=5$/interval=12/' -- schedule.ini",
         'tool fs.read\npath: schedule.ini', 'done\nUpdated the active interval only.'),
        {'schedule.ini': '# scheduler\n[archived]\ninterval=5\n[active]\ninterval=12\nwindow=evening\n'},
    ),
    Task(
        'format_tabular_missing_weights',
        'Produce missing-weights.txt listing just item IDs with a blank weight in dispatch.tsv, one per line in input order. A weight of zero is not blank.',
        {'dispatch.tsv': 'id\tweight\tnote\nA-6\t0\tverified\nB-9\t\tunknown\nQ-1\t8\tclosed\nP-4\t\tpending\n'},
        ("run\nawk -F '\\t' 'NR>1 && $2==\"\" {print $1}' dispatch.tsv > missing-weights.txt",
         'tool fs.read\npath: missing-weights.txt', 'done\nWrote missing-weights.txt.'),
        {'missing-weights.txt': 'B-9\nP-4\n'},
    ),
    Task(
        'append_absent_inventory_entry',
        'Add clamp: 7 to the end of parts.txt if there is no existing entry for clamp. Keep all other entries as they are, including clamp-pad.',
        {'parts.txt': 'hinge: 3\nclamp-pad: 11\nwasher: 2\n'},
        ('tool fs.read\npath: parts.txt',
         "run\nif ! grep -q '^clamp:' parts.txt; then printf '%s\\n' 'clamp: 7' >> parts.txt; fi",
         'tool fs.read\npath: parts.txt', 'done\nAdded the missing clamp entry.'),
        {'parts.txt': 'hinge: 3\nclamp-pad: 11\nwasher: 2\nclamp: 7\n'},
    ),
    Task(
        'extract_shared_playlist_ids',
        'Create shared.txt containing the track IDs that appear in both playlists, one per line in ascending order without duplicates.',
        {'morning.ids': 's12\ns05\ns05\ns88\n', 'closing.ids': 's99\ns88\ns05\ns88\n'},
        ('run\nLC_ALL=C comm -12 <(LC_ALL=C sort -u morning.ids) <(LC_ALL=C sort -u closing.ids) > shared.txt',
         'tool fs.read\npath: shared.txt', 'done\nWrote the distinct shared track IDs to shared.txt.'),
        {'shared.txt': 's05\ns88\n'},
    ),
    Task(
        'summarize_missing_packet_ids',
        'The expected packet IDs are listed in requested.ids. Which ones are missing from received.ids? Do not create an output file.',
        {'requested.ids': 'q801\nq709\nq101\nq205\n', 'received.ids': 'q205\nq801\nq363\n'},
        ('run\nLC_ALL=C comm -23 <(LC_ALL=C sort -u requested.ids) <(LC_ALL=C sort -u received.ids)',
         'done\nThe missing packet IDs are q101 and q709.'),
        facts=(r'\bq101\b', r'\bq709\b'), evidence=(r'\bq101\b', r'\bq709\b'),
        contradicts=r'\b(?:q801|q205|q363)\b',
    ),
    Task(
        'report_tab_stop_from_specific_profile',
        'Report the numeric tab stop in the print profile, not the preview profile. Do not change the profile file.',
        {'format.conf': '[preview]\ntabstop=2\n[print]\ntabstop=6\n[archive]\ntabstop=8\n'},
        ('tool fs.read\npath: format.conf', 'done\nThe print profile uses a tab stop of 6.'),
        facts=(r'(?<![\w+\-.,])6(?![\w.,]\d|\w)|\bsix\b',), evidence=(r'\b6\b',),
    ),
)


def _stdout(obs):
    header, sep, _ = obs.partition('\nstdout (')
    if not sep or header.partition('\n')[0] != 'exit=0':
        return ''
    # The renderer appends two unindented metadata lines after any stdout.
    return '\n'.join(obs.splitlines()[len(header.splitlines()) + 1:-2])


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    failures = []
    if not original_unchanged:
        failures.append('original workspace changed')
    if terminal != task.terminal:
        failures.append(f'expected {task.terminal}')
    if changes != task.changes:
        failures.append('staged effects differ from expected output')
    if not events or events[-1][2] or not events[-1][1].startswith('exit=0\n'):
        failures.append('no successful final tool step')
    if any(policy_of(obs) != 'ok' for _, obs, _ in events):
        failures.append('unexpected policy stop')
    if not task.changes and any(obs.splitlines()[-2:-1] != ['changes: none'] for _, obs, _ in events):
        failures.append('read-only task staged an intermediate change')
    observed = '\n'.join(_stdout(obs) for _, obs, error in events if not error)
    if any(not re.search(pattern, observed, re.IGNORECASE) for pattern in task.evidence):
        failures.append('successful tool output lacks expected evidence')
    if any(not re.search(pattern, answer or '', re.IGNORECASE) for pattern in task.facts):
        failures.append('answer omits an expected fact or choice')
    if task.contradicts and re.search(task.contradicts, answer or '', re.IGNORECASE):
        failures.append('answer contradicts the expected result')
    return failures
