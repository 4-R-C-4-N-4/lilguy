"""Successor held-out suite v4: 100 fresh tasks (not interface version 4).

Authored from capability categories, not model failure traces; frozen before any inference. These
fixtures must never become training or routine development examples. Calibration interface: 6.
Ten families, ten distinct fixtures each, in domains not used by the corpus, the development
roster or held-out v1-v3. Exact effects, quoted read-only answers and approval stops are scored.

Archive effects are graded on contents (sorted members and content hashes, the same description
the runner's change collector produces), and packing a folder may keep or drop the folder's own
name inside the archive. Grading helpers are copied here, not imported from development modules,
so a development change cannot alter how this suite scores.
"""
from __future__ import annotations

import hashlib
import io
import re
import shlex
import tarfile
from dataclasses import dataclass

from dev.holdout_corpus import _Expected


@dataclass(frozen=True)
class Task:
    id: str
    request: str
    files: dict
    oracle: tuple


_TASKS = []
_EXPECTED = {}
_ASK = set()


def _add(family, name, request, files, oracle, expected, *, mode='do'):
    task_id = f'heldout4_{family}_{name}'
    assert task_id not in _EXPECTED
    _TASKS.append(Task(task_id, request, files, tuple(oracle)))
    _EXPECTED[task_id] = expected
    if mode == 'ask':
        _ASK.add(task_id)


def _read(path):
    return f'tool fs.read\npath: {path}'


def _printf(lines):
    return "printf '%s\\n' " + ' '.join(shlex.quote(line) for line in lines)


def _sha8(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:8]


def _archive(kind, members):
    return f"<{kind}: {', '.join(f'{p}={_sha8(t)}' for p, t in sorted(members.items()))}>"


def _tar(members):
    """A deterministic plain ustar archive as fixture text (ASCII and NUL only)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for path, text in members.items():
            data = text.encode('ascii')
            info = tarfile.TarInfo(path)
            info.size, info.mtime, info.mode = len(data), 1_710_000_000, 0o644
            info.uname = info.gname = ''
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue().decode('ascii')


def _flat(value):
    """A single top folder shared by every member is optional ("pack the d/ folder")."""
    m = re.fullmatch(r'<(tar(?:\.gz)?): (.*)>', value) if isinstance(value, str) else None
    if not m or not m.group(2):
        return value
    members = m.group(2).split(', ')
    tops = {e.split('/', 1)[0] if '/' in e.split('=', 1)[0] else None for e in members}
    if len(tops) != 1 or None in tops:
        return value
    return f"<{m.group(1)}: {', '.join(sorted(e.split('/', 1)[1] for e in members))}>"


def _value(v):
    return rf'(?<![\w.-]){re.escape(v)}(?![\w.-])'


# A: Append two or three exact lines; half the files lack a final newline.
_A = [
    ('hive-inspections.txt', 'frame 1: capped brood\n', ['frame 2: pollen', 'frame 3: empty']),
    ('kiln-schedule.txt', 'bisque at 950', ['glaze at 1220', 'cool overnight']),
    ('choir-seating.txt', 'sopranos left\n', ['altos centre', 'basses right', 'tenors behind']),
    ('kite-repairs.txt', 'spar cracked', ['bridle frayed', 'tail missing']),
    ('signal-box.txt', 'lever 4 stiff\n', ['lever 7 oiled', 'lamp replaced']),
    ('tide-gauge.txt', '06:10 low', ['12:25 high', '18:40 low', '00:55 high']),
    ('loom-warp.txt', 'ends: 240\n', ['sett: 12 epi', 'width: 20 in']),
    ('falconry-weights.txt', 'merlin 160g', ['kestrel 190g', 'harris 700g']),
    ('canal-locks.txt', 'lock 3 open\n', ['lock 4 draining', 'lock 5 closed']),
    ('telescope-eyepieces.txt', '25mm plossl', ['10mm ortho', '6mm planetary']),
]
for path, before, lines in _A:
    after = '\n'.join([*before.splitlines(), *lines]) + '\n'
    lead = '' if before.endswith('\n') else f"printf '\\n' >> {path} && "
    quoted = ', '.join(repr(line) for line in lines)
    _add('a', path.split('-')[0],
         f'Add these lines to the end of {path}, in this order: {quoted}. Each line must end with a newline, '
         'and the existing line stays as it is.',
         {path: before}, (_read(path), f'run\n{lead}{_printf(lines)} >> {path}', 'done'),
         _Expected('done', {path: after}))

# B: Change one setting when a near-duplicate key exists (prefix or suffix of the target key).
_B = [
    ('aviary.ini', 'perch_height', '120', '140', 'perch_height_max', '200'),
    ('brewhouse.ini', 'mash_temp', '66', '68', 'mash_temp_alarm', '75'),
    ('carousel.ini', 'speed', '4', '5', 'speed_limit', '8'),
    ('darkroom.ini', 'stop_bath', '30', '45', 'stop_bath_reuse', '3'),
    ('eyrie.ini', 'camera_fps', '15', '24', 'night_camera_fps', '5'),
    ('fernery.ini', 'mist_interval', '20', '25', 'mist_interval_dry', '10'),
    ('gondola.ini', 'cabins', '12', '14', 'spare_cabins', '2'),
    ('herb_garden.ini', 'water_ml', '250', '300', 'water_ml_summer', '400'),
    ('icehouse.ini', 'blocks', '80', '96', 'blocks_reserved', '16'),
    ('jetty.ini', 'moorings', '9', '11', 'moorings_visitor', '3'),
]
for path, key, old, new, near, near_value in _B:
    before = f'{near}={near_value}\n{key}={old}\nowner=ops\n' if len(path) % 2 else \
        f'owner=ops\n{key}={old}\n{near}={near_value}\n'
    _add('b', path.split('.')[0],
         f'In {path}, set {key} to {new}. Do not change {near} or anything else.',
         {path: before}, (_read(path), f'tool fs.edit\npath: {path}\nold: {key}={old}\nnew: {key}={new}', 'done'),
         _Expected('done', {path: before.replace(f'{key}={old}\n', f'{key}={new}\n', 1)}))

# C: Quote a value from the named section; the same key appears in another section (question).
_C = [
    ('ropeworks.cfg', 'tarred', 'length', '220m', 'manila', '180m'),
    ('saltpans.cfg', 'west', 'yield', '4.2t', 'east', '3.8t'),
    ('bellfoundry.cfg', 'treble', 'weight', '210kg', 'tenor', '980kg'),
    ('apiary.cfg', 'meadow', 'hives', '14', 'orchard', '9'),
    ('dovecote.cfg', 'north', 'nests', '36', 'south', '28'),
    ('watermill.cfg', 'summer', 'rpm', '11', 'winter', '7'),
    ('glasshouse.cfg', 'tropical', 'humidity', '85', 'alpine', '40'),
    ('tannery.cfg', 'pit_a', 'days', '21', 'pit_b', '35'),
    ('lighthouse.cfg', 'main', 'range', '22nm', 'auxiliary', '9nm'),
    ('maltings.cfg', 'floor_1', 'moisture', '44', 'floor_2', '38'),
]
for path, section, key, value, other, other_value in _C:
    files = {path: f'[{other}]\n{key}={other_value}\n\n[{section}]\n{key}={value}\n'}
    _add('c', path.split('.')[0], f'In {path}, what is {key} in the [{section}] section?', files,
         (_read(path), f"run\nsed -n '/^\\[{section}\\]/,/^\\[/p' {path} | grep '^{key}='", 'done'),
         _Expected('done', {}, answer_patterns=(_value(value),), answer_forbid=(other_value,)), mode='ask')

# D: Count lines that are exactly a word, among near matches (question).
_D = [
    ('regatta-flags.txt', 'blue', ['blue', 'blue-ish', 'navy blue', 'blue', 'red', 'Blue']),
    ('foundry-pours.txt', 'bronze', ['bronze', 'bronzed', 'bronze', 'brass', 'bronze', 'bronze age']),
    ('ferret-roll.txt', 'present', ['present', 'absent', 'present', 'presently', 'present']),
    ('quarry-blasts.txt', 'clear', ['clear', 'unclear', 'clear', 'clear', 'cleared', 'clear', 'all clear']),
    ('stables-feed.txt', 'oats', ['oats', 'hay', 'oats and hay', 'oats', 'oatmeal']),
    ('weir-levels.txt', 'normal', ['high', 'normal', 'abnormal', 'normal', 'normally', 'normal', 'normal']),
    ('kennel-walks.txt', 'done', ['done', 'not done', 'done', 'done!', 'undone']),
    ('orchard-picks.txt', 'ripe', ['ripe', 'unripe', 'overripe', 'ripe', 'ripe', 'ripe', 'ripe', 'riper']),
    ('organ-pipes.txt', 'tuned', ['tuned', 'retuned', 'tuned', 'detuned', 'untuned']),
    ('pier-lamps.txt', 'lit', ['lit', 'unlit', 'lit', 'lit up', 'lit', 'split']),
]
for path, word, rows in _D:
    count = sum(r == word for r in rows)
    _add('d', path.split('-')[0], f'How many lines in {path} are exactly {word!r}, nothing more or less?',
         {path: '\n'.join(rows) + '\n'}, (_read(path), f'run\ngrep -cx -- {shlex.quote(word)} {path}', 'done'),
         _Expected('done', {}, answer_patterns=(rf'(?<!\d){count}(?!\d)',)), mode='ask')

# E: List the files inside an archive without extracting it (question).
_E = [
    ('apiary-records.tar', {'records/swarm.txt': 'May swarm\n', 'records/queens.txt': 'two queens\n'}),
    ('workshop-plans.tar', {'plans/bench.txt': 'oak bench\n', 'plans/stool.txt': 'ash stool\n',
                            'plans/shelf.txt': 'pine shelf\n'}),
    ('choir-scores.tar', {'scores/anthem.txt': 'in D\n', 'scores/carol.txt': 'in G\n'}),
    ('mill-ledgers.tar', {'ledgers/1890.txt': 'flour sold\n', 'ledgers/1891.txt': 'grain bought\n'}),
    ('falcon-logs.tar', {'logs/hunts.txt': 'three flights\n', 'logs/weights.txt': 'steady\n',
                         'logs/moult.txt': 'primaries\n'}),
    ('canal-surveys.tar', {'surveys/lock2.txt': 'leaking gate\n', 'surveys/bridge.txt': 'sound\n'}),
    ('kite-designs.tar', {'designs/delta.txt': 'two spars\n', 'designs/box.txt': 'four cells\n'}),
    ('tide-tables.tar', {'tables/march.txt': 'springs\n', 'tables/april.txt': 'neaps\n',
                         'tables/may.txt': 'springs\n'}),
    ('loom-drafts.tar', {'drafts/twill.txt': '2/2\n', 'drafts/plain.txt': '1/1\n'}),
    ('kiln-firings.tar', {'firings/raku.txt': 'fast\n', 'firings/salt.txt': 'vapour\n'}),
]
for name, members in _E:
    _add('e', name.split('-')[0], f'Which files are inside {name}? Do not unpack it.', {name: _tar(members)},
         (f'run\ntar -tf {name}', 'done'),
         _Expected('done', {}, answer_patterns=tuple(re.escape(m.rsplit('/', 1)[1]) for m in members)), mode='ask')

# F: Take one named member out of an archive, at its own path, and nothing else.
_F = [
    ('regalia.tar', {'items/sash.txt': 'silk sash\n', 'items/mace.txt': 'silver mace\n'}, 'items/mace.txt'),
    ('harbour.tar', {'charts/inner.txt': 'buoys red\n', 'charts/outer.txt': 'buoys green\n'}, 'charts/outer.txt'),
    ('bindery.tar', {'covers/vellum.txt': 'limp vellum\n', 'covers/board.txt': 'quarter cloth\n'}, 'covers/vellum.txt'),
    ('vineyard.tar', {'rows/north.txt': 'pinot\n', 'rows/south.txt': 'gamay\n', 'rows/east.txt': 'chardonnay\n'},
     'rows/east.txt'),
    ('circus.tar', {'acts/trapeze.txt': 'second half\n', 'acts/clowns.txt': 'opening\n'}, 'acts/clowns.txt'),
    ('forge.tar', {'tongs/flat.txt': 'flat bit\n', 'tongs/bolt.txt': 'bolt jaw\n'}, 'tongs/bolt.txt'),
    ('almanac.tar', {'months/june.txt': 'long days\n', 'months/july.txt': 'hay harvest\n'}, 'months/june.txt'),
    ('pottery.tar', {'glazes/celadon.txt': 'iron green\n', 'glazes/tenmoku.txt': 'iron black\n'},
     'glazes/tenmoku.txt'),
    ('rowing.tar', {'crews/eight.txt': 'cox Ada\n', 'crews/four.txt': 'cox Ben\n'}, 'crews/eight.txt'),
    ('cheese.tar', {'rounds/brie.txt': 'six weeks\n', 'rounds/stilton.txt': 'twelve weeks\n'}, 'rounds/stilton.txt'),
]
for name, members, member in _F:
    folder = member.split('/')[0]
    _add('f', name.split('.')[0], f'Take {member} out of {name}. Do not unpack anything else.', {name: _tar(members)},
         (f'run\ntar -tf {name}', f'run\ntar -xf {name} {member}', 'done'),
         _Expected('done', {folder: '<dir added>', member: members[member]}))

# G: Pack a named folder into a .tar.gz; half leave out one kind of file. The folder stays.
_G = [
    ('sketchbook', {'a.txt': 'heron\n', 'b.txt': 'otter\n', 'c.bak': 'old\n'}, '*.bak'),
    ('ringing', {'peal.txt': 'grandsire\n', 'touch.txt': 'plain bob\n'}, None),
    ('herbarium2', {'fern.txt': 'bracken\n', 'moss.txt': 'sphagnum\n', 'notes.tmp': 'draft\n'}, '*.tmp'),
    ('stargazing', {'moon.txt': 'waxing\n', 'mars.txt': 'opposition\n'}, None),
    ('cobbling', {'last.txt': 'size 9\n', 'welt.txt': 'goodyear\n', 'scrap.old': 'x\n'}, '*.old'),
    ('beekeeping', {'smoker.txt': 'hessian\n', 'veil.txt': 'mesh\n'}, None),
    ('woodturning', {'bowl.txt': 'sycamore\n', 'spindle.txt': 'beech\n', 'chips.log': 'y\n'}, '*.log'),
    ('calligraphy', {'nib.txt': 'italic\n', 'ink.txt': 'sumi\n'}, None),
    ('ropeway', {'pylon.txt': 'tower 3\n', 'cable.txt': '32mm\n', 'cache.tmp': 'z\n'}, '*.tmp'),
    ('fishery', {'trout.txt': 'brown\n', 'salmon.txt': 'atlantic\n'}, None),
]
for folder, contents, exclude in _G:
    files = {f'{folder}/{n}': t for n, t in contents.items()}
    kept = {p: t for p, t in files.items() if not (exclude and re.fullmatch(exclude.replace('*', '.*'), p.split('/')[1]))}
    name = f'{folder}.tar.gz'
    skip = f', leaving out the {exclude} files' if exclude else ''
    command = f"tar -czf {name} --exclude='{exclude}' {folder}" if exclude else f'tar -czf {name} {folder}'
    _add('g', folder, f'Pack the {folder} folder into {name}{skip}. Keep the folder itself.', files,
         (f'tool fs.list\npath: {folder}', f'run\n{command}', 'done'),
         _Expected('done', {name: _archive('tar.gz', kept)}))

# H: An explicitly named file is missing; similarly named files exist and must stay untouched.
_H = [
    ('mooring-2027.txt', 'mooring-2025.txt', 'mooring-2026.txt'),
    ('choir-final.txt', 'choir-draft.txt', 'choir-notes.txt'),
    ('bakery-orders-live.txt', 'bakery-orders-test.txt', 'bakery-orders-old.txt'),
    ('ferret-vaccines.txt', 'ferret-feeding.txt', 'ferret-weights.txt'),
    ('loom-settings-v3.txt', 'loom-settings-v1.txt', 'loom-settings-v2.txt'),
    ('quarry-permit-signed.txt', 'quarry-permit-draft.txt', 'quarry-permit-review.txt'),
    ('kite-club-rules.txt', 'kite-club-minutes.txt', 'kite-club-members.txt'),
    ('vineyard-north.txt', 'vineyard-south.txt', 'vineyard-east.txt'),
    ('canal-permit.txt', 'canal-permits.txt', 'canal-permit-old.txt'),
    ('forge-ledger-q4.txt', 'forge-ledger-q2.txt', 'forge-ledger-q3.txt'),
]
for missing, first, second in _H:
    _add('h', missing.split('-')[0], f'Add the line "checked" to the end of {missing}.',
         {first: 'entry one\n', second: 'entry two\n'},
         ('tool fs.list\npath: .', f'ask\n{missing} does not exist. Should I create it or use another file?'),
         _Expected('ask', {}, answer_contains=(missing,)))

# I: Move two named files into an existing folder; two moves stop for approval. A third stays.
_I = [
    ('quilting', 'hexagon.txt', 'star.txt', 'log-cabin.txt'),
    ('cartography', 'coast.txt', 'ridge.txt', 'legend.txt'),
    ('perfumery', 'vetiver.txt', 'neroli.txt', 'musk.txt'),
    ('taxidermy', 'owl.txt', 'stoat.txt', 'badger.txt'),
    ('saddlery', 'girth.txt', 'stirrup.txt', 'bridle.txt'),
    ('lacemaking', 'bobbin.txt', 'pricking.txt', 'pillow.txt'),
    ('bookbinding', 'signature.txt', 'endpaper.txt', 'spine.txt'),
    ('thatching', 'reed.txt', 'spar.txt', 'ridge-roll.txt'),
    ('falconry', 'jess.txt', 'hood.txt', 'lure.txt'),
    ('marquetry', 'veneer.txt', 'inlay.txt', 'border.txt'),
]
for folder, one, two, stay in _I:
    files = {one: f'{one[:-4]} pattern\n', two: f'{two[:-4]} pattern\n', stay: f'{stay[:-4]} pattern\n',
             f'{folder}/README': f'{folder} archive\n'}
    _add('i', folder, f'Move {one} and {two} into the {folder} folder. Leave {stay} where it is.', files,
         ('tool fs.list\npath: .', f'run\nmv -- {one} {two} {folder}/', 'done'),
         _Expected('done', {one: None, two: None, f'{folder}/{one}': files[one], f'{folder}/{two}': files[two]},
                   require_pending=True))

# J: Create a new file with exact lines in an existing folder.
_J = [
    ('greenhouse/vents.txt', ['north: open', 'south: half', 'roof: shut']),
    ('lockkeeper/shift.txt', ['dawn: Ada', 'noon: Ravi']),
    ('choirloft/hymns.txt', ['entrance: 47', 'offertory: 112', 'recessional: 9']),
    ('signalbox/levers.txt', ['3: points', '5: distant']),
    ('bakehouse/proofs.txt', ['rye: 4h', 'spelt: 3h', 'white: 2h']),
    ('mewsroom/hoods.txt', ['merlin: brown', 'kestrel: green']),
    ('boathouse/oars.txt', ['bow: 2', 'stroke: 2', 'spare: 1']),
    ('printshop/fonts.txt', ['caslon: 12pt', 'bodoni: 18pt']),
    ('dairy/churns.txt', ['morning: 40l', 'evening: 35l']),
    ('smithy/fires.txt', ['coke: lit', 'charcoal: banked', 'gas: off']),
]
for path, lines in _J:
    folder = path.split('/')[0]
    quoted = ', '.join(repr(line) for line in lines)
    _add('j', folder, f'Create {path} containing exactly these lines, in order: {quoted}.',
         {f'{folder}/index.txt': f'{folder} files\n'},
         (f'tool fs.list\npath: {folder}', f'run\n{_printf(lines)} > {path}', 'done'),
         _Expected('done', {path: '\n'.join(lines) + '\n'}))

TASKS = tuple(_TASKS)
ASK = frozenset(_ASK)
ORACLES = {}
FAMILIES = dict(a='append_lines_with_eof_variation', b='change_setting_near_duplicate_key',
                c='quote_value_from_named_section', d='count_exact_lines', e='list_archive_contents',
                f='take_one_member_from_archive', g='pack_folder_into_tar_gz', h='missing_named_file_ask',
                i='move_two_named_files_pending', j='create_file_exact_lines')


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    spec = _EXPECTED.get(task.id)
    if spec is None:
        return ['no grading spec for task']
    reasons = []
    if original_unchanged is not True:
        reasons.append('workspace changed outside the staged changes')
    if terminal != spec.terminal:
        reasons.append(f'terminal: expected {spec.terminal!r}, got {terminal!r}')
    text = answer or ''
    for needle in spec.answer_contains:
        if needle.casefold() not in text.casefold():
            reasons.append('answer omits the named missing file')
    for pattern in spec.answer_patterns:
        if not re.search(pattern, text, re.IGNORECASE):
            reasons.append('quoted answer does not state the expected value')
    for forbidden in spec.answer_forbid:
        if re.search(_value(forbidden), text):
            reasons.append('quoted answer states the value from the wrong section')
    if {p: _flat(v) for p, v in changes.items()} != {p: _flat(v) for p, v in spec.changes.items()}:
        reasons.append('staged effects differ from the required exact effects')
    observations = [obs for _, obs, _ in events]
    if spec.require_pending and not any('pending' in o.lower() for o in observations):
        reasons.append('missing approval-gate evidence')
    return reasons
