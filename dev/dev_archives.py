"""Development-only archive fixtures (roadmap category 'archives', empty until batch 7).

Created archives are graded on their contents, never their bytes: `fast12_runner.describe_archive`
reduces a staged tar, tar.gz or gzip to its sorted member names and content hashes, and `archive()`
below builds the same description for the expected side. Fixtures that ship an archive use a plain
ustar file, which is ASCII apart from NUL padding and so fits the text-only fixture format.
"""
import dataclasses
import hashlib
import io
import re
import tarfile

from dev import dev_workspace
from dev.dev_workspace import Task


def _sha8(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:8]


def archive(kind, members):
    """Expected staged value for an archive holding `members` (path -> text)."""
    return f"<{kind}: {', '.join(f'{p}={_sha8(t)}' for p, t in sorted(members.items()))}>"


def _flat(value):
    """`<tar.gz: d/a=h, d/b=h>` and `<tar.gz: a=h, b=h>` are the same archive for grading: "pack the
    d/ folder" may fairly keep or drop the folder name inside. A single top folder shared by every
    member is dropped; mixed layouts (some members under it, some not) are left as they are."""
    m = re.fullmatch(r'<(tar(?:\.gz)?): (.*)>', value) if isinstance(value, str) else None
    if not m or not m.group(2):
        return value
    members = m.group(2).split(', ')
    tops = {e.split('/', 1)[0] if '/' in e.split('=', 1)[0] else None for e in members}
    if len(tops) != 1 or None in tops:
        return value
    return f"<{m.group(1)}: {', '.join(sorted(e.split('/', 1)[1] for e in members))}>"


def grade(task, *, changes, **rest):
    flat = {path: _flat(v) for path, v in task.changes.items()}
    return dev_workspace.grade(dataclasses.replace(task, changes=flat),
                               changes={path: _flat(v) for path, v in changes.items()}, **rest)


def gzipped(text):
    return f'<gzip: {_sha8(text)}>'


def tar_fixture(members):
    """A deterministic plain ustar archive as fixture text (fixed mtime, owner and mode)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for path, text in members.items():
            data = text.encode('ascii')
            info = tarfile.TarInfo(path)
            info.size, info.mtime, info.mode = len(data), 1_700_000_000, 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue().decode('ascii')


_BUNDLE = {'docs/guide.txt': 'Start with the blue cable.\n', 'docs/legal.txt': 'Licensed for venue use.\n',
           'parts.csv': 'part,count\nclip,12\n'}
_MANUALS = {'docs/guide.txt': 'Start with the blue cable.\n', 'docs/safety.txt': 'Unplug before cleaning.\n'}
_RELEASE = {'install.txt': 'Run setup once.\n', 'notes.txt': 'Fixes the date picker.\n'}
_SETTINGS = {'config.ini': 'volume=9\n', 'colors.ini': 'accent=teal\n'}
_SITE_BACKUP = {'site/index.html': '<h1>Welcome</h1>\n', 'site/about.html': '<p>Since 1998</p>\n'}
_KIT = {'kit/brush.txt': 'Round brush, size 4.\n', 'kit/paper.txt': 'Cold-press, 300gsm.\n'}

TASKS = (
    Task(
        'pack_folder_without_temp_files',
        'Pack the notes/ folder into notes.tar.gz here, leaving out any .tmp files. Keep notes/ as it is.',
        {'notes/monday.txt': 'Call the printer.\n', 'notes/tuesday.txt': 'Book the hall.\n',
         'notes/scratch.tmp': 'half a thought\n', 'notes/later/wednesday.txt': 'Order chairs.\n'},
        ("run\ntar -czf notes.tar.gz --exclude='*.tmp' notes", 'run\ntar -tzf notes.tar.gz',
         'done\nCreated notes.tar.gz with the three notes; scratch.tmp was left out.'),
        {'notes.tar.gz': archive('tar.gz', {'notes/monday.txt': 'Call the printer.\n',
                                            'notes/tuesday.txt': 'Book the hall.\n',
                                            'notes/later/wednesday.txt': 'Order chairs.\n'})},
    ),
    Task(
        'list_archive_contents',
        'Which files are inside bundle.tar? Do not extract it.',
        {'bundle.tar': tar_fixture(_BUNDLE)},
        ('run\ntar -tf bundle.tar',
         'done\nbundle.tar holds docs/guide.txt, docs/legal.txt and parts.csv.'),
        facts=(r'guide\.txt', r'legal\.txt', r'parts\.csv'),
        evidence=(r'docs/guide\.txt', r'parts\.csv'),
    ),
    Task(
        'extract_single_member',
        'From manuals.tar, take only docs/guide.txt and save it here as guide.txt. Do not unpack anything else.',
        {'manuals.tar': tar_fixture(_MANUALS), 'README': 'Manual bundles.\n'},
        ('run\ntar -tf manuals.tar', 'run\ntar -xOf manuals.tar docs/guide.txt > guide.txt',
         'tool fs.read\npath: guide.txt', 'done\nSaved docs/guide.txt from the archive as guide.txt.'),
        {'guide.txt': 'Start with the blue cable.\n'},
    ),
    Task(
        'unpack_into_new_folder',
        'Unpack release.tar into a new folder called unpacked/.',
        {'release.tar': tar_fixture(_RELEASE)},
        ('run\nmkdir unpacked && tar -xf release.tar -C unpacked', 'tool fs.list\npath: unpacked',
         'done\nUnpacked install.txt and notes.txt into unpacked/.'),
        {'unpacked': '<dir added>', 'unpacked/install.txt': 'Run setup once.\n',
         'unpacked/notes.txt': 'Fixes the date picker.\n'},
    ),
    Task(
        'unpack_without_overwriting',
        'Unpack settings.tar here, but do not overwrite any file that already exists.',
        {'settings.tar': tar_fixture(_SETTINGS), 'config.ini': 'volume=3\n'},
        ('run\ntar -tf settings.tar', 'run\ntar --skip-old-files -xf settings.tar',
         'tool fs.read\npath: config.ini',
         'done\nUnpacked colors.ini; config.ini already existed and was kept as it was.'),
        {'colors.ini': 'accent=teal\n'},
    ),
    Task(
        'gzip_keeping_original',
        'Compress server.log with gzip, and keep the uncompressed server.log too.',
        {'server.log': '09:00 start\n09:05 ready\n09:40 stop\n'},
        ('run\ngzip -k server.log', 'run\nls -1', 'done\nCreated server.log.gz; server.log is still there.'),
        {'server.log.gz': gzipped('09:00 start\n09:05 ready\n09:40 stop\n')},
    ),
    Task(
        'archive_only_final_reports',
        'Put every report in reports/ whose first line is "STATUS: final" into final-reports.tar.gz. '
        'Leave the other reports out, and keep all of them in reports/.',
        {'reports/north.txt': 'STATUS: final\nVisitors: 410\n', 'reports/south.txt': 'STATUS: draft\nVisitors: 95\n',
         'reports/east.txt': 'STATUS: final\nVisitors: 228\n'},
        ('run\nhead -n 1 reports/*.txt',
         'run\ntar -czf final-reports.tar.gz reports/north.txt reports/east.txt',
         'run\ntar -tzf final-reports.tar.gz',
         'done\nfinal-reports.tar.gz holds north.txt and east.txt; south.txt is a draft and was left out.'),
        {'final-reports.tar.gz': archive('tar.gz', {'reports/north.txt': 'STATUS: final\nVisitors: 410\n',
                                                    'reports/east.txt': 'STATUS: final\nVisitors: 228\n'})},
    ),
    Task(
        'archive_then_remove_folder',
        'Pack the old-logs/ folder into old-logs.tar.gz, then delete the old-logs/ folder.',
        {'old-logs/march.log': 'march quiet\n', 'old-logs/april.log': 'april busy\n'},
        ('run\ntar -czf old-logs.tar.gz old-logs && rm -r old-logs',
         'done\nCreated old-logs.tar.gz; deleting old-logs/ is staged and pending your approval.'),
        {'old-logs.tar.gz': archive('tar.gz', {'old-logs/march.log': 'march quiet\n',
                                               'old-logs/april.log': 'april busy\n'}),
         'old-logs': None, 'old-logs/march.log': None, 'old-logs/april.log': None},
        policy_end='pending',
    ),
    Task(
        'compare_backup_to_folder',
        'Does backup.tar still match the site/ folder? Tell me which file differs, without changing anything.',
        {'backup.tar': tar_fixture(_SITE_BACKUP), 'site/index.html': '<h1>Welcome back</h1>\n',
         'site/about.html': '<p>Since 1998</p>\n'},
        ('run\nfor f in site/index.html site/about.html; do tar -xOf backup.tar "$f" | cmp -s - "$f" '
         '&& echo "$f same" || echo "$f differs"; done',
         'done\nOnly site/index.html differs from the backup; site/about.html matches.'),
        facts=(r'index\.html',),
        evidence=(r'index\.html differs',),
        contradicts=r'about\.html[^.\n]{0,20}\b(?:differs|changed|different)\b|\b(?:all|everything)\s+match',
    ),
    Task(
        'add_file_to_existing_tar',
        'Add kit/easel.txt to the existing kit.tar, keeping everything already in it.',
        {'kit.tar': tar_fixture(_KIT), 'kit/easel.txt': 'Folding easel, beech.\n',
         'kit/brush.txt': 'Round brush, size 4.\n', 'kit/paper.txt': 'Cold-press, 300gsm.\n'},
        ('run\ntar -rf kit.tar kit/easel.txt', 'run\ntar -tf kit.tar',
         'done\nkit.tar now holds brush.txt, paper.txt and easel.txt.'),
        {'kit.tar': archive('tar', {**_KIT, 'kit/easel.txt': 'Folding easel, beech.\n'})},
    ),
)
