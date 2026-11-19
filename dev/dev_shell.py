"""Hand-authored development-only shell fixtures. Do not use these as training examples."""
from dataclasses import dataclass
import re

from lilguy.loop import policy_of


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict[str, str]
    oracle: tuple[str, ...]
    changes: dict[str, str]
    answer_pattern: str | None = None


TASKS = (
    Task(
        'quoted_label_index',
        'Make label-index.txt from the distinct lines of "field labels.txt", one label per line, sorted alphabetically.',
        {'field labels.txt': 'fern\nacorn\nfern\n', 'field.txt': 'ignore this\n'},
        ('tool fs.read\npath: field labels.txt',
         "run\nLC_ALL=C sort -u -- 'field labels.txt' > label-index.txt",
         'tool fs.read\npath: label-index.txt', 'done\nWrote label-index.txt.'),
        {'label-index.txt': 'acorn\nfern\n'},
    ),
    Task(
        'utf8_line_count',
        'How many non-empty lines are in journal.txt? Treat a blank line as not a line for this count.',
        {'journal.txt': 'été\n\nmañana\n冬\n'},
        ('run\ngrep -c . -- journal.txt', 'done\nThe file has 3 non-empty lines.'),
        {}, r'\b(?:3|three)\b'),
    Task(
        'hidden_theme_lookup',
        'The theme name is in a hidden file under profile/. Find it and tell me its value without changing files.',
        {'profile/.appearance': 'theme: juniper\n', 'profile/notes.txt': 'Archived theme: violet\n'},
        ('run\nls -A -- profile', 'tool fs.read\npath: profile/.appearance', 'done\nThe theme is juniper.'),
        {}, r'\bjuniper\b'),
    Task(
        'middle_excerpt',
        'Save lines 3 through 5 of transcript.txt, inclusive, in excerpt.txt in their original order.',
        {'transcript.txt': 'welcome\nroll call\nopening\nquestions\nresponse\nfarewell\n'},
        ('run\nsed -n \'3,5p\' -- transcript.txt > excerpt.txt', 'tool fs.read\npath: excerpt.txt',
         'done\nSaved the requested lines in excerpt.txt.'),
        {'excerpt.txt': 'opening\nquestions\nresponse\n'},
    ),
    Task(
        'guide_selected_input',
        'Generate ticket-list.txt containing the ticket names, one per line. Use the input file specified by the handoff guide and preserve its order.',
        {'HANDOFF.txt': 'The source of record is current.tsv. scratch.tsv is a draft. Take the first field.\n',
         'current.tsv': 'saffron\tqueued\nmaple\treview\n', 'scratch.tsv': 'lilac\tdraft\n'},
        ('tool fs.read\npath: HANDOFF.txt', 'run\ncut -f 1 -- current.tsv > ticket-list.txt',
         'tool fs.read\npath: ticket-list.txt', 'done\nWrote ticket-list.txt from current.tsv.'),
        {'ticket-list.txt': 'saffron\nmaple\n'},
    ),
    Task(
        'aggregate_signed_amounts',
        'What is the net total of the signed adjustments in adjustments.txt? Do not modify it.',
        {'adjustments.txt': '18\n-5\n2\n-4\n'},
        ("run\nawk '{sum += $1} END {print sum}' adjustments.txt", 'done\nThe net total is 11.'),
        {}, r'(?<![\w+\-])(?:11|eleven)\b',
    ),
    Task(
        'literal_marker_filter',
        'Write the rows from build-events.txt that contain the literal marker [OK] to successful.txt, preserving order.',
        {'build-events.txt': '[OK] pack\nK ignored\n[FAIL] link\n[OK] render\n'},
        ("run\ngrep -F -- '[OK]' build-events.txt > successful.txt", 'tool fs.read\npath: successful.txt',
         'done\nWrote successful.txt.'),
        {'successful.txt': '[OK] pack\n[OK] render\n'},
    ),
    Task(
        'merge_pages_in_named_order',
        'Combine intro.md, examples.md, then closing.md in exactly that order into leaflet.md without adding headers or separators.',
        {'intro.md': '# Field notes\n', 'examples.md': 'Example: sketch a leaf.\n',
         'closing.md': 'End of leaflet.\n'},
        ('run\ncat -- intro.md examples.md closing.md > leaflet.md', 'tool fs.read\npath: leaflet.md',
         'done\nCombined the three files into leaflet.md.'),
        {'leaflet.md': '# Field notes\nExample: sketch a leaf.\nEnd of leaflet.\n'},
    ),
)


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    """Require the exact staged effect or observed evidence for a read-only answer."""
    failures = []
    if not original_unchanged:
        failures.append('original workspace changed')
    if terminal != 'done':
        failures.append('expected done')
    if changes != task.changes:
        failures.append('staged effects differ from expected output')
    if task.answer_pattern:
        if not re.search(task.answer_pattern, answer or '', re.IGNORECASE):
            failures.append('answer is missing the requested result')
        if not any(not error and obs.startswith('exit=0\n') and policy_of(obs) == 'ok'
                   for _, obs, error in events):
            failures.append('read-only answer lacks a successful tool observation')
    if any(policy_of(obs) != 'ok' for _, obs, _ in events):
        failures.append('unexpected policy stop')
    return failures
