"""Fresh development fixtures for the v4 round: multi-line appends, edits where the target text
occurs more than once, and questions whose answer must be quoted exactly.

Written from the weakness *names* only (docs/plan/INTERFACE-V4.md). No held-out trace or task
text was used, and the tasks are audited against the frozen held-out manifest for overlap
(tests/unit/test_dev_focus.py). Kept out of the 80-task development roster so that roster's
evaluation fingerprint stays comparable across rounds; run with `python -m dev.focus_runner`.
Questions are issued in `ask` mode (ASK) with oracles whose last command prints the answer.
"""
from dev.dev_verification import Task, grade as grade  # noqa: F401  (shared grader)

APPEND = (
    Task(
        'append_dated_journal_block',
        'Add this entry at the end of journal.md, exactly as two lines: "## Sunday" and then "- Called the plumber". Keep everything already there.',
        {'journal.md': '# Journal\n\n## Saturday\n- Bought paint\n'},
        ("run\nprintf '%s\\n' '## Sunday' '- Called the plumber' >> journal.md", 'tool fs.read\npath: journal.md',
         'done'),
        {'journal.md': '# Journal\n\n## Saturday\n- Bought paint\n## Sunday\n- Called the plumber\n'},
    ),
    Task(
        'append_two_csv_rows',
        'Append two rows to fruit.csv: pear,4 and then plum,7. Do not touch the existing rows.',
        {'fruit.csv': 'name,count\napple,3\nfig,9\n'},
        ("run\nprintf '%s\\n' 'pear,4' 'plum,7' >> fruit.csv", 'tool fs.read\npath: fruit.csv', 'done'),
        {'fruit.csv': 'name,count\napple,3\nfig,9\npear,4\nplum,7\n'},
    ),
    Task(
        'append_yaml_list_item',
        'Add a job to the end of jobs.yaml with name: backup and every: daily, in the same format as the existing job.',
        {'jobs.yaml': 'jobs:\n  - name: rotate\n    every: weekly\n'},
        ("run\nprintf '%s\\n' '  - name: backup' '    every: daily' >> jobs.yaml", 'tool fs.read\npath: jobs.yaml',
         'done'),
        {'jobs.yaml': 'jobs:\n  - name: rotate\n    every: weekly\n  - name: backup\n    every: daily\n'},
    ),
    Task(
        'append_after_missing_final_newline',
        'Add two lines to the end of guests.txt: Omar and then Priya. The file currently has no newline at the end; each name must end up on its own line.',
        {'guests.txt': 'Lena\nTomas'},
        ("run\nprintf '\\n%s\\n%s\\n' Omar Priya >> guests.txt", 'tool fs.read\npath: guests.txt', 'done'),
        {'guests.txt': 'Lena\nTomas\nOmar\nPriya\n'},
    ),
    Task(
        'append_signature_block',
        'Finish letter.txt by adding three lines at the end: an empty line, "Best regards," and "Sam".',
        {'letter.txt': 'Hello Ines,\nThe tiles arrive Tuesday.\n'},
        ("run\nprintf '%s\\n' '' 'Best regards,' 'Sam' >> letter.txt", 'tool fs.read\npath: letter.txt', 'done'),
        {'letter.txt': 'Hello Ines,\nThe tiles arrive Tuesday.\n\nBest regards,\nSam\n'},
    ),
)

REPEATED = (
    Task(
        'edit_port_in_named_section',
        'In server.ini, change the port of the [prod] section to 9090. The [dev] section must keep its port.',
        {'server.ini': '[dev]\nport=8080\nhost=localhost\n\n[prod]\nport=8080\nhost=example.org\n'},
        ('tool fs.read\npath: server.ini', 'tool fs.edit\npath: server.ini\nold <<<\nport=8080\nhost=example.org\n>>>\nnew <<<\nport=9090\nhost=example.org\n>>>',
         'tool fs.read\npath: server.ini', 'done'),
        {'server.ini': '[dev]\nport=8080\nhost=localhost\n\n[prod]\nport=9090\nhost=example.org\n'},
    ),
    Task(
        'tick_friday_chore_only',
        'In chores.md, mark "water plants" as done under Friday only (change [ ] to [x] there). Leave Monday as it is.',
        {'chores.md': '## Monday\n- [ ] water plants\n- [ ] bins\n\n## Friday\n- [ ] water plants\n- [ ] laundry\n'},
        ('tool fs.read\npath: chores.md',
         'tool fs.edit\npath: chores.md\nold <<<\n## Friday\n- [ ] water plants\n>>>\nnew <<<\n## Friday\n- [x] water plants\n>>>',
         'tool fs.read\npath: chores.md', 'done'),
        {'chores.md': '## Monday\n- [ ] water plants\n- [ ] bins\n\n## Friday\n- [x] water plants\n- [ ] laundry\n'},
    ),
    Task(
        'set_quantity_for_named_item',
        'In parts.txt, set the qty of nuts to 8. Bolts also have qty 5 and must stay at 5.',
        {'parts.txt': 'item: bolts\nqty: 5\n\nitem: nuts\nqty: 5\n'},
        ('tool fs.read\npath: parts.txt', 'tool fs.edit\npath: parts.txt\nold <<<\nitem: nuts\nqty: 5\n>>>\nnew <<<\nitem: nuts\nqty: 8\n>>>',
         'tool fs.read\npath: parts.txt', 'done'),
        {'parts.txt': 'item: bolts\nqty: 5\n\nitem: nuts\nqty: 8\n'},
    ),
    Task(
        'mark_second_order_shipped',
        'Order B-2 in orders.txt has shipped: change its status to shipped. Order A-1 stays pending.',
        {'orders.txt': 'order A-1\nstatus: pending\n\norder B-2\nstatus: pending\n'},
        ('tool fs.read\npath: orders.txt',
         'tool fs.edit\npath: orders.txt\nold <<<\norder B-2\nstatus: pending\n>>>\nnew <<<\norder B-2\nstatus: shipped\n>>>',
         'tool fs.read\npath: orders.txt', 'done'),
        {'orders.txt': 'order A-1\nstatus: pending\n\norder B-2\nstatus: shipped\n'},
    ),
    Task(
        'shorten_second_stage_pause',
        'In stages.sh, the pause after "echo stage two" should be sleep 1. The pause after "echo stage one" stays sleep 5.',
        {'stages.sh': '#!/bin/sh\necho stage one\nsleep 5\necho stage two\nsleep 5\necho done\n'},
        ('tool fs.read\npath: stages.sh', 'tool fs.edit\npath: stages.sh\nold <<<\necho stage two\nsleep 5\n>>>\nnew <<<\necho stage two\nsleep 1\n>>>',
         'tool fs.read\npath: stages.sh', 'done'),
        {'stages.sh': '#!/bin/sh\necho stage one\nsleep 5\necho stage two\nsleep 1\necho done\n'},
    ),
)

QUESTIONS = (
    Task(
        'retries_in_json_settings',
        'How many retries are configured in settings.json?',
        {'settings.json': '{\n  "timeout": 30,\n  "retries": 4,\n  "verbose": false\n}\n'},
        ('tool fs.read\npath: settings.json', 'done\nretries is 4.'),
        facts=(r'\bretries\b\D{0,12}\b4\b',), evidence=(r'"retries": 4',),
    ),
    Task(
        'count_vegan_guests',
        'How many lines in rsvp.txt mention vegan?',
        {'rsvp.txt': 'Ada - vegan\nBo - none\nCy - vegan, no nuts\nDee - vegetarian\nEd - vegan\n'},
        ('tool fs.read\npath: rsvp.txt', 'done\n3 lines mention vegan.'),
        facts=(r'^\s*3\s*$',),
    ),
    Task(
        'which_note_mentions_invoice',
        'Which file in notes/ mentions an invoice? Tell me its name.',
        {'notes/monday.txt': 'call the bank\n', 'notes/tuesday.txt': 'send invoice 2231 to Hale\n',
         'notes/wednesday.txt': 'gym\n'},
        ('tool fs.list\npath: notes', 'done\nnotes/tuesday.txt'),
        facts=(r'\btuesday\.txt\b',), contradicts=r'\b(?:monday|wednesday)\.txt\b',
    ),
    Task(
        'display_name_with_space',
        'What is the display name in profile.conf?',
        {'profile.conf': 'user = ada\ndisplay_name = Ada Lovelace\ntheme = dark\n'},
        ('tool fs.read\npath: profile.conf', 'done\nAda Lovelace'),
        facts=(r'\bAda Lovelace\b',), contradicts=r'\bdark\b',
    ),
    Task(
        'last_line_of_history',
        'What is the last line of history.log?',
        {'history.log': '09:00 start\n09:05 sync\n09:12 stop\n'},
        ('tool fs.read\npath: history.log', 'done\n09:12 stop'),
        facts=(r'09:12 stop',), contradicts=r'09:0[05]',
    ),
)

TASKS = APPEND + REPEATED + QUESTIONS

ASK = frozenset(task.id for task in QUESTIONS)

ORACLES = {
    'retries_in_json_settings': ("run\ngrep '\"retries\"' settings.json", 'done'),
    'count_vegan_guests': ('run\ngrep -c vegan rsvp.txt', 'done'),
    'which_note_mentions_invoice': ('run\ngrep -l invoice notes/*', 'done'),
    'display_name_with_space': ("run\nsed -n 's/^display_name = //p' profile.conf", 'done'),
    'last_line_of_history': ('run\ntail -n 1 history.log', 'done'),
}

GROUPS = {'append': APPEND, 'repeated-text edit': REPEATED, 'exact answer': QUESTIONS}
