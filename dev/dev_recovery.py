"""Development-only recovery fixtures (roadmap category 'recovery', batch 7).

Each fixture sets a trap a natural first attempt falls into: a path one folder away, a literal
that does not match byte for byte, a destination that does not exist yet, a case mismatch. A careful
model can avoid the trap, so making the mistake is never required to pass; only the end state and
the final answer are graded. Following the focus 'named file missing' convention, a file with the
exact requested name elsewhere is found and used, never asked about.
"""
from dev.dev_workspace import Task, grade  # noqa: F401  (grade is this suite's grader)

TASKS = (
    Task(
        'port_in_settings_one_level_down',
        'Change the port in settings.conf from 8080 to 9090.',
        {'service/settings.conf': 'host=0.0.0.0\nport=8080\n', 'service/README': 'Service files.\n'},
        ('tool fs.read\npath: settings.conf', 'tool fs.find\nname_glob: settings.conf',
         'tool fs.edit\npath: service/settings.conf\nold: port=8080\nnew: port=9090',
         'done\nsettings.conf was in service/; changed its port to 9090.'),
        {'service/settings.conf': 'host=0.0.0.0\nport=9090\n'},
        facts=(r'service/settings\.conf|\bservice/',),
    ),
    Task(
        'aligned_column_edit',
        "In roster.txt, change Sam's shift from early to late. Keep the columns lined up.",
        {'roster.txt': 'Sam     early\nAnaya   late\nBo      early\n'},
        ('tool fs.read\npath: roster.txt',
         'tool fs.edit\npath: roster.txt\nold: Sam     early\nnew: Sam     late',
         'tool fs.read\npath: roster.txt', "done\nChanged Sam's shift to late."),
        {'roster.txt': 'Sam     late\nAnaya   late\nBo      early\n'},
    ),
    Task(
        'copy_into_missing_folder',
        'Save a copy of draft.txt as out/final/draft.txt.',
        {'draft.txt': 'Third and last draft.\n', 'out/README': 'Outputs.\n'},
        ('run\ncp draft.txt out/final/draft.txt', 'run\nmkdir -p out/final && cp draft.txt out/final/draft.txt',
         'tool fs.read\npath: out/final/draft.txt', 'done\nCreated out/final/ and copied draft.txt into it.'),
        {'out/final': '<dir added>', 'out/final/draft.txt': 'Third and last draft.\n'},
    ),
    Task(
        'notes_is_a_folder',
        'Read the notes and tell me the date of the next meeting.',
        {'notes/meeting.txt': 'Next meeting: 14 March\nRoom: B2\n', 'agenda.md': '# Agenda\n'},
        ('tool fs.read\npath: notes', 'tool fs.list\npath: notes', 'tool fs.read\npath: notes/meeting.txt',
         'done\nThe next meeting is on 14 March.'),
        facts=(r'\b14\s+March\b|\bMarch\s+14\b',), evidence=(r'14 March',),
    ),
    Task(
        'error_code_case_mismatch',
        'Which file in logs/ mentions the error code e42? Tell me its name.',
        {'logs/monday.log': 'ok\nok\n', 'logs/tuesday.log': 'ok\nERROR E42 disk full\n',
         'logs/wednesday.log': 'warn E41 slow\n'},
        ('run\ngrep -l e42 logs/*.log', 'run\ngrep -il e42 logs/*.log', 'done\nlogs/tuesday.log mentions E42.'),
        facts=(r'tuesday\.log',), evidence=(r'tuesday\.log',),
        contradicts=r'\b(?:no|none of the)\s+(?:file|log)s?\b[^.\n]{0,30}\bmention|wednesday\.log\s+mentions',
    ),
    Task(
        'copy_three_one_elsewhere',
        'Copy a.txt, b.txt and c.txt into share/.',
        {'a.txt': 'alpha\n', 'b.txt': 'bravo\n', 'extra/c.txt': 'charlie\n', 'share/README': 'Shared.\n'},
        ('run\ncp a.txt b.txt c.txt share/', 'tool fs.find\nname_glob: c.txt', 'run\ncp extra/c.txt share/',
         'tool fs.list\npath: share', 'done\nCopied a.txt and b.txt, and c.txt from extra/, into share/.'),
        {'share/a.txt': 'alpha\n', 'share/b.txt': 'bravo\n', 'share/c.txt': 'charlie\n'},
    ),
    Task(
        'windows_path_literal_replace',
        r'In win.ini, change path=C:\temp to path=D:\temp. Change nothing else.',
        {'win.ini': '[paths]\npath=C:\\temp\nlog=C:\\temp\\log\n'},
        ('tool fs.read\npath: win.ini', 'tool fs.edit\npath: win.ini\nold: path=C:\\temp\nnew: path=D:\\temp',
         'tool fs.read\npath: win.ini', 'done\nChanged path to D:\\temp; the log line is untouched.'),
        {'win.ini': '[paths]\npath=D:\\temp\nlog=C:\\temp\\log\n'},
    ),
    Task(
        'remove_whitespace_only_lines',
        'Remove the blank lines from list.txt, including lines that only contain spaces or tabs.',
        {'list.txt': 'pens\n\nink\n   \npaper\n\t\nclips\n'},
        ("run\nsed -i '/^[[:space:]]*$/d' list.txt", 'tool fs.read\npath: list.txt',
         'done\nRemoved the four blank lines.'),
        {'list.txt': 'pens\nink\npaper\nclips\n'},
    ),
)
