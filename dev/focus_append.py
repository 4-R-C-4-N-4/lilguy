"""Development probe for multi-line appends (after 3.0; never training data, never held-out).

3.0's model card names "appending exact lines" as its one regression against 2.0. This probe asks
whether that reproduces on fresh development fixtures: two or three lines appended in order, to
files that end with a newline and to files that do not. Written from the weakness's name, not
from held-out traces or task text; audited against every frozen held-out suite
(tests/unit/test_focus_append.py).

    .venv/bin/python -m dev.focus_runner SERVER GGUF OUT --set append [--interface N]
"""
import shlex

from dev.dev_verification import Task, grade as grade  # noqa: F401  (shared grader)

_PHRASES = (
    'Append {lines} to {f}, one per line, in that order.',
    'Put {lines} at the bottom of {f}, each on its own line.',
    'At the end of {f}, add {lines} as separate lines, keeping their order.',
    'Add {lines} after the last line of {f}, one per line.',
)

# (file, existing text, lines to add). The first ten end with a newline; the last ten do not.
_CASES = (
    ('pantry.list', 'flour\nsugar\n', ['salt', 'yeast']),
    ('crew.roster', 'Mira (deck)\n', ['Odile (galley)', 'Sven (engine)', 'Tariq (helm)']),
    ('bookmarks.txt', 'https://example.org/a\n', ['https://example.org/b', 'https://example.org/c']),
    ('plants.md', '# Plants\n- fern\n', ['- ivy', '- moss']),
    ('ports.conf', 'http=80\n', ['https=443', 'ssh=22', 'ftp=21']),
    ('chores.txt', 'mon: bins\ntue: laundry\n', ['wed: windows', 'thu: floors']),
    ('authors.csv', 'name,year\nWoolf,1927\n', ['Morrison,1987', 'Ishiguro,1989']),
    ('aliases.sh', "alias ll='ls -l'\n", ["alias gs='git status'", "alias ..='cd ..'"]),
    ('rivers.txt', 'Danube\nRhine\n', ['Elbe', 'Oder', 'Vistula']),
    ('todo.org', '* TODO call plumber\n', ['* TODO renew passport', '* TODO book dentist']),
    ('seeds.list', 'basil', ['chives', 'dill']),
    ('players.txt', 'Ana\nBo', ['Cy', 'Dee', 'Eli']),
    ('mirrors.txt', 'mirror.one.example', ['mirror.two.example', 'mirror.three.example']),
    ('songs.md', '# Setlist\n1. Opener', ['2. Ballad', '3. Encore']),
    ('limits.ini', 'files=1024', ['procs=512', 'stack=8M']),
    ('stations.txt', 'Alder\nBirch', ['Cedar', 'Dogwood']),
    ('grades.csv', 'student,score\nLi,91', ['Ngo,84', 'Oak,77', 'Pym,95']),
    ('paths.env', 'PATH_A=/opt/a', ['PATH_B=/opt/b', 'PATH_C=/opt/c']),
    ('moons.txt', 'Io\nEuropa', ['Ganymede', 'Callisto']),
    ('steps.txt', '1) unplug', ['2) open case', '3) swap fan']),
)


def _printf(lines):
    return "printf '%s\\n' " + ' '.join(shlex.quote(line) for line in lines)


TASKS = []
for i, (path, before, lines) in enumerate(_CASES):
    quoted = ' and then '.join(f'"{line}"' for line in lines)
    request = _PHRASES[i % len(_PHRASES)].format(lines=quoted, f=path)
    lead = '' if before.endswith('\n') else f"printf '\\n' >> {path} && "
    after = before + ('' if before.endswith('\n') else '\n') + ''.join(f'{line}\n' for line in lines)
    TASKS.append(Task(f'append_probe_{path.replace(".", "_")}', request, {path: before},
                      (f'tool fs.read\npath: {path}', f'run\n{lead}{_printf(lines)} >> {path}',
                       f'tool fs.read\npath: {path}', 'done\nAppended.'),
                      {path: after}))
TASKS = tuple(TASKS)
ASK = frozenset()
ORACLES = {}
GROUPS = {'file ends with newline': TASKS[:10], 'no final newline': TASKS[10:]}
