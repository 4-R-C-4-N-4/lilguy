"""Fresh development fixtures for the round after 2.0 (corpus revision 11).

Written from the weakness *names* that 2.0's model card lists, never from held-out traces or
task text: questions (quote a value, count lines) regressed against 1.0; exact multi-line file
creation; noticing that a named file is missing; appending to a file without a final newline.
Audited against every frozen held-out suite and the 80-task roster
(tests/unit/test_focus_r11.py); kept out of that roster so its fingerprint stays comparable.

    .venv/bin/python -m dev.focus_runner SERVER GGUF OUT --set r11 [--interface N]
"""
from dev.dev_verification import Task, grade as grade  # noqa: F401  (shared grader)

QUOTE = (
    Task('quote_cache_size', 'What cache size does proxy.conf set?',
         {'proxy.conf': 'listen=3128\ncache_size=512MB\nlog=off\n'},
         ('tool fs.read\npath: proxy.conf', 'done\n512MB'), facts=(r'(?<![\w.-])512MB(?![\w.])',),
         contradicts=r'\b3128\b'),
    Task('quote_maintainer_email', 'Who is listed as maintainer in package.meta? Give the email.',
         {'package.meta': 'name: tidy\nmaintainer: ruth@example.net\nlicense: MIT\n'},
         ('tool fs.read\npath: package.meta', 'done\nruth@example.net'), facts=(r'ruth@example\.net',)),
    Task('quote_backup_window', 'When does the backup window start according to ops.toml?',
         {'ops.toml': 'region = "north"\nbackup_start = "02:30"\nbackup_end = "04:00"\n'},
         ('tool fs.read\npath: ops.toml', 'done\n02:30'), facts=(r'02:30',), contradicts=r'04:00'),
    Task('quote_second_section_value', 'In mixer.ini, what volume does the [rear] section use?',
         {'mixer.ini': '[front]\nvolume=70\n\n[rear]\nvolume=55\n'},
         ('tool fs.read\npath: mixer.ini', 'done\n55'), facts=(r'(?<!\d)55(?!\d)',), contradicts=r'(?<!\d)70(?!\d)'),
    Task('quote_json_nested_flag', 'Is dark mode on or off in prefs.json?',
         {'prefs.json': '{\n  "ui": {\n    "dark_mode": "off",\n    "font": "serif"\n  }\n}\n'},
         ('tool fs.read\npath: prefs.json', 'done\noff'), facts=(r'\boff\b',)),
)

COUNT = (
    Task('count_failed_jobs', 'How many jobs in cron.log failed?',
         {'cron.log': 'job1 ok\njob2 failed\njob3 ok\njob4 failed\njob5 failed\njob6 ok\n'},
         ('tool fs.read\npath: cron.log', 'done\n3'), facts=(r'^\s*3\s*$',)),
    Task('count_todo_markers', 'How many lines in plan.md contain TODO?',
         {'plan.md': '# Plan\nTODO buy wood\ncut boards\nTODO sand\nTODO paint\nTODO varnish\n'},
         ('tool fs.read\npath: plan.md', 'done\n4'), facts=(r'^\s*4\s*$',)),
    Task('count_rows_without_header', 'How many members are listed in members.csv (not counting the header)?',
         {'members.csv': 'name,joined\nAnya,2021\nBeto,2022\nCleo,2024\n'},
         ('tool fs.read\npath: members.csv', 'done\n3'), facts=(r'^\s*3\s*$',)),
    Task('count_exact_word_lines', 'How many lines of answers.txt are exactly "no"?',
         {'answers.txt': 'yes\nno\nnot sure\nno\nnope\nno\n'},
         ('tool fs.read\npath: answers.txt', 'done\n3'), facts=(r'^\s*3\s*$',)),
    Task('count_files_in_folder', 'How many files are in the invoices folder?',
         {'invoices/a.pdf': 'a\n', 'invoices/b.pdf': 'b\n', 'invoices/c.pdf': 'c\n', 'invoices/d.pdf': 'd\n',
          'readme.txt': 'top\n'},
         ('tool fs.list\npath: invoices', 'done\n4'), facts=(r'^\s*4\s*$',)),
)

CREATE = (
    Task('create_two_line_note', 'Create todo.txt with exactly two lines: "water plants" and "call Mia".',
         {'notes.txt': 'misc\n'},
         ("run\nprintf '%s\\n' 'water plants' 'call Mia' > todo.txt", 'tool fs.read\npath: todo.txt', 'done'),
         {'todo.txt': 'water plants\ncall Mia\n'}),
    Task('create_config_in_folder', 'Create conf/app.env containing these lines: PORT=7000 and DEBUG=false. The conf folder already exists.',
         {'conf/base.env': 'TZ=UTC\n'},
         ("run\nprintf '%s\\n' 'PORT=7000' 'DEBUG=false' > conf/app.env", 'tool fs.read\npath: conf/app.env', 'done'),
         {'conf/app.env': 'PORT=7000\nDEBUG=false\n'}),
    Task('create_markdown_list', 'Make a file shopping.md with a heading "# Shopping" followed by the items "- eggs" and "- rice", one per line.',
         {'recipes.md': '# Recipes\n'},
         ("run\nprintf '%s\\n' '# Shopping' '- eggs' '- rice' > shopping.md", 'tool fs.read\npath: shopping.md', 'done'),
         {'shopping.md': '# Shopping\n- eggs\n- rice\n'}),
    Task('create_with_blank_line', 'Create note.txt with three lines: "Dear team,", an empty line, and "See you Monday."',
         {'draft.txt': 'old draft\n'},
         ("run\nprintf '%s\\n' 'Dear team,' '' 'See you Monday.' > note.txt", 'tool fs.read\npath: note.txt', 'done'),
         {'note.txt': 'Dear team,\n\nSee you Monday.\n'}),
    Task('create_indented_yaml', 'Create service.yaml with exactly these three lines: "service:", "  name: web" and "  replicas: 2".',
         {'deploy.txt': 'pending\n'},
         ("run\nprintf '%s\\n' 'service:' '  name: web' '  replicas: 2' > service.yaml", 'tool fs.read\npath: service.yaml', 'done'),
         {'service.yaml': 'service:\n  name: web\n  replicas: 2\n'}),
)

MISSING = (
    Task('missing_changelog_2', 'Add a line "fixed login" to CHANGELOG-2.md.',
         {'CHANGELOG-1.md': '# 1\n', 'CHANGES.md': '# all\n'},
         ('tool fs.list\npath: .', 'ask\nCHANGELOG-2.md does not exist. Should I create it or use CHANGELOG-1.md?'),
         terminal='ask', facts=(r'CHANGELOG-2\.md',)),
    Task('missing_settings_local', 'Set debug to true in settings.local.ini.',
         {'settings.ini': 'debug=false\n', 'settings.dev.ini': 'debug=false\n'},
         ('tool fs.list\npath: .', 'ask\nsettings.local.ini is not here. Which file should I change?'),
         terminal='ask', facts=(r'settings\.local\.ini',)),
    Task('missing_in_subfolder', 'Fix the typo "recieve" in docs/guide.md.',
         {'docs/intro.md': 'how to recieve mail\n', 'docs/faq.md': 'faq\n'},
         ('tool fs.list\npath: docs', 'ask\ndocs/guide.md does not exist; there is intro.md and faq.md. Which one?'),
         terminal='ask', facts=(r'guide\.md',)),
    Task('missing_year_file', 'Add "rent 950" to expenses-2027.txt.',
         {'expenses-2025.txt': 'rent 900\n', 'expenses-2026.txt': 'rent 925\n'},
         ('tool fs.list\npath: .', 'ask\nexpenses-2027.txt does not exist. Should I create it?'),
         terminal='ask', facts=(r'expenses-2027\.txt',)),
    Task('missing_script', 'Make backup.sh print "done" at the end.',
         {'backup.py': 'print("start")\n', 'restore.sh': 'echo restore\n'},
         ('tool fs.list\npath: .', 'ask\nbackup.sh is not here; there is backup.py and restore.sh. Which should I change?'),
         terminal='ask', facts=(r'backup\.sh',)),
)

NO_EOL = (
    Task('append_one_line_no_eol', 'Add "gamma" as a new last line of names.txt.',
         {'names.txt': 'alpha\nbeta'},
         ("run\nprintf '\\n%s\\n' gamma >> names.txt", 'tool fs.read\npath: names.txt', 'done'),
         {'names.txt': 'alpha\nbeta\ngamma\n'}),
    Task('append_two_lines_no_eol', 'Append "cpu=4" and then "mem=8G" to limits.conf, each on its own line.',
         {'limits.conf': 'disk=50G'},
         ("run\nprintf '\\n%s\\n%s\\n' cpu=4 mem=8G >> limits.conf", 'tool fs.read\npath: limits.conf', 'done'),
         {'limits.conf': 'disk=50G\ncpu=4\nmem=8G\n'}),
    Task('append_list_item_no_eol', 'Add "- tape" to the end of the list in supplies.md.',
         {'supplies.md': '# Supplies\n- glue\n- scissors'},
         ("run\nprintf '\\n%s\\n' '- tape' >> supplies.md", 'tool fs.read\npath: supplies.md', 'done'),
         {'supplies.md': '# Supplies\n- glue\n- scissors\n- tape\n'}),
    Task('append_csv_row_no_eol', 'Append the row "ink,2" to stock.csv.',
         {'stock.csv': 'item,qty\npaper,10'},
         ("run\nprintf '\\n%s\\n' 'ink,2' >> stock.csv", 'tool fs.read\npath: stock.csv', 'done'),
         {'stock.csv': 'item,qty\npaper,10\nink,2\n'}),
    Task('append_hosts_no_eol', 'Add the line "10.0.0.9 nas" at the end of hosts.txt.',
         {'hosts.txt': '127.0.0.1 localhost\n10.0.0.2 printer'},
         ("run\nprintf '\\n%s\\n' '10.0.0.9 nas' >> hosts.txt", 'tool fs.read\npath: hosts.txt', 'done'),
         {'hosts.txt': '127.0.0.1 localhost\n10.0.0.2 printer\n10.0.0.9 nas\n'}),
)

TASKS = QUOTE + COUNT + CREATE + MISSING + NO_EOL

ASK = frozenset(task.id for task in QUOTE + COUNT)

ORACLES = {
    'quote_cache_size': ("run\nsed -n 's/^cache_size=//p' proxy.conf", 'done'),
    'quote_maintainer_email': ("run\nsed -n 's/^maintainer: //p' package.meta", 'done'),
    'quote_backup_window': ("run\nsed -n 's/^backup_start = \"\\(.*\\)\"/\\1/p' ops.toml", 'done'),
    'quote_second_section_value': ("run\nsed -n '/^\\[rear\\]/,/^\\[/s/^volume=//p' mixer.ini", 'done'),
    'quote_json_nested_flag': ("run\nsed -n 's/.*\"dark_mode\": \"\\(.*\\)\",/\\1/p' prefs.json", 'done'),
    'count_failed_jobs': ('run\ngrep -c failed cron.log', 'done'),
    'count_todo_markers': ('run\ngrep -c TODO plan.md', 'done'),
    'count_rows_without_header': ('run\ntail -n +2 members.csv | wc -l', 'done'),
    'count_exact_word_lines': ('run\ngrep -cx no answers.txt', 'done'),
    'count_files_in_folder': ('run\nls invoices | wc -l', 'done'),
}

GROUPS = {'quote a value': QUOTE, 'count lines': COUNT, 'create exact file': CREATE,
          'named file missing': MISSING, 'append without final newline': NO_EOL}
