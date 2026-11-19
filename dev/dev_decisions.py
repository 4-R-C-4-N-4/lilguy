"""Development-only fixtures for choosing whether to inspect, ask, or produce an artifact."""
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
    terminal: str = 'done'
    contradicts: str | None = None


TASKS = (
    Task(
        'choose_language_edition',
        'Make a handout by copying the announcement to print-copy.txt. I did not specify an edition.',
        {'annonce.fr.txt': 'Bonjour à la réunion.\n', 'notice.en.txt': 'Welcome to the meeting.\n'},
        ('tool fs.list\npath: .', 'ask\nShould the handout use the English or French edition?'),
        facts=(r'\b(?:English|notice\.en\.txt)\b', r'\b(?:French|annonce\.fr\.txt)\b'), terminal='ask',
    ),
    Task(
        'clarify_missing_recording_order',
        'Combine lecture-a.txt and lecture-b.txt into recording-order.txt in the order we agreed on. Do not guess the order.',
        {'lecture-a.txt': 'Audio transcript: shoreline talk.\n', 'lecture-b.txt': 'Audio transcript: woodland talk.\n'},
        ('tool fs.list\npath: .', 'ask\nWhich recording should come first, lecture-a.txt or lecture-b.txt?'),
        facts=(r'\border\b|\bfirst\b|\bstart\b',), terminal='ask',
    ),
    Task(
        'resolve_conflicting_separator_guides',
        'Export item-codes.txt as one line in export.txt using the separator specified by the project guides.',
        {'print-guide.txt': 'Use a semicolon between codes.\n',
         'upload-guide.txt': 'Use a vertical bar between codes.\n', 'item-codes.txt': 'K7\nJ4\n'},
        ('tool fs.read\npath: print-guide.txt', 'tool fs.read\npath: upload-guide.txt',
         'ask\nThe print and upload guides disagree. Should I use a semicolon or a vertical bar?'),
        facts=(r'semicolon|;', r'vertical bar|pipe|\|'), terminal='ask',
    ),
    Task(
        'csv_quoted_location_values',
        'Write only the location column of events.csv, one value per line without a header, to locations.txt. Preserve commas in names.',
        {'events.csv': 'event,location,day\nshow,"Hall A, Annex",Mon\nworkshop,Studio,Wed\n'},
        ('tool fs.read\npath: events.csv',
         "run\npython3 -c 'import csv; print(*[r[\"location\"] for r in csv.DictReader(open(\"events.csv\"))], sep=\"\\n\")' > locations.txt",
         'tool fs.read\npath: locations.txt', 'done\nWrote locations.txt.'),
        {'locations.txt': 'Hall A, Annex\nStudio\n'},
    ),
    Task(
        'project_priority_status_json',
        'Create public-tasks.json as a JSON array of just the names of tasks whose visibility is public, in input order. Use compact JSON with no spaces between elements, followed by a newline.',
        {'board.json': '[{"name":"plan","visibility":"public"},{"name":"draft","visibility":"private"},{"name":"ship","visibility":"public"}]\n'},
        ('tool fs.read\npath: board.json',
         "run\npython3 -c 'import json; print(json.dumps([r[\"name\"] for r in json.load(open(\"board.json\")) if r[\"visibility\"] == \"public\"], separators=(\",\", \":\")))' > public-tasks.json",
         'tool fs.read\npath: public-tasks.json', 'done\nWrote public-tasks.json.'),
        {'public-tasks.json': '["plan","ship"]\n'},
    ),
    Task(
        'windows_line_endings_copy',
        'Make a copy of supplier-address.txt named unix-address.txt, converting CRLF line endings to LF and changing nothing else.',
        {'supplier-address.txt': '7 Wren Lane\r\nAttn: Returns\r\n\r\n'},
        ("run\npython3 -c 'from pathlib import Path; import sys; sys.stdout.buffer.write(Path(\"supplier-address.txt\").read_bytes().replace(b\"\\r\\n\", b\"\\n\"))' > unix-address.txt",
         'tool fs.read\npath: unix-address.txt', 'done\nWrote unix-address.txt with LF line endings.'),
        {'unix-address.txt': '7 Wren Lane\nAttn: Returns\n\n'},
    ),
    Task(
        'sum_inventory_per_bin',
        'Make bin-totals.txt with one row per bin in stock.tsv, alphabetically by bin, showing the bin and summed quantity separated by a tab. The input has no header.',
        {'stock.tsv': 'willow\t4\ncedar\t12\nwillow\t6\nbirch\t8\ncedar\t1\n'},
        ("run\nawk '{totals[$1] += $2} END {for (bin in totals) printf \"%s\\t%d\\n\", bin, totals[bin]}' stock.tsv | LC_ALL=C sort > bin-totals.txt",
         'tool fs.read\npath: bin-totals.txt', 'done\nWrote the bin totals to bin-totals.txt.'),
        {'bin-totals.txt': 'birch\t8\ncedar\t13\nwillow\t10\n'},
    ),
    Task(
        'pair_audio_ids_to_titles',
        'Join audio-durations.txt and audio-titles.txt by recording ID, ignoring IDs absent from either file. Write ID, duration, and title separated by single spaces, sorted by ID, to audio-index.txt.',
        {'audio-durations.txt': 'a23 2m\na12 3m\na54 8m\n', 'audio-titles.txt': 'a12 Marsh\na67 Quarry\na54 Ridge\n'},
        ("run\nLC_ALL=C join <(LC_ALL=C sort audio-durations.txt) <(LC_ALL=C sort audio-titles.txt) > audio-index.txt",
         'tool fs.read\npath: audio-index.txt', 'done\nWrote audio-index.txt.'),
        {'audio-index.txt': 'a12 3m Marsh\na54 8m Ridge\n'},
    ),
    Task(
        'files_with_dash_prefix',
        'Copy the contents of the file literally named -schedule into schedule-copy.txt.',
        {'-schedule': 'Bridge opens at noon.\n', 'schedule': 'Old plan: evening.\n'},
        ('run\ncat -- -schedule > schedule-copy.txt', 'tool fs.read\npath: schedule-copy.txt',
         'done\nWrote schedule-copy.txt from -schedule.'),
        {'schedule-copy.txt': 'Bridge opens at noon.\n'},
    ),
    Task(
        'matching_normalized_addresses',
        'Do postcard-a.txt and postcard-b.txt contain the same lines once trailing whitespace is ignored? Do not modify either.',
        {'postcard-a.txt': '42 Meadow Lane  \nGarden Side\t\n', 'postcard-b.txt': '42 Meadow Lane\nGarden Side\n'},
        ("run\ndiff <(sed 's/[[:space:]]*$//' postcard-a.txt) <(sed 's/[[:space:]]*$//' postcard-b.txt)",
         'done\nYes, their lines match after ignoring trailing whitespace.'),
        facts=(r'\b(?:yes|same|match|identical|equal)\b',),
        contradicts=r'^\s*no\b|\b(?:not|never)\b[^.!?\n]{0,32}\b(?:same|match|identical|equal)\b|\b(?:differ|different|unequal)\b',
    ),
    Task(
        'latest_iso_timestamp',
        'Which station recorded the latest timestamp in arrivals.tsv? The first column contains UTC timestamps; report station and time without editing.',
        {'arrivals.tsv': '2026-08-17T10:24Z\tsparrow\n2026-08-17T09:55Z\theron\n2026-08-17T10:20Z\tfinch\n'},
        ('run\nLC_ALL=C sort arrivals.tsv | tail -n 1', 'done\nSparrow recorded the latest at 10:24 UTC.'),
        facts=(r'\bsparrow\b', r'(?<!\d)10:24(?!\d)'),
    ),
    Task(
        'no_marker_in_schedule',
        'Does rota.txt contain a row whose first field is CANCELLED? Do not change the file.',
        {'rota.txt': 'ACTIVE first shift\nMOVED second shift\nACTIVE third shift\n'},
        ('tool fs.read\npath: rota.txt', 'done\nNo, none of the rows starts with CANCELLED.'),
        facts=(r'^\s*no\b|\b(?:no|none|zero|not|doesn[’\x27]t)\b[^.!?\n]{0,64}\bCANCELLED\b',),
        contradicts=r'^\s*yes\b',
    ),
)


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    failures = []
    if not original_unchanged:
        failures.append('original workspace changed')
    if terminal != task.terminal:
        failures.append(f'expected {task.terminal}')
    if changes != task.changes:
        failures.append('staged effects differ from expected output')
    if any(not re.search(pattern, answer or '', re.IGNORECASE) for pattern in task.facts):
        failures.append('answer omits an expected fact or choice')
    if task.contradicts and re.search(task.contradicts, answer or '', re.IGNORECASE):
        failures.append('answer contradicts the requested result')
    if not events or events[-1][2] or not events[-1][1].startswith('exit=0\n'):
        failures.append('no successful last tool step')
    if any(policy_of(obs) != 'ok' for _, obs, _ in events):
        failures.append('unexpected policy stop')
    return failures
