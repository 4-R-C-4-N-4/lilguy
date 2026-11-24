"""Development-only organising fixtures (roadmap category 'organise', batch 7)."""
from dev.dev_workspace import Task, grade  # noqa: F401  (grade is this suite's grader)

TASKS = (
    Task(
        'sort_inbox_by_type',
        'Sort inbox/: move the .png and .jpg files into inbox/images/ and the .txt and .md files into '
        'inbox/docs/. Make both folders.',
        {'inbox/logo.png': 'PNG stand-in\n', 'inbox/team.jpg': 'JPG stand-in\n',
         'inbox/agenda.txt': 'Item one\n', 'inbox/plan.md': '# Plan\n'},
        ('tool fs.list\npath: inbox',
         'run\nmkdir inbox/images inbox/docs && mv inbox/logo.png inbox/team.jpg inbox/images/ '
         '&& mv inbox/agenda.txt inbox/plan.md inbox/docs/',
         'done\nThe four moves are staged and pending your approval.'),
        {'inbox/logo.png': None, 'inbox/team.jpg': None, 'inbox/agenda.txt': None, 'inbox/plan.md': None,
         'inbox/images': '<dir added>', 'inbox/docs': '<dir added>',
         'inbox/images/logo.png': 'PNG stand-in\n', 'inbox/images/team.jpg': 'JPG stand-in\n',
         'inbox/docs/agenda.txt': 'Item one\n', 'inbox/docs/plan.md': '# Plan\n'},
        policy_end='pending',
    ),
    Task(
        'file_minutes_by_month',
        'Copy each file in minutes/ into a folder named after the year and month in its name, like '
        'by-month/2026-03/. Keep the originals.',
        {'minutes/2026-03-04-standup.txt': 'Short one.\n', 'minutes/2026-03-18-review.txt': 'Long one.\n',
         'minutes/2026-04-01-planning.txt': 'Quarter plan.\n'},
        ('tool fs.list\npath: minutes',
         'run\nmkdir -p by-month/2026-03 by-month/2026-04 && cp minutes/2026-03-* by-month/2026-03/ '
         '&& cp minutes/2026-04-* by-month/2026-04/',
         'tool fs.list\npath: by-month', 'done\nCopied the March and April minutes into by-month/.'),
        {'by-month': '<dir added>', 'by-month/2026-03': '<dir added>', 'by-month/2026-04': '<dir added>',
         'by-month/2026-03/2026-03-04-standup.txt': 'Short one.\n',
         'by-month/2026-03/2026-03-18-review.txt': 'Long one.\n',
         'by-month/2026-04/2026-04-01-planning.txt': 'Quarter plan.\n'},
    ),
    Task(
        'zero_pad_page_names',
        'In scans/, rename the pages so the numbers have two digits: page1.txt becomes page01.txt. '
        'Leave page10.txt and page11.txt as they are.',
        {'scans/page1.txt': 'one\n', 'scans/page2.txt': 'two\n', 'scans/page10.txt': 'ten\n',
         'scans/page11.txt': 'eleven\n'},
        ('tool fs.list\npath: scans',
         'run\nmv scans/page1.txt scans/page01.txt && mv scans/page2.txt scans/page02.txt',
         'done\nRenaming page1 and page2 to page01 and page02 is staged and pending your approval.'),
        {'scans/page1.txt': None, 'scans/page2.txt': None, 'scans/page01.txt': 'one\n',
         'scans/page02.txt': 'two\n'},
        policy_end='pending',
    ),
    Task(
        'flatten_nested_text_files',
        'Copy every .txt file anywhere under deep/ straight into flat/, keeping the file names. Leave deep/ as it is.',
        {'deep/a/one.txt': 'first\n', 'deep/a/b/two.txt': 'second\n', 'deep/c/three.txt': 'third\n',
         'deep/c/skip.csv': 'x,y\n', 'flat/README': 'Flat copies only.\n'},
        ("run\nfind deep -name '*.txt' -exec cp {} flat/ \\;", 'tool fs.list\npath: flat',
         'done\nCopied one.txt, two.txt and three.txt into flat/.'),
        {'flat/one.txt': 'first\n', 'flat/two.txt': 'second\n', 'flat/three.txt': 'third\n'},
    ),
    Task(
        'merge_camera_folders_with_prefix',
        'Copy the photos from cam-a/ and cam-b/ into all/, putting the camera name in front of each '
        'file name, like cam-a-IMG1.txt. Keep the originals.',
        {'cam-a/IMG1.txt': 'harbour\n', 'cam-a/IMG2.txt': 'lighthouse\n', 'cam-b/IMG1.txt': 'market\n',
         'all/README': 'Merged photos.\n'},
        ('run\nfor c in cam-a cam-b; do for f in "$c"/*; do cp "$f" "all/$c-$(basename "$f")"; done; done',
         'tool fs.list\npath: all', 'done\nCopied all three photos into all/ with camera prefixes.'),
        {'all/cam-a-IMG1.txt': 'harbour\n', 'all/cam-a-IMG2.txt': 'lighthouse\n',
         'all/cam-b-IMG1.txt': 'market\n'},
    ),
    Task(
        'lowercase_doc_names',
        'Rename README.TXT in docs/ to readme.txt. Do not touch anything else.',
        {'docs/README.TXT': 'Read me first.\n', 'docs/Guide.md': '# Guide\n'},
        ('tool fs.list\npath: docs', 'run\nmv docs/README.TXT docs/readme.txt',
         'done\nRenaming docs/README.TXT to docs/readme.txt is staged and pending your approval.'),
        {'docs/README.TXT': None, 'docs/readme.txt': 'Read me first.\n'}, policy_end='pending',
    ),
    Task(
        'move_closed_tickets',
        'Move every ticket in tickets/ that has a line "state: closed" into tickets/closed/. Leave the open ones.',
        {'tickets/t1.txt': 'title: door\nstate: closed\n', 'tickets/t2.txt': 'title: lamp\nstate: open\n',
         'tickets/t3.txt': 'title: sink\nstate: closed\n', 'tickets/closed/README': 'Closed tickets.\n'},
        ("run\ngrep -lx 'state: closed' tickets/*.txt", 'run\nmv tickets/t1.txt tickets/t3.txt tickets/closed/',
         'done\nMoving t1 and t3 into tickets/closed/ is staged and pending your approval.'),
        {'tickets/t1.txt': None, 'tickets/t3.txt': None, 'tickets/closed/t1.txt': 'title: door\nstate: closed\n',
         'tickets/closed/t3.txt': 'title: sink\nstate: closed\n'},
        policy_end='pending',
    ),
    Task(
        'dashes_for_spaces_in_names',
        'Copy each file in uploads/ into clean/ with the spaces in its name replaced by dashes. '
        'Keep the extensions and the originals.',
        {'uploads/my notes.txt': 'notes\n', 'uploads/team photo list.md': 'photos\n',
         'uploads/plain.txt': 'plain\n', 'clean/README': 'Clean names.\n'},
        ('tool fs.list\npath: uploads',
         'run\nfor f in uploads/*; do n=$(basename "$f"); cp "$f" "clean/${n// /-}"; done',
         'tool fs.list\npath: clean', 'done\nCopied the three files into clean/ with dashes for spaces.'),
        {'clean/my-notes.txt': 'notes\n', 'clean/team-photo-list.md': 'photos\n', 'clean/plain.txt': 'plain\n'},
    ),
)
