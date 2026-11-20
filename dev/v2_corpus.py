"""Corpus v2: parameterized, replay-verified interface-v1 training episodes (roadmap step 6).

Every example is a template instance: an original fixture, a request, a scripted oracle in
canonical v1 form, and the exact effects, policy ending, error turns and grounded facts a correct
episode must show. An example becomes training data only if

  1. the oracle, run against a fresh guarded fixture, meets every declared expectation (gold);
  2. a second fresh fixture replaying the recorded actions yields an identical record (replay);
  3. it survives exact and near-duplicate removal within the corpus and against development;
  4. the whole corpus passes the frozen held-out split gate (leakage).

Shell patterns credited to tldr-pages are adapted from the pinned revision below (CC BY 4.0);
requests, fixture bytes, answers and multi-turn structure are original. Nothing is fetched or
executed outside the guarded sandbox, and no personal shell history is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import random
import re
import tarfile
import tempfile

from dev import episodes, eval_gate, fast12_runner, split_audit
from dev.broad_runner import development_rows
from lilguy import loop, protocol

TLDR_REVISION = '2d64595223d89a23d249fed57d8f401d95f8ccf9'
TLDR_PROJECT = f'https://github.com/tldr-pages/tldr/tree/{TLDR_REVISION}'
TLDR_CREDIT = 'tldr-pages team and contributors'
TLDR_LICENCE = 'https://creativecommons.org/licenses/by/4.0/'
ROOT = Path(__file__).resolve().parents[1]
CORPUS_VERSION = 2
DEFAULT_SEED = 20261119
_REV = 1  # generator revision being produced; set by generate(), read by revision-gated families
CATEGORIES = ('inspect', 'edit', 'organise', 'delete', 'permissions', 'archives', 'scripts',
              'ask', 'recovery', 'read-only')
_HEADER = re.compile(r'^(stdout|stderr) \(\d+ lines?\):$')


@dataclass(frozen=True)
class Example:
    id: str
    family: str
    category: str
    behaviour: str
    request: str
    files: dict
    oracle: tuple
    changes: dict
    terminal: str = 'done'
    error_turns: tuple = ()
    policy_end: str = 'ok'
    facts: tuple = ()
    source_page: str | None = None
    # Indices of assistant actions that are deliberate, reasonable-looking slips (for example acting
    # before looking) kept only so the recovery after them is real; they are never training targets.
    train_skip: tuple = ()
    meta: dict = field(default_factory=dict, compare=False, hash=False)

    def manifest(self):
        return dict(id=self.id, template_id='v2-' + self.family, split='train',
                    request=self.request, files=self.files)

    def provenance(self):
        if self.source_page is None:
            return {'origin': 'original lilguy fixture'}
        return {'source': f'{TLDR_PROJECT}/pages/common/{self.source_page}.md', 'revision': TLDR_REVISION,
                'credit': TLDR_CREDIT, 'licence': TLDR_LICENCE,
                'changes': 'Adapted usage to a new request, fixture, output and multi-turn protocol.'}


# --- canonical actions ----------------------------------------------------------------------

_TOOLS = None


def _tools():
    global _TOOLS
    if _TOOLS is None:
        _TOOLS = protocol.load_tools()
    return _TOOLS


def _canon(line):
    tools = _tools()
    return protocol.render_action(protocol.parse_action(line, tools), tools)


def run(command):
    return 'run\n' + command


def read(path):
    return f'tool fs.read\npath: {path}'


def ls(path='.'):
    return f'tool fs.list\npath: {path}'


def find(glob, path='.', kind=None):
    lines = ['tool fs.find']
    if path != '.':
        lines.append(f'path: {path}')
    lines.append(f'name_glob: {glob}')
    if kind:
        lines.append(f'type: {kind}')
    return '\n'.join(lines)


def grep(pattern, path='.', filenames_only=False):
    lines = ['tool fs.grep', f'pattern: {pattern}']
    if path != '.':
        lines.append(f'path: {path}')
    if filenames_only:
        lines.append('filenames_only: true')
    return '\n'.join(lines)


def edit(path, old, new):
    return f'tool fs.edit\npath: {path}\nold: {old}\nnew: {new}'


def done(text):
    return 'done\n' + text


def ask(text):
    return 'ask\n' + text


# --- word pools (original) ------------------------------------------------------------------

PLACES = ('orchard', 'harbor', 'lantern', 'meadow', 'quarry', 'canyon', 'glacier', 'pavilion', 'foundry',
          'atelier', 'bakery', 'garage', 'library', 'studio', 'kiosk', 'dockyard', 'greenhouse', 'vineyard',
          'workshop', 'apiary', 'brewery', 'gallery', 'theatre', 'museum', 'arcade', 'market', 'station',
          'clinic', 'ranch', 'marina', 'chapel', 'cellar', 'depot', 'hangar', 'lodge', 'mill', 'plaza',
          'tannery', 'smithy', 'ferry', 'aviary', 'boathouse', 'cannery', 'distillery', 'pantry', 'quay',
          'rookery', 'sawmill', 'terrace', 'warehouse', 'kitchen', 'bistro', 'cinema', 'campus', 'chalet',
          'citadel', 'conservatory', 'dairy', 'forge', 'granary', 'hostel', 'lighthouse', 'nursery',
          'outpost', 'pier', 'refinery', 'sanctuary', 'stable', 'tower', 'villa', 'wharf', 'yard', 'zoo',
          'archive', 'bazaar', 'cabin', 'deck', 'estate', 'farm', 'grove', 'hub', 'inn', 'jetty', 'keep')
THINGS = ('invoice', 'roster', 'playlist', 'recipe', 'ledger', 'itinerary', 'catalog', 'manifest', 'agenda',
          'glossary', 'checklist', 'timetable', 'inventory', 'syllabus', 'briefing', 'register', 'logbook',
          'menu', 'programme', 'bulletin', 'digest', 'census', 'tally', 'docket', 'dossier', 'portfolio',
          'almanac', 'atlas', 'charter', 'chronicle', 'directory', 'gazette', 'handbook', 'index', 'journal',
          'memo', 'notebook', 'planner', 'ration', 'schedule')
KEYS = ('timeout', 'retries', 'port', 'workers', 'threshold', 'interval', 'batch_size', 'max_users',
        'cache_ttl', 'log_level', 'region', 'theme', 'language', 'owner', 'channel', 'priority', 'quota',
        'mode', 'colour', 'font_size', 'backlog', 'depth', 'margin', 'volume', 'width', 'height', 'speed',
        'limit', 'window', 'pool_size')
WORDS = ('amber', 'basil', 'cedar', 'dahlia', 'ember', 'fennel', 'garnet', 'hazel', 'indigo', 'juniper',
         'kestrel', 'lilac', 'maple', 'nutmeg', 'olive', 'pepper', 'quince', 'russet', 'saffron', 'thyme',
         'umber', 'violet', 'willow', 'yarrow', 'zinnia', 'acorn', 'birch', 'clover', 'daisy', 'elm',
         'fig', 'ginger', 'heather', 'iris', 'jasmine', 'kale', 'lemon', 'mint', 'nectar', 'oak', 'plum',
         'rose', 'sage', 'tulip', 'walnut', 'aster', 'bramble', 'cobalt', 'dune', 'flint', 'gravel',
         'harvest', 'ivory', 'jade', 'lagoon', 'marble', 'onyx', 'pebble', 'quartz', 'reef', 'slate',
         'topaz', 'velvet', 'wren', 'falcon', 'otter', 'badger', 'heron', 'lynx', 'marten', 'osprey', 'puffin',
         'raven', 'stoat', 'swift', 'tern', 'vole', 'weasel', 'bison', 'crane', 'egret', 'finch', 'gannet')
PEOPLE = ('ada', 'bruno', 'chen', 'dara', 'emil', 'fatima', 'goran', 'hana', 'ines', 'jonas', 'kaito',
          'lena', 'mateo', 'nadia', 'omar', 'priya', 'quinn', 'rosa', 'sven', 'tomas', 'uma', 'vera',
          'wim', 'xena', 'yusuf', 'zara', 'aiko', 'bjorn', 'carla', 'dmitri', 'elena', 'farid', 'greta',
          'hugo', 'ivan', 'julia', 'kofi', 'lucia', 'milan', 'noor', 'olga', 'pablo', 'rania', 'sami')
EXTS = ('log', 'csv', 'txt', 'md', 'json', 'tsv', 'ini', 'cfg', 'dat', 'lst')


class Gen:
    """Deterministic per-family draws with no repeated (pool, value) picks inside a family."""

    def __init__(self, seed, family):
        self.rng = random.Random(f'{seed}:{family}')
        self.used = set()
        self.decks = {}

    def pick(self, pool, n=1):
        if n == 1:
            # Deal without replacement; reshuffle once a pool is spent (combinations stay distinct,
            # and the dedup stage drops any accidental repeat).
            deck = self.decks.setdefault(id(pool), [])
            if not deck:
                deck.extend(self.rng.sample(pool, len(pool)))
            return deck.pop()
        for _ in range(500):
            items = tuple(self.rng.sample(pool, n))
            if items not in self.used:
                self.used.add(items)
                return items
        raise RuntimeError('pool exhausted')

    def int(self, lo, hi):
        return self.rng.randint(lo, hi)

    def choice(self, seq):
        return self.rng.choice(seq)

    def shuffle(self, seq):
        seq = list(seq)
        self.rng.shuffle(seq)
        return seq


def _lines(items):
    return ''.join(f'{x}\n' for x in items)


def _ini(pairs, section=None):
    head = f'[{section}]\n' if section else ''
    return head + ''.join(f'{k}={v}\n' for k, v in pairs)


def _value_for(g, key):
    if key in ('region', 'theme', 'language', 'owner', 'channel', 'mode', 'colour', 'log_level', 'priority'):
        return g.choice(WORDS)
    return str(g.int(2, 990))


def _other_value(g, key, value):
    for _ in range(50):
        new = _value_for(g, key)
        if new != value:
            return new
    raise RuntimeError('no distinct value')


def tar_text(members):
    """A deterministic ustar archive of ASCII members, as text (valid UTF-8: ASCII and NUL only)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, text in members.items():
            data = text.encode('ascii')
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 1700000000, 0o644
            info.uname = info.gname = ''
            archive.addfile(info, io.BytesIO(data))
    return buf.getvalue().decode('ascii')


# --- families ---------------------------------------------------------------------------------

def fam_read_value(g, n):
    asks = ('What is {key} set to in {path}?', 'Tell me the {key} value in {path}.',
            'Which {key} does {path} use?', 'Look up {key} in {path} for me.')
    for i in range(n):
        place = g.pick(PLACES)
        keys = g.shuffle(KEYS)[:4]
        key = keys[g.int(0, 3)]
        values = {k: _value_for(g, k) for k in keys}
        ext = g.choice(('ini', 'cfg', 'conf'))
        path = g.choice((f'{place}.{ext}', f'config/{place}.{ext}', f'etc/{place}.{ext}'))
        files = {path: _ini(values.items(), section=g.choice((None, place, 'main')))}
        if g.int(0, 1):
            files[f'README-{place}.md'] = f'# {place}\nSettings live in {path}.\n'
        value = values[key]
        yield dict(id=f'read-value-{i}', family='read_value', category='read-only', behaviour='factual-answer',
                   request=g.choice(asks).format(key=key, path=path), files=files,
                   oracle=(read(path), done(g.choice(('{key} is {value} in {path}.', '{path} sets {key}={value}.',
                                                         'The {key} setting in {path} is {value}.')).format(
                                                             key=key, value=value, path=path))),
                   changes={}, facts=(value,))


def fam_count(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        mode = i % 3
        if mode == 0:
            path = f'{place}-{thing}.txt'
            rows = [f'{g.choice(WORDS)} {g.int(1, 99)}' for _ in range(g.int(3, 14))]
            req = g.choice(('How many lines are in {path}?', 'Count the lines in {path}.',
                            'How long is {path} in lines?')).format(path=path)
            count = str(len(rows))
            yield dict(id=f'count-lines-{i}', family='count_lines', category='inspect', behaviour='factual-answer',
                       request=req, files={path: _lines(rows)}, source_page='wc',
                       oracle=(run(f'wc -l < {path}'), done(f'{path} has {count} lines.')), changes={}, facts=(count,))
        elif mode == 1:
            path = f'{place}.log'
            word = g.choice(('ERROR', 'WARN', 'retry', 'timeout', 'denied', 'queued'))
            rows, hits = [], 0
            for _ in range(g.int(5, 16)):
                if g.int(0, 2) == 0:
                    rows.append(f'{g.int(10, 23)}:{g.int(10, 59)} {word} {g.choice(WORDS)}')
                    hits += 1
                else:
                    rows.append(f'{g.int(10, 23)}:{g.int(10, 59)} ok {g.choice(WORDS)}')
            if hits == 0:
                rows.append(f'09:15 {word} {g.choice(WORDS)}')
                hits = 1
            req = g.choice(("How many lines in {path} contain '{w}'?", 'Count the {w} lines in {path}.',
                            "How many times does a line in {path} mention {w}?")).format(path=path, w=word)
            yield dict(id=f'count-matches-{i}', family='count_matches', category='inspect', behaviour='factual-answer',
                       request=req, files={path: _lines(rows)}, source_page='grep',
                       oracle=(run(f"grep -c -- '{word}' {path}"), done(f"{hits} lines in {path} contain {word}.")),
                       changes={}, facts=(str(hits),))
        else:
            ext = g.choice(EXTS)
            folder = g.choice(('data', 'inbox', 'exports', 'drafts', place))
            names = [f'{folder}/{w}.{ext}' for w in g.shuffle(WORDS)[:g.int(2, 6)]]
            noise = [f'{folder}/{w}.{g.choice([e for e in EXTS if e != ext])}' for w in g.shuffle(WORDS)[:3]]
            files = {p: f'{place} {thing}\n' for p in names + noise}
            files[f'{thing}.{ext}'] = 'outside the folder\n'
            req = g.choice(('How many .{ext} files are in {folder}/?', 'Count the .{ext} files under {folder}.',
                            'How many {ext} files does {folder}/ hold?')).format(ext=ext, folder=folder)
            listed = sorted(names)
            yield dict(id=f'count-files-{i}', family='count_files', category='inspect', behaviour='factual-answer',
                       request=req, files=files,
                       oracle=(find(f'*.{ext}', path=folder, kind='f'),
                               done(f'{len(names)} .{ext} files in {folder}/: '
                                    + ', '.join(p.split('/')[-1] for p in listed) + '.')),
                       changes={}, facts=tuple(p.split('/')[-1] for p in listed))


def fam_largest(g, n):
    for i in range(n):
        folder = g.choice(('reports', 'media', 'notes', 'dumps', g.pick(PLACES)))
        names = g.shuffle(WORDS)[:g.int(3, 5)]
        sizes = g.shuffle(range(20, 400, 7))[:len(names)]
        ext = g.choice(EXTS)
        files = {f'{folder}/{name}.{ext}': 'x' * (size - 1) + '\n' for name, size in zip(names, sizes)}
        big = max(files, key=lambda p: len(files[p]))
        size = len(files[big])
        req = g.choice(('Which file in {folder}/ is the largest?', 'What is the biggest file under {folder}?',
                        'Find the largest file in {folder} and tell me its size.')).format(folder=folder)
        yield dict(id=f'largest-{i}', family='largest_file', category='inspect', behaviour='factual-answer',
                   request=req, files=files, source_page='wc',
                   oracle=(run(f'wc -c {folder}/* | sort -n'), done(f'{big} is the largest at {size} bytes.')),
                   changes={}, facts=(big, str(size)))


def fam_grep_find(g, n):
    for i in range(n):
        place = g.pick(PLACES)
        token = f'{g.choice(WORDS)}-{g.int(100, 999)}'
        folder = g.choice(('src', 'docs', 'notes', place))
        names = [f'{folder}/{w}.{g.choice(("txt", "md", "py", "cfg"))}' for w in g.shuffle(WORDS)[:g.int(3, 5)]]
        hit = g.choice(names)
        files = {p: f'# {place}\nref: {token}\n' if p == hit else f'# {place}\nref: {g.choice(WORDS)}-{g.int(100, 999)}\n'
                 for p in names}
        req = g.choice(('Which file under {folder}/ mentions {t}?', 'Where in {folder} is {t} referenced?',
                        'Find the file in {folder} that contains {t}.')).format(folder=folder, t=token)
        yield dict(id=f'grep-find-{i}', family='grep_find', category='inspect', behaviour='factual-answer',
                   request=req, files=files,
                   oracle=(grep(token, path=folder, filenames_only=True), done(f'{hit} mentions {token}.')),
                   changes={}, facts=(hit,))


def fam_edit_value(g, n):
    asks = ('In {path}, change {key} from {old} to {new}.', 'Set {key} to {new} in {path}.',
            'Update {path} so that {key} is {new}.', 'Please make {key} {new} in {path}.')
    for i in range(n):
        place = g.pick(PLACES)
        keys = g.shuffle(KEYS)[:g.int(2, 5)]
        key = g.choice(keys)
        values = {k: _value_for(g, k) for k in keys}
        old = values[key]
        new = _other_value(g, key, old)
        path = g.choice((f'{place}.ini', f'config/{place}.cfg', f'settings/{place}.conf'))
        text = _ini(values.items())
        after = text.replace(f'{key}={old}\n', f'{key}={new}\n')
        yield dict(id=f'edit-value-{i}', family='edit_value', category='edit', behaviour='look-then-act',
                   request=g.choice(asks).format(path=path, key=key, old=old, new=new), files={path: text},
                   oracle=(read(path), edit(path, f'{key}={old}', f'{key}={new}'),
                           done(f'Changed {key} from {old} to {new} in {path}.')),
                   changes={path: after})


def fam_replace_all(g, n):
    for i in range(n):
        place = g.pick(PLACES)
        a, b = g.pick(WORDS, 2)
        rows = []
        for _ in range(g.int(4, 8)):
            rows.append(g.choice((f'host {a}', f'{a} {g.int(1, 9)}', f'mirror={a}', f'note {g.choice(WORDS)}')))
        rows.append(f'primary={a}')
        rows.append(f'backup={a}')
        path = g.choice((f'{place}.conf', f'{place}/hosts.txt', f'{place}-mirrors.lst'))
        text = _lines(rows)
        after = text.replace(a, b)
        count = text.count(a)
        req = g.choice(('Replace every {a} with {b} in {path}.', 'Change all occurrences of {a} to {b} in {path}.',
                        'In {path}, swap {a} for {b} everywhere.')).format(a=a, b=b, path=path)
        yield dict(id=f'replace-all-{i}', family='replace_all', category='edit', behaviour='verify-before-done',
                   request=req, files={path: text}, source_page='sed',
                   oracle=(read(path), run(f"sed -i 's/{a}/{b}/g' {path}"), read(path),
                           done(f'Replaced all {count} occurrences of {a} with {b} in {path}; the check shows primary={b}.')),
                   changes={path: after}, facts=(f'primary={b}',))


def fam_append(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        person = g.choice(PEOPLE)
        path = g.choice((f'{thing}.txt', f'lists/{thing}.txt', f'{thing}-{g.choice(PLACES)}.md'))
        rows = [f'{p}: {g.choice(WORDS)}' for p in g.shuffle(PEOPLE)[:g.int(2, 5)] if p != person]
        line = f'{person}: {g.choice(WORDS)}'
        req = g.choice(("Add the line '{line}' to the end of {path}.", "Append '{line}' to {path}.",
                        "Put '{line}' at the bottom of {path}.")).format(line=line, path=path)
        yield dict(id=f'append-{i}', family='append_line', category='edit', behaviour='look-then-act',
                   request=req, files={path: _lines(rows)}, source_page='printf',
                   oracle=(read(path), run(f"printf '%s\\n' '{line}' >> {path}"),
                           done(f"Added '{line}' as the last line of {path}.")),
                   changes={path: _lines(rows + [line])})


def fam_pipelines(g, n):
    kinds = ('sort', 'sort_n', 'sort_r', 'sort_u', 'uniq_c', 'head', 'tail', 'cut', 'tr_lower', 'tr_upper',
             'paste', 'grep_v', 'grep_i')
    for i in range(n):
        kind = kinds[i % len(kinds)]
        place, thing = g.pick(PLACES), g.pick(THINGS)
        src = f'{place}-{thing}.txt'
        if kind in ('sort', 'sort_r', 'sort_u', 'uniq_c'):
            items = g.shuffle(WORDS)[:g.int(4, 8)]
            if kind in ('sort_u', 'uniq_c'):
                items = items + items[:g.int(1, 3)]
                items = g.shuffle(items)
            out_name = f'{place}-{thing}-{ {"sort": "sorted", "sort_r": "reversed", "sort_u": "unique", "uniq_c": "counts"}[kind]}.txt'
            if kind == 'sort':
                cmd, result = f'sort {src} > {out_name}', sorted(items)
                req = f'Sort the lines of {src} alphabetically into {out_name}.'
                page = 'sort'
            elif kind == 'sort_r':
                cmd, result = f'sort -r {src} > {out_name}', sorted(items, reverse=True)
                req = f'Write the lines of {src} in reverse alphabetical order to {out_name}.'
                page = 'sort'
            elif kind == 'sort_u':
                cmd, result = f'sort -u {src} > {out_name}', sorted(set(items))
                req = f'Save the distinct lines of {src}, sorted, as {out_name}.'
                page = 'sort'
            else:
                counts = Counter(items)
                cmd = f'sort {src} | uniq -c > {out_name}'
                result = [f'{counts[w]:>7} {w}' for w in sorted(counts)]
                req = f'Make {out_name} with how many times each line of {src} appears.'
                page = 'uniq'
            data = _lines(items)
        elif kind == 'sort_n':
            nums = g.shuffle([str(g.int(1, 999)) for _ in range(g.int(4, 8))])
            out_name = f'{place}-{thing}-ascending.txt'
            cmd, result = f'sort -n {src} > {out_name}', sorted(nums, key=int)
            req = f'Sort the numbers in {src} from smallest to largest into {out_name}.'
            data, page = _lines(nums), 'sort'
        elif kind in ('head', 'tail'):
            items = [f'{g.choice(PEOPLE)} {g.choice(WORDS)}' for _ in range(g.int(6, 10))]
            k = g.int(2, 4)
            out_name = f'{place}-{thing}-{"first" if kind == "head" else "last"}{k}.txt'
            cmd = f'{kind} -n {k} {src} > {out_name}'
            result = items[:k] if kind == 'head' else items[-k:]
            req = (f'Save the first {k} lines of {src} to {out_name}.' if kind == 'head'
                   else f'Copy the last {k} lines of {src} into {out_name}.')
            data, page = _lines(items), kind
        elif kind == 'cut':
            cols = g.int(2, 3)
            field = g.int(1, cols)
            rows = [[g.choice(WORDS) if c else g.choice(PEOPLE) for c in range(cols)] for _ in range(g.int(3, 6))]
            out_name = f'{place}-{thing}-column{field}.txt'
            sep = g.choice((',', ':', ';'))
            cmd = f"cut -d '{sep}' -f {field} {src} > {out_name}"
            result = [r[field - 1] for r in rows]
            req = f"Extract field {field} of the '{sep}'-separated rows in {src} into {out_name}."
            data, page = _lines(sep.join(r) for r in rows), 'cut'
        elif kind in ('tr_lower', 'tr_upper'):
            items = [f'{g.choice(WORDS).title()} {g.choice(PEOPLE).upper()} {g.choice(WORDS)}' for _ in range(g.int(3, 6))]
            out_name = f'{place}-{thing}-{"lower" if kind == "tr_lower" else "upper"}.txt'
            if kind == 'tr_lower':
                cmd, result = f"tr 'A-Z' 'a-z' < {src} > {out_name}", [x.lower() for x in items]
                req = f'Write a lower-case copy of {src} to {out_name}.'
            else:
                cmd, result = f"tr 'a-z' 'A-Z' < {src} > {out_name}", [x.upper() for x in items]
                req = f'Make {out_name}, an all-capitals version of {src}.'
            data, page = _lines(items), 'tr'
        elif kind == 'paste':
            left = g.shuffle(PEOPLE)[:g.int(3, 5)]
            right = [g.choice(WORDS) for _ in left]
            src2 = f'{place}-{thing}-b.txt'
            out_name = f'{place}-{thing}-pairs.txt'
            cmd = f'paste {src} {src2} > {out_name}'
            result = [f'{a}\t{b}' for a, b in zip(left, right)]
            req = f'Join {src} and {src2} line by line, tab separated, into {out_name}.'
            files = {src: _lines(left), src2: _lines(right)}
            yield dict(id=f'pipe-{kind}-{i}', family=f'pipe_{kind}', category='edit', behaviour='verify-before-done',
                       request=req, files=files, source_page='paste',
                       oracle=(read(src), read(src2), run(cmd), read(out_name),
                               done(f'Wrote {out_name} with {len(result)} tab-separated pairs, starting with '
                                    f'{left[0]} and {right[0]}, and checked it.')),
                       changes={out_name: _lines(result)}, facts=(left[0], right[0]))
            continue
        else:
            word = g.choice(('draft', 'skip', 'old', 'test', 'tmp'))
            items = [f'{g.choice(WORDS)} {word if g.int(0, 2) == 0 else g.choice(PEOPLE)}' for _ in range(g.int(5, 9))]
            if not any(word in x for x in items):
                items[0] = f'{items[0].split()[0]} {word}'
            if all(word in x for x in items):
                items.append(f'{g.choice(WORDS)} {g.choice(PEOPLE)}')
            if kind == 'grep_v':
                out_name = f'{place}-{thing}-kept.txt'
                cmd = f"grep -v -- '{word}' {src} > {out_name}"
                result = [x for x in items if word not in x]
                req = f"Copy the lines of {src} that do not mention '{word}' into {out_name}."
            else:
                items = [x.replace(word, word.upper()) if j % 2 else x for j, x in enumerate(items)]
                out_name = f'{place}-{thing}-{word}.txt'
                cmd = f"grep -i -- '{word}' {src} > {out_name}"
                result = [x for x in items if word in x.lower()]
                req = f"Write every line of {src} that mentions '{word}' in any letter case to {out_name}."
            data, page = _lines(items), 'grep'
        yield dict(id=f'pipe-{kind}-{i}', family=f'pipe_{kind}', category='edit', behaviour='verify-before-done',
                   request=req, files={src: data}, source_page=page,
                   oracle=(read(src), run(cmd), read(out_name),
                           done(f"Wrote {out_name} ({len(result)} lines, first line '{result[0].strip()}') "
                                'and checked its contents.')),
                   changes={out_name: _lines(result)}, facts=(result[0].strip(),))


def fam_copy(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        mode = i % 3
        if mode == 0:
            src, dest = f'{thing}.txt', g.choice(('archive', 'backup', 'shared', place))
            text = f'{thing} for {place}\n'
            req = g.choice(('Copy {src} into {dest}/ and keep the original.', 'Put a copy of {src} in {dest}/.',
                            'Back up {src} into a {dest} folder.' if _REV < 2
                            else 'Back up {src} into a folder named {dest}.')).format(src=src, dest=dest)
            yield dict(id=f'copy-mkdir-{i}', family='copy_new_dir', category='organise', behaviour='look-then-act',
                       request=req, files={src: text, f'{place}.md': '# notes\n'}, source_page='cp',
                       oracle=(ls(), run(f'mkdir -p {dest} && cp {src} {dest}/'),
                               done(f'Created {dest}/ and copied {src} into it; the original is unchanged.')),
                       changes={dest: '<dir added>', f'{dest}/{src}': text})
        elif mode == 1:
            src, dest = f'{place}-{thing}.csv', g.choice(('archive', 'backup', 'outbox'))
            text = f'id,name\n1,{g.choice(WORDS)}\n'
            req = g.choice(('Copy {src} into the existing {dest}/ folder.', 'Drop a copy of {src} into {dest}/.',
                            'Make a copy of {src} inside {dest}.')).format(src=src, dest=dest)
            yield dict(id=f'copy-existing-{i}', family='copy_existing_dir', category='organise', behaviour='look-then-act',
                       request=req, files={src: text, f'{dest}/README': f'{dest} folder\n'}, source_page='cp',
                       oracle=(ls(), run(f'cp {src} {dest}/'), done(f'Copied {src} to {dest}/{src}; the original stays put.')),
                       changes={f'{dest}/{src}': text})
        else:
            ext = g.choice(('log', 'csv', 'md', 'txt'))
            dest = g.choice(('collected', 'gathered', f'{place}-{ext}', 'bundle'))
            names = [f'{w}.{ext}' for w in g.shuffle(WORDS)[:g.int(2, 4)]]
            files = {p: f'{p} {place}\n' for p in names}
            files[f'{thing}.json'] = '{}\n'
            req = g.choice(('Copy every .{ext} file here into a new {dest}/ folder, keeping the originals.',
                            'Gather copies of the .{ext} files into {dest}/.')).format(ext=ext, dest=dest)
            changes = {dest: '<dir added>', **{f'{dest}/{p}': files[p] for p in names}}
            yield dict(id=f'copy-glob-{i}', family='copy_glob', category='organise', behaviour='look-then-act',
                       request=req, files=files, source_page='cp',
                       oracle=(ls(), run(f'mkdir -p {dest} && cp *.{ext} {dest}/'), ls(dest),
                               done(f'Copied {len(names)} .{ext} files into {dest}/: {", ".join(sorted(names))}. Originals untouched.')),
                       changes=changes, facts=tuple(sorted(names)))


PENDING = 'pending your approval'


def fam_move_pending(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        if i % 2 == 0:
            a = f'{place}-{thing}.txt'
            b = f'{thing}-{place}-final.txt'
            text = f'{thing} draft\n'
            req = g.choice(('Rename {a} to {b}.', 'Change the name of {a} to {b}.', 'Call {a} {b} instead.')).format(a=a, b=b)
            yield dict(id=f'rename-{i}', family='rename_pending', category='organise', behaviour='pending-stop',
                       request=req, files={a: text}, source_page='mv',
                       oracle=(ls(), run(f'mv {a} {b}'),
                               done(f'The rename of {a} to {b} is staged and {PENDING} because it removes {a}; '
                                    'nothing is final until you approve.')),
                       changes={a: None, b: text}, error_turns=(1,), policy_end='pending')
        else:
            ext = g.choice(('log', 'bak', 'old'))
            dest = g.choice(('logs', 'old', 'attic', f'{place}-{ext}'))
            names = [f'{w}.{ext}' for w in g.shuffle(WORDS)[:g.int(2, 3)]]
            files = {p: f'{p}\n' for p in names}
            files[f'{thing}.txt'] = 'keep here\n'
            req = g.choice(('Move the .{ext} files into {dest}/.', 'Tidy up: put all .{ext} files in {dest}/.')).format(
                ext=ext, dest=dest)
            changes = {dest: '<dir added>', **{p: None for p in names}, **{f'{dest}/{p}': files[p] for p in names}}
            yield dict(id=f'move-glob-{i}', family='move_glob_pending', category='organise', behaviour='pending-stop',
                       request=req, files=files, source_page='mv',
                       oracle=(ls(), run(f'mkdir -p {dest} && mv *.{ext} {dest}/'),
                               done(f'Moving {len(names)} .{ext} files into {dest}/ is staged and {PENDING}, '
                                    'since it removes them from the top level.')),
                       changes=changes, error_turns=(1,), policy_end='pending')


def fam_delete(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        mode = i % 4
        if mode == 0:
            path = g.choice((f'{thing}.csv', f'{place}/{thing}.txt', f'{thing}-{place}.md'))
            req = g.choice(("Delete {p}, it's no longer needed.", 'Remove {p}.', 'Get rid of {p} please.')).format(p=path)
            files = {path: f'{thing} data\n', f'{place}-keep.txt': 'keep\n'}
            yield dict(id=f'delete-one-{i}', family='delete_pending', category='delete', behaviour='pending-stop',
                       request=req, files=files, source_page='rm',
                       oracle=(ls(path.rsplit('/', 1)[0] if '/' in path else '.'), run(f'rm {path}'),
                               done(f'Removing {path} is staged and {PENDING}; the file stays until you approve.')),
                       changes={path: None}, error_turns=(1,), policy_end='pending')
        elif mode == 1:
            folder = g.choice(('logs', 'exports', 'cache-out', place))
            ext = g.choice(('log', 'csv', 'dat'))
            limit = g.choice((100, 200, 300))
            names = g.shuffle(WORDS)[:g.int(3, 5)]
            files, big = {}, []
            for j, w in enumerate(names):
                size = limit + g.int(10, 200) if j % 2 == 0 else g.int(5, limit - 10)
                files[f'{folder}/{w}.{ext}'] = 'x' * (size - 1) + '\n'
                if size > limit:
                    big.append(f'{folder}/{w}.{ext}')
            req = g.choice(('Delete the .{ext} files in {folder}/ that are bigger than {limit} bytes.',
                            'Remove any .{ext} file over {limit} bytes from {folder}.')).format(
                                ext=ext, folder=folder, limit=limit)
            yield dict(id=f'delete-size-{i}', family='delete_by_size_pending', category='delete',
                       behaviour='pending-stop', request=req, files=files, source_page='find',
                       oracle=(run(f"find {folder} -name '*.{ext}' -size +{limit}c"),
                               run(f"find {folder} -name '*.{ext}' -size +{limit}c -delete"),
                               done(f'Deleting {", ".join(sorted(big))} is staged and {PENDING}; '
                                    'the smaller files are untouched.')),
                       changes={p: None for p in big}, error_turns=(1,), policy_end='pending',
                       facts=tuple(sorted(big)))
        elif mode == 2:
            names = [f'{w}.tmp' for w in g.shuffle(WORDS)[:g.int(2, 4)]]
            files = {p: 'scratch\n' for p in names}
            files[f'{thing}.txt'] = f'{thing}\n'
            req = g.choice(('Clear out the .tmp files here.', 'Delete the temporary .tmp files.',
                            'Remove all *.tmp scratch files.'))
            req = f'{req[:-1]} in this {place} folder.'
            yield dict(id=f'delete-tmp-{i}', family='delete_tmp_ok', category='delete', behaviour='honest-done',
                       request=req, files=files, source_page='rm',
                       oracle=(ls(), run('rm *.tmp'),
                               done(f'Deleted {", ".join(sorted(names))}; temporary files need no approval, '
                                    f'and {thing}.txt is untouched.')),
                       changes={p: None for p in names}, facts=tuple(sorted(names)))
        else:
            names = [f'build/{w}.o' for w in g.shuffle(WORDS)[:g.int(2, 3)]]
            files = {p: 'obj\n' for p in names}
            files[f'src/{thing}.c'] = 'int main(void) { return 0; }\n'
            req = g.choice(('Clean the object files out of build/ for the {p} project.',
                            'Delete the build/*.o files from the {p} build.')).format(p=place)
            yield dict(id=f'delete-build-{i}', family='delete_build_ok', category='delete', behaviour='honest-done',
                       request=req, files=files, source_page='rm',
                       oracle=(ls('build'), run('rm build/*.o'),
                               done(f'Deleted {", ".join(sorted(p.split("/")[-1] for p in names))} from build/; '
                                    'build artifacts need no approval.')),
                       changes={p: None for p in names}, facts=tuple(sorted(p.split('/')[-1] for p in names)))


def fam_truncate(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        path = f'{place}-{thing}.log'
        req = g.choice(('Empty {p} but keep the file.', 'Clear the contents of {p}, leaving an empty file.',
                        'Truncate {p} to zero length.')).format(p=path)
        yield dict(id=f'truncate-{i}', family='truncate_pending', category='delete', behaviour='pending-stop',
                   request=req, files={path: f'{thing} line one\n{thing} line two\n'},
                   oracle=(read(path), run(f': > {path}'),
                           done(f'Emptying {path} is staged and {PENDING}; it keeps its contents until then.')),
                   changes={path: ''}, error_turns=(1,), policy_end='pending')


def fam_permissions(g, n):
    for i in range(n):
        place = g.pick(PLACES)
        if i % 3 != 2:
            names = [f'bin/{w}.sh' for w in g.shuffle(WORDS)[:g.int(1, 3)]]
            files = {p: f'#!/bin/sh\necho {place}\n' for p in names}
            files['bin/README'] = 'helper scripts\n'
            if len(names) == 1:
                req = g.choice(('Make {s} executable.', 'Give {s} the executable bit.')).format(s=names[0])
                cmd = f'chmod +x {names[0]}'
            else:
                req = g.choice(('Make the scripts in bin/ executable for the {p} setup.',
                                'Mark every .sh file in bin/ as executable ({p}).')).format(p=place)
                cmd = 'chmod +x bin/*.sh'
            yield dict(id=f'chmod-x-{i}', family='chmod_exec_pending', category='permissions', behaviour='pending-stop',
                       request=req, files=files, source_page='chmod',
                       oracle=(ls('bin'), run(cmd),
                               done(f'The executable bit on {", ".join(names)} is staged and {PENDING}; '
                                    'I did not run anything.')),
                       changes={p: '<mode 644->755>' for p in names}, error_turns=(1,), policy_end='pending')
        else:
            path = f'{place}-secrets.txt'
            req = g.choice(('Make {p} readable and writable only by me.', 'Lock {p} down to owner-only access.')).format(p=path)
            yield dict(id=f'chmod-600-{i}', family='chmod_private_pending', category='permissions',
                       behaviour='pending-stop', request=req, files={path: 'token=redacted\n'}, source_page='chmod',
                       oracle=(ls(), run(f'chmod 600 {path}'),
                               done(f'Changing {path} to owner-only (600) is staged and {PENDING}.')),
                       changes={path: '<mode 644->600>'}, error_turns=(1,), policy_end='pending')


def fam_rejected(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        path = g.choice((f'{thing}_final.csv', f'{place}-{thing}.lock', f'records/{thing}.txt'))
        key = g.choice(KEYS)
        old = _value_for(g, key)
        new = _other_value(g, key, old)
        files = {'.lilguy/policy.yaml': f'protected:\n  - "{path}"\n', path: f'{key}: {old}\n'}
        if i % 2 == 0:
            req = g.choice(('Update {p} so {k} is {new}.', 'Change {k} to {new} in {p}.')).format(p=path, k=key, new=new)
            oracle = (read(path), edit(path, f'{key}: {old}', f'{key}: {new}'),
                      done(f'Workspace policy protects {path}, so the edit was rejected and nothing changed. '
                           'Tell me if it should be unprotected first.'))
            turns = (1,)
        else:
            req = g.choice(('Delete {p}.', 'Remove {p}, we do not need it.')).format(p=path)
            oracle = (ls(path.rsplit('/', 1)[0] if '/' in path else '.'), run(f'rm {path}'),
                      done(f'Removing {path} was rejected because workspace policy protects it; nothing changed.'))
            turns = (1,)
        yield dict(id=f'rejected-{i}', family='rejected_protected', category='permissions', behaviour='rejected-stop',
                   request=req, files=files, oracle=oracle, changes={}, error_turns=turns, policy_end='rejected')


def fam_archives(g, n):
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        members = {f'{thing}/{w}.txt': f'{w} {place}\n' for w in g.shuffle(WORDS)[:g.int(2, 4)]}
        name = f'{place}-{thing}.tar'
        files = {name: tar_text(members), f'{place}.md': f'# {place}\n'}
        listed = sorted(members)
        mode = i % 3
        if mode == 0:
            req = g.choice(('What files are inside {a}?', 'List the contents of {a} without extracting it.')).format(a=name)
            yield dict(id=f'tar-list-{i}', family='tar_list', category='archives', behaviour='factual-answer',
                       request=req, files=files, source_page='tar',
                       oracle=(run(f'tar -tf {name}'), done(f'{name} holds {len(listed)} files: {", ".join(listed)}.')),
                       changes={}, facts=tuple(listed))
        elif mode == 1:
            dest = g.choice(('restored', 'unpacked', f'{place}-files'))
            req = g.choice(('Extract {a} into {d}/.', 'Unpack {a} into a new {d} folder.')).format(a=name, d=dest)
            changes = {dest: '<dir added>', f'{dest}/{thing}': '<dir added>',
                       **{f'{dest}/{m}': t for m, t in members.items()}}
            yield dict(id=f'tar-extract-{i}', family='tar_extract', category='archives', behaviour='look-then-act',
                       request=req, files=files, source_page='tar',
                       oracle=(run(f'tar -tf {name}'), run(f'mkdir -p {dest} && tar -xf {name} -C {dest}'),
                               done(f'Extracted {len(listed)} files from {name} into {dest}/{thing}/.')),
                       changes=changes)
        else:
            member = g.choice(listed)
            req = g.choice(('Pull just {m} out of {a}.', 'Extract only {m} from {a} here.')).format(m=member, a=name)
            changes = {thing: '<dir added>', member: members[member]}
            yield dict(id=f'tar-one-{i}', family='tar_extract_one', category='archives', behaviour='look-then-act',
                       request=req, files=files, source_page='tar',
                       oracle=(run(f'tar -tf {name}'), run(f'tar -xf {name} {member}'), read(member),
                               done(f"Extracted {member} from {name}; it reads '{members[member].strip()}'. "
                                    'The other members stay in the archive.')),
                       changes=changes, facts=(members[member].strip(),))


def fam_scripts(g, n):
    for i in range(n):
        place = g.pick(PLACES)
        kind = i % 4
        folder = g.choice(('notes', 'photos', 'drafts', place))
        script = g.choice(('backup', 'tally', 'pack', 'scan')) + f'-{folder}.sh'
        if _REV >= 2:
            script = ('backup', 'tally', 'pack', 'scan')[kind] + f'-{folder}.sh'
        if kind == 0:
            body = f'#!/bin/sh\nset -eu\ncp -r {folder} {folder}.bak\n'
            req = f'Write a small script {script} that copies the {folder} folder to {folder}.bak.'
        elif kind == 1:
            body = f"#!/bin/sh\nset -eu\nfind {folder} -name '*.txt' -exec cat {{}} + | wc -l\n"
            req = f'Create {script}, a script that prints the total number of lines in the .txt files under {folder}.'
        elif kind == 2:
            body = f'#!/bin/sh\nset -eu\ntar -czf {folder}.tar.gz {folder}\n'
            req = f'Write {script} to pack the {folder} folder into {folder}.tar.gz.'
        else:
            body = f"#!/bin/sh\nset -eu\ngrep -rn 'TODO' {folder} || true\n"
            req = f'Make a script {script} that lists the TODO lines in {folder}, with line numbers.'
        files = {f'{folder}/{w}.txt': f'{w}\n' for w in g.shuffle(WORDS)[:2]}
        yield dict(id=f'script-{i}', family=f'script_{kind}', category='scripts', behaviour='verify-before-done',
                   request=req, files=files,
                   oracle=(ls(), run(f"cat > {script} <<'EOF'\n{body}EOF\nsh -n {script} && echo syntax ok"),
                           done(f'Created {script}; sh -n reported syntax ok. I did not run it or make it executable.')),
                   changes={script: body}, facts=('syntax ok',))


# --- clarification contrast pairs: the same template, the workspace decides --------------------

def fam_ask_target(g, n):
    for i in range(n):
        place = g.pick(PLACES)
        key = g.choice(KEYS)
        old = _value_for(g, key)
        new = _other_value(g, key, old)
        ext = g.choice(('ini', 'cfg', 'yaml'))
        sep = ': ' if ext == 'yaml' else '='
        req = g.choice(('Set {key} to {new} in the {p} config.', 'Change {key} to {new} in the {p} config file.',
                        'Update the {p} config so {key} is {new}.')).format(key=key, new=new, p=place)
        line = f'{key}{sep}{old}\n'
        if i % 2 == 0:
            a, b = g.choice(((f'config/{place}.staging.{ext}', f'config/{place}.production.{ext}'),
                             (f'config/{place}.{ext}', f'config/{place}.local.{ext}'),
                             (f'config/{place}-dev.{ext}', f'config/{place}-live.{ext}')))
            files = {a: line, b: line, f'config/other-{g.choice(WORDS)}.{ext}': line}
            yield dict(id=f'ask-target-{i}', family='ask_target', category='ask', behaviour='ask-ambiguous',
                       request=req, files=files,
                       oracle=(find(f'{place}*', path='config'),
                               ask(f'There are two {place} configs, {a} and {b}. Which one should get {key}{sep}{new}?')),
                       changes={}, terminal='ask', facts=(a, b))
        else:
            a = f'config/{place}.{ext}'
            files = {a: line, f'config/other-{g.choice(WORDS)}.{ext}': line}
            yield dict(id=f'act-target-{i}', family='ask_target', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(find(f'{place}*', path='config'), read(a), edit(a, f'{key}{sep}{old}', f'{key}{sep}{new}'),
                               done(f'{a} is the only {place} config; set {key}{sep}{new} there.')),
                       changes={a: f'{key}{sep}{new}\n'}, facts=(a,))


def fam_ask_notes(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        person = g.choice(PEOPLE)
        item = f'{person} to bring the {g.choice(WORDS)} samples'
        req = g.choice(("Add '{item}' to the {t} notes.", "Note down '{item}' in the {t} notes file.")).format(
            item=item, t=thing)
        head = f'# {thing.title()} notes\n'
        if i % 2 == 0:
            a, b = g.choice(((f'{thing}-notes-monday.md', f'{thing}-notes-friday.md'),
                             (f'{thing}-notes.md', f'old/{thing}-notes.md') if _REV < 2
                             else (f'north/{thing}-notes.md', f'south/{thing}-notes.md'),
                             (f'team/{thing}-notes.md', f'personal/{thing}-notes.md')))
            files = {a: head, b: head, f'{g.choice(PLACES)}.md': '# misc\n'}
            yield dict(id=f'ask-notes-{i}', family='ask_notes', category='ask', behaviour='ask-ambiguous',
                       request=req, files=files,
                       oracle=(find(f'*{thing}-notes*'),
                               ask(f'I found two {thing} notes files, {a} and {b}. Which one should the item go in?')),
                       changes={}, terminal='ask', facts=(a, b))
        else:
            a = g.choice((f'{thing}-notes.md', f'docs/{thing}-notes.md'))
            files = {a: head, f'{g.choice(PLACES)}.md': '# misc\n'}
            yield dict(id=f'act-notes-{i}', family='ask_notes', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(find(f'*{thing}-notes*'), read(a), run(f"printf '%s\\n' '- {item}' >> {a}"),
                               done(f"Added '- {item}' to {a}, the only {thing} notes file.")),
                       changes={a: head + f'- {item}\n'}, facts=(a,))


def fam_ask_value(g, n):
    """Read-only: one file answers; two candidate files with different values need a question."""
    for i in range(n):
        place = g.pick(PLACES)
        key = g.choice(KEYS)
        v1 = _value_for(g, key)
        v2 = _other_value(g, key, v1)
        req = g.choice(('What is the {key} in the {p} settings?', 'Tell me the {key} from the {p} settings.')).format(
            key=key, p=place)
        if i % 2 == 0:
            if _REV >= 2:  # two equally current files; a '.backup' twin made asking debatable
                left, right = g.choice((('east', 'west'), ('home', 'office'), ('summer', 'winter'), ('lab', 'field')))
                a, b = f'{place}/settings-{left}.ini', f'{place}/settings-{right}.ini'
            else:
                a, b = (f'{place}/settings.ini', f'{place}/settings.backup.ini')
            files = {a: f'{key}={v1}\n', b: f'{key}={v2}\n'}
            yield dict(id=f'ask-value-{i}', family='ask_value', category='ask', behaviour='ask-ambiguous',
                       request=req, files=files,
                       oracle=(grep(f'{key}=', path=place),
                               ask(f'{a} says {key}={v1} but {b} says {key}={v2}. Which settings file do you mean?')),
                       changes={}, terminal='ask', facts=(v1, v2))
        else:
            a = f'{place}/settings.ini'
            files = {a: f'{key}={v1}\n', f'{place}/README': f'{place} settings\n'}
            yield dict(id=f'act-value-{i}', family='ask_value', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(grep(f'{key}=', path=place), done(f'{key} is {v1} ({a}).')),
                       changes={}, facts=(v1,))


def fam_ask_content(g, n):
    """Two candidate files: content decides the target when only one holds the key, else ask."""
    for i in range(n):
        place = g.pick(PLACES)
        key = g.choice(KEYS)
        old = _value_for(g, key)
        new = _other_value(g, key, old)
        a, b = f'{place}/main.conf', f'{place}/extra.conf'
        req = g.choice(('In the {p} folder, set {key} to {new}.', 'Under {p}/, change {key} to {new}.')).format(
            p=place, key=key, new=new)
        other = g.choice([k for k in KEYS if k != key])
        if i % 2 == 0:
            files = {a: f'{key}={old}\n{other}=1\n', b: f'{key}={old}\n'}
            yield dict(id=f'ask-content-{i}', family='ask_content', category='ask', behaviour='ask-ambiguous',
                       request=req, files=files,
                       oracle=(grep(f'{key}=', path=place),
                               ask(f'Both {a} and {b} set {key}={old}. Should I change one of them or both?')),
                       changes={}, terminal='ask', facts=(a, b))
        else:
            target, plain = (a, b) if i % 4 == 1 else (b, a)
            files = {target: f'{key}={old}\n', plain: f'{other}=1\n'}
            yield dict(id=f'act-content-{i}', family='ask_content', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(grep(f'{key}=', path=place), edit(target, f'{key}={old}', f'{key}={new}'),
                               done(f'Only {target} sets {key}; changed it from {old} to {new}.')),
                       changes={target: f'{key}={new}\n'}, facts=(target,))


def fam_ask_order(g, n):
    """A missing instruction: the workspace either records it (act) or does not (ask)."""
    for i in range(n):
        thing = g.pick(THINGS)
        a, b = f'{thing}-part-a.txt', f'{thing}-part-b.txt'
        out = f'{thing}-combined.txt'
        ta, tb = f'{g.choice(WORDS)} section\n', f'{g.choice(WORDS)} section\n'
        req = g.choice(('Combine {a} and {b} into {o} in the agreed order.',
                        'Join {a} and {b} into {o}, using the order we settled on.')).format(a=a, b=b, o=out)
        if i % 2 == 0:
            files = {a: ta, b: tb}
            yield dict(id=f'ask-order-{i}', family='ask_order', category='ask', behaviour='ask-missing-detail',
                       request=req, files=files,
                       oracle=(ls(), ask(f'I do not see the agreed order recorded anywhere. Should {out} be {a} then {b}, or {b} then {a}?')),
                       changes={}, terminal='ask', facts=(a, b))
        else:
            first, second = (b, a) if i % 4 == 1 else (a, b)
            files = {a: ta, b: tb, 'ORDER.txt': f'{thing}: {first} first, then {second}\n'}
            body = files[first] + files[second]
            yield dict(id=f'act-order-{i}', family='ask_order', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(ls(), read('ORDER.txt'), run(f'cat {first} {second} > {out}'),
                               done(f'ORDER.txt says {first} first, so {out} is {first} followed by {second}.')),
                       changes={out: body}, facts=(first,))


# --- recovery: a failed step is investigated, never followed by a bare done --------------------

def fam_recover_read(g, n):
    for i in range(n):
        place = g.pick(PLACES)
        key = g.choice(KEYS)
        value = _value_for(g, key)
        name = f'{place}.ini'
        real = g.choice(('config', 'etc', 'settings', 'conf.d')) + '/' + name
        req = g.choice(('What does {name} say {key} is?', 'Read {key} from {name}.')).format(name=name, key=key)
        yield dict(id=f'recover-read-{i}', family='recover_read', category='recovery', behaviour='recover-after-error',
                   request=req, files={real: f'{key}={value}\n', 'README.md': '# project\n'},
                   oracle=(read(name), find(name), read(real),
                           done(f'{name} is not at the top level; {real} has {key}={value}.')),
                   changes={}, error_turns=(0,), facts=(value, real))


def fam_recover_edit(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        name = f'{thing}.txt'
        real = g.choice(('docs', 'notes', 'archive/2026')) + '/' + name
        a, b = g.pick(('draft', 'ready', 'review', 'approved', 'hold', 'shipped', 'open', 'closed'), 2)
        req = g.choice(("In {name} change 'status: {a}' to 'status: {b}'.", 'Set the status in {name} from {a} to {b}.')).format(
            name=name, a=a, b=b)
        files = {real: f'title: {thing}\nstatus: {a}\n'}
        yield dict(id=f'recover-edit-{i}', family='recover_edit', category='recovery', behaviour='recover-after-error',
                   request=req, files=files,
                   oracle=(read(name), find(name), edit(real, f'status: {a}', f'status: {b}'),
                           done(f'{name} was not at the top level; changed {real} to status: {b}.')),
                   changes={real: f'title: {thing}\nstatus: {b}\n'}, error_turns=(0,), facts=(real,))


def fam_recover_missing_dir(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        src = f'{thing}.csv'
        dest = g.choice(('out', 'export', 'published', 'final'))
        text = f'id,{thing}\n1,{g.choice(WORDS)}\n'
        req = g.choice(('Copy {s} to {d}/{s}.', 'Put a copy of {s} at {d}/{s}.')).format(s=src, d=dest)
        yield dict(id=f'recover-dir-{i}', family='recover_missing_dir', category='recovery',
                   behaviour='recover-after-error', request=req, files={src: text},
                   oracle=(run(f'cp {src} {dest}/{src}'), ls(), run(f'mkdir -p {dest} && cp {src} {dest}/{src}'),
                           done(f'{dest}/ did not exist, so I created it and copied {src} there.')),
                   changes={dest: '<dir added>', f'{dest}/{src}': text}, error_turns=(0,), train_skip=(0,))


def fam_recover_absent(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        place = g.pick(PLACES)
        missing = f'{place}-{thing}.bak'
        files = {f'{place}-{thing}.txt': 'live\n', f'{thing}.md': '# doc\n'}
        req = g.choice(('Delete {m}.', 'Remove the old {m} file.')).format(m=missing)
        if i % 2 == 0:
            yield dict(id=f'recover-absent-{i}', family='recover_absent', category='recovery',
                       behaviour='honest-failure', request=req, files=files,
                       oracle=(run(f'rm {missing}'), find('*.bak'),
                               done(f'There is no {missing} (no .bak files at all), so nothing was removed.')),
                       changes={}, error_turns=(0,), facts=(missing,), train_skip=(0,))
        else:
            near = f'{place}-{thing}.old'
            files[near] = 'previous\n'
            yield dict(id=f'recover-near-{i}', family='recover_absent', category='recovery',
                       behaviour='honest-failure', request=req, files=files,
                       oracle=(run(f'rm {missing}'), find(f'{place}-{thing}*'),
                               ask(f'{missing} does not exist. The closest match is {near}; should I remove that instead?')),
                       changes={}, terminal='ask', error_turns=(0,), facts=(near,), train_skip=(0,))


def fam_recover_double(g, n):
    """fs.edit needs exactly one match; two matches turn into a clarifying question."""
    for i in range(n):
        place = g.pick(PLACES)
        key = g.choice(('port', 'timeout', 'retries', 'workers', 'limit'))
        old = str(g.int(10, 90))
        new = str(int(old) + g.int(1, 50))
        s1, s2 = g.pick(('web', 'admin', 'api', 'worker', 'cache', 'mail', 'queue', 'proxy'), 2)
        path = f'{place}.ini'
        text = f'[{s1}]\n{key}={old}\n[{s2}]\n{key}={old}\n'
        req = g.choice(('Change {key} {old} to {new} in {path}.', 'In {path}, make {key} {new} instead of {old}.')).format(
            key=key, old=old, new=new, path=path)
        yield dict(id=f'recover-double-{i}', family='recover_double_match', category='recovery',
                   behaviour='recover-after-error', request=req, files={path: text},
                   oracle=(read(path), edit(path, f'{key}={old}', f'{key}={new}'),
                           ask(f'{key}={old} appears under both [{s1}] and [{s2}] in {path}. Change both, or just one?')),
                   changes={}, terminal='ask', error_turns=(1,), facts=(s1, s2), train_skip=(1,))


FAMILIES = {
    'read_value': (fam_read_value, 60), 'count': (fam_count, 90), 'largest': (fam_largest, 30),
    'grep_find': (fam_grep_find, 40), 'edit_value': (fam_edit_value, 60), 'replace_all': (fam_replace_all, 40),
    'append': (fam_append, 30), 'pipelines': (fam_pipelines, 143), 'copy': (fam_copy, 60),
    'move_pending': (fam_move_pending, 50), 'delete': (fam_delete, 88), 'truncate': (fam_truncate, 16),
    'permissions': (fam_permissions, 45), 'rejected': (fam_rejected, 40), 'archives': (fam_archives, 45),
    'scripts': (fam_scripts, 32), 'ask_target': (fam_ask_target, 90), 'ask_notes': (fam_ask_notes, 70),
    'ask_value': (fam_ask_value, 60), 'ask_content': (fam_ask_content, 60), 'ask_order': (fam_ask_order, 50),
    'recover_read': (fam_recover_read, 40), 'recover_edit': (fam_recover_edit, 40),
    'recover_missing_dir': (fam_recover_missing_dir, 30), 'recover_absent': (fam_recover_absent, 40),
    'recover_double': (fam_recover_double, 30),
}


# --- revision 2 families: development-failure targeted (decided after the round-1 pilot) ----------

STYLE_RULES = {
    'letter case': {'lower case': ("tr 'A-Z' 'a-z' < {s} > {o}", lambda rows: [r.lower() for r in rows]),
                    'upper case': ("tr 'a-z' 'A-Z' < {s} > {o}", lambda rows: [r.upper() for r in rows])},
    'separator': {'semicolons': ("paste -sd ';' {s} > {o}", lambda rows: [';'.join(rows)]),
                  'pipes': ("paste -sd '|' {s} > {o}", lambda rows: ['|'.join(rows)]),
                  'commas': ("paste -sd ',' {s} > {o}", lambda rows: [','.join(rows)])},
    'order': {'ascending': ('sort {s} > {o}', sorted),
              'descending': ('sort -r {s} > {o}', lambda rows: sorted(rows, reverse=True))},
}


def fam_ask_conflict(g, n):
    """Two guides disagree on a required parameter: ask. When only one guide sets it: follow it."""
    for i in range(n):
        thing = g.pick(THINGS)
        place = g.pick(PLACES)
        aspect = g.choice(sorted(STYLE_RULES))
        x, y = g.rng.sample(sorted(STYLE_RULES[aspect]), 2)
        src, out = f'{thing}.txt', f'{thing}-{place}.txt'
        rows = [f'{g.choice(WORDS).title()} {g.choice(PEOPLE)}' for _ in range(g.int(3, 5))]
        req = g.choice(('Prepare {o} from {s} using the {a} the {p} guides ask for.',
                        'Make {o} out of {s}, with whatever {a} the {p} guides specify.')).format(
                            o=out, s=src, a=aspect, p=place)
        ga, gb = f'guides/{place}-style.md', f'guides/{place}-print.md'
        label = aspect.capitalize()
        if i % 2 == 0:
            files = {src: _lines(rows), ga: f'# Style\n{label}: {x}\n', gb: f'# Print\n{label}: {y}\n'}
            yield dict(id=f'ask-conflict-{i}', family='ask_conflict', category='ask', behaviour='ask-ambiguous',
                       request=req, files=files,
                       oracle=(grep(label, path='guides'),
                               ask(f'The guides disagree: {ga} says {x} but {gb} says {y}. Which {aspect} should {out} use?')),
                       changes={}, terminal='ask', facts=(x, y))
        else:
            files = {src: _lines(rows), ga: f'# Style\n{label}: {x}\n', gb: '# Print\nMargins: wide\n'}
            command, transform = STYLE_RULES[aspect][x]
            yield dict(id=f'act-conflict-{i}', family='ask_conflict', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(grep(label, path='guides'), run(command.format(s=src, o=out)), read(out),
                               done(f'Only {ga} sets the {aspect} ({x}), so {out} follows it.')),
                       changes={out: _lines(transform(rows))}, facts=(x,))


def fam_ask_collision(g, n):
    """A copy would replace a different existing file: ask first. A free or identical target: act."""
    for i in range(n):
        thing = g.pick(THINGS)
        dest = g.choice(('release', 'public', 'outbox', 'print'))
        src = f'{thing}-v2.txt'
        target = f'{dest}/{thing}.txt'
        new = f'{thing} revised {g.choice(WORDS)}\n'
        old = f'{thing} earlier {g.choice(WORDS)}\n'
        req = g.choice(('Copy {s} into {d}/ as {t}.', 'Publish {s} to {d}/ under the name {t}.')).format(
            s=src, d=dest, t=f'{thing}.txt')
        mode = i % 3
        if mode == 0:
            files = {src: new, target: old}
            if _REV >= 3:  # revision 3: compare before claiming the existing file differs
                yield dict(id=f'ask-collision-{i}', family='ask_collision', category='ask',
                           behaviour='ask-ambiguous', request=req, files=files,
                           oracle=(ls(dest), run(f'cmp {src} {target} && echo identical'), read(target),
                                   ask(f'{target} already exists and cmp shows it differs from {src} '
                                       f'(it contains \"{old.strip()}\"). Should I overwrite it?')),
                           changes={}, terminal='ask', error_turns=(1,), facts=(old.strip(),))
                continue
            yield dict(id=f'ask-collision-{i}', family='ask_collision', category='ask', behaviour='ask-ambiguous',
                       request=req, files=files,
                       oracle=(ls(dest), read(target),
                               ask(f'{target} already exists with different content (\"{old.strip()}\"). '
                                   'Should I overwrite it?')),
                       changes={}, terminal='ask', facts=(old.strip(),))
        elif mode == 1:
            files = {src: new, f'{dest}/README': 'drop zone\n'}
            yield dict(id=f'act-collision-{i}', family='ask_collision', category='ask', behaviour='act-unambiguous',
                       request=req, files=files,
                       oracle=(ls(dest), run(f'cp {src} {target}'), done(f'Copied {src} to {target}; nothing was there before.')),
                       changes={target: new})
        else:
            files = {src: new, target: new}
            yield dict(id=f'same-collision-{i}', family='ask_collision', category='ask', behaviour='honest-done',
                       request=req, files=files,
                       oracle=(ls(dest), run(f'cmp {src} {target} && echo identical'),
                               done(f'{target} already has exactly the same content as {src} (cmp: identical), '
                                    'so nothing needed copying.')),
                       changes={}, facts=('identical',))


def fam_idempotent(g, n):
    """'Only if not already': read first; report an unchanged file honestly."""
    for i in range(n):
        place = g.pick(PLACES)
        key = g.choice(KEYS)
        cur = _value_for(g, key)
        path = g.choice((f'{place}.ini', f'conf/{place}.ini'))
        other = g.choice([k for k in KEYS if k != key])
        text = f'{other}=1\n{key}={cur}\n'
        if i % 2 == 0:
            req = g.choice(('Set {k} to {v} in {p} unless it already is. Tell me whether you changed it.',
                            'Make sure {k} is {v} in {p}; only edit if needed.')).format(k=key, v=cur, p=path)
            yield dict(id=f'idem-same-{i}', family='idempotent_edit', category='edit', behaviour='honest-done',
                       request=req, files={path: text},
                       oracle=(read(path), done(f'{key} is already {cur} in {path}, so I left the file unchanged.')),
                       changes={}, facts=(cur,))
        else:
            new = _other_value(g, key, cur)
            req = g.choice(('Set {k} to {v} in {p} unless it already is. Tell me whether you changed it.',
                            'Make sure {k} is {v} in {p}; only edit if needed.')).format(k=key, v=new, p=path)
            yield dict(id=f'idem-change-{i}', family='idempotent_edit', category='edit', behaviour='look-then-act',
                       request=req, files={path: text},
                       oracle=(read(path), edit(path, f'{key}={cur}', f'{key}={new}'),
                               done(f'{key} was {cur}, so I changed it to {new} in {path}.')),
                       changes={path: f'{other}=1\n{key}={new}\n'}, facts=(cur,))


def fam_conditional_copy(g, n):
    """Act only if a marker line matches exactly; a non-match is reported, not forced."""
    for i in range(n):
        thing = g.pick(THINGS)
        marker = g.choice(('READY', 'APPROVED', 'GO', 'SIGNED'))
        flag = g.choice(('status.flag', 'state.txt', 'gate.txt'))
        src, dest = f'{thing}.txt', f'outgoing/{thing}.txt'
        text = f'{thing} {g.choice(WORDS)}\n'
        req = g.choice(("Copy {s} to {d} only if {f} has a line that is exactly {m}.",
                        "If {f} contains the exact line {m}, copy {s} to {d}; otherwise leave everything.")).format(
                            s=src, d=dest, f=flag, m=marker)
        if i % 2 == 0:
            files = {src: text, flag: f'note\n{marker}\n', 'outgoing/README': 'out\n'}
            yield dict(id=f'cond-yes-{i}', family='conditional_copy', category='organise', behaviour='look-then-act',
                       request=req, files=files, source_page='grep',
                       oracle=(run(f'grep -x -- {marker} {flag}'), run(f'cp {src} {dest}'),
                               done(f'{flag} has the exact line {marker}, so I copied {src} to {dest}.')),
                       changes={dest: text}, facts=(marker,))
        else:
            files = {src: text, flag: f'note\n{marker}-PENDING\nnot {marker.lower()}\n', 'outgoing/README': 'out\n'}
            yield dict(id=f'cond-no-{i}', family='conditional_copy', category='organise', behaviour='honest-failure',
                       request=req, files=files, source_page='grep',
                       oracle=(run(f'grep -x -- {marker} {flag}'), read(flag),
                               done(f'{flag} has no line that is exactly {marker} (only {marker}-PENDING), '
                                    f'so I did not copy {src}.')),
                       changes={}, error_turns=(0,), facts=(f'{marker}-PENDING',))


def fam_awk_sum(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        path = f'{thing}.tsv'
        names = g.shuffle(WORDS)[:g.int(3, 7)]
        vals = [g.int(-40, 300) for _ in names]
        header = g.int(0, 1)
        body = ''.join(f'{w}\t{v}\n' for w, v in zip(names, vals))
        text = ('item\tamount\n' + body) if header else body
        prog = "NR>1 {s+=$2} END {print s}" if header else "{s+=$2} END {print s}"
        total = sum(vals)
        req = g.choice(('What is the total of the amounts in {p}?', 'Add up the second column of {p} for me.')).format(p=path)
        yield dict(id=f'awk-sum-{i}', family='awk_sum', category='inspect', behaviour='factual-answer',
                   request=req, files={path: text}, source_page='awk',
                   oracle=(read(path), run(f"awk -F'\\t' '{prog}' {path}"),
                           done(f'The amounts in {path} add up to {total}.')),
                   changes={}, facts=(str(total),))


def fam_set_diff(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        old, new = f'{thing}-before.txt', f'{thing}-after.txt'
        base = g.shuffle(PEOPLE)[:g.int(3, 6)]
        added = [p for p in g.shuffle(PEOPLE) if p not in base][:g.int(1, 3)]
        newlist = g.shuffle(base[1:] + added)
        if i % 2 == 0:
            out = f'{thing}-added.txt'
            req = f'Write the names that are in {new} but not in {old} to {out}, keeping their order.'
            result = [p for p in newlist if p not in base]
            yield dict(id=f'diff-added-{i}', family='set_diff', category='edit', behaviour='verify-before-done',
                       request=req, files={old: _lines(base), new: _lines(newlist)}, source_page='grep',
                       oracle=(run(f'grep -vxF -f {old} {new} > {out}'), read(out),
                               done(f'{out} lists {", ".join(result)}, the names only in {new}.')),
                       changes={out: _lines(result)}, facts=tuple(result))
        else:
            gone = base[0]
            req = f'Which names from {old} are missing in {new}? Do not create any files.'
            yield dict(id=f'diff-gone-{i}', family='set_diff', category='inspect', behaviour='factual-answer',
                       request=req, files={old: _lines(base), new: _lines(newlist)}, source_page='grep',
                       oracle=(run(f'grep -vxF -f {new} {old}'), done(f'Only {gone} is in {old} but not in {new}.')),
                       changes={}, facts=(gone,))


def fam_text_misc(g, n):
    for i in range(n):
        thing = g.pick(THINGS)
        mode = i % 4
        src = f'{thing}.txt'
        if mode == 0:
            rows = [f'{g.choice(WORDS)} {g.choice(PEOPLE)}' for _ in range(g.int(3, 5))]
            out = f'{thing}-unix.txt'
            req = f'Make {out}, a copy of {src} with Windows CRLF line endings turned into plain LF.'
            yield dict(id=f'crlf-{i}', family='text_crlf', category='edit', behaviour='verify-before-done',
                       request=req, files={src: ''.join(r + '\r\n' for r in rows)}, source_page='tr',
                       oracle=(run(f"tr -d '\\r' < {src} > {out}"), run(f'od -c {out} | head -n 2'),
                               done(f'Wrote {out} with LF endings only; od shows no \\r left.')),
                       changes={out: _lines(rows)}, facts=())
        elif mode == 1:
            rows = [g.choice(WORDS) for _ in range(g.int(5, 9))]
            a, b = g.int(2, 3), g.int(4, 5)
            out = f'{thing}-lines-{a}-{b}.txt'
            req = f'Save lines {a} to {b} of {src} (inclusive) as {out}.'
            yield dict(id=f'sed-range-{i}', family='text_range', category='edit', behaviour='verify-before-done',
                       request=req, files={src: _lines(rows)}, source_page='sed',
                       oracle=(run(f"sed -n '{a},{b}p' {src} > {out}"), read(out),
                               done(f"Wrote lines {a}-{b} of {src} to {out}, starting with '{rows[a - 1]}'.")),
                       changes={out: _lines(rows[a - 1:b])}, facts=(rows[a - 1],))
        elif mode == 2:
            vals = g.shuffle(WORDS)[:g.int(3, 5)]
            col = [g.choice(vals) for _ in range(g.int(6, 10))]
            rows = [f'{j},{v}' for j, v in enumerate(col, 1)]
            path = f'{thing}.csv'
            distinct = len(set(col))
            req = f'How many distinct values are in the second column of {path}?'
            yield dict(id=f'distinct-{i}', family='text_distinct', category='inspect', behaviour='factual-answer',
                       request=req, files={path: _lines(rows)}, source_page='cut',
                       oracle=(run(f'cut -d, -f2 {path} | sort -u'),
                               done(f'{path} has {distinct} distinct values in its second column: {", ".join(sorted(set(col)))}.')),
                       changes={}, facts=tuple(sorted(set(col))))
        else:
            word = g.choice(('BEGIN', 'Total', 'TODO', 'CANCELLED'))
            path = f'{thing}.log'
            rows = [f'{g.choice(PEOPLE)} {g.choice(WORDS)}' for _ in range(g.int(3, 6))]
            has = i % 8 == 3
            if has:
                rows.insert(g.int(0, len(rows)), f'{word} {g.choice(WORDS)}')
            req = f'Does any line of {path} start with {word}? Do not change the file.'
            if has:
                hit = next(r for r in rows if r.startswith(word))
                yield dict(id=f'starts-yes-{i}', family='text_starts', category='read-only', behaviour='factual-answer',
                           request=req, files={path: _lines(rows)}, source_page='grep',
                           oracle=(run(f"grep -n '^{word}' {path}"), done(f"Yes: '{hit}' starts with {word}.")),
                           changes={}, facts=(hit,))
            else:
                yield dict(id=f'starts-no-{i}', family='text_starts', category='read-only', behaviour='honest-failure',
                           request=req, files={path: _lines(rows)}, source_page='grep',
                           oracle=(run(f"grep -n '^{word}' {path}"), read(path),
                                   done(f'No, no line of {path} starts with {word}; the file is unchanged.')),
                           changes={}, error_turns=(0,))


def fam_ask_after_read(g, n):
    """The ambiguity only shows inside a file: two equally valid entries mean ask; one valid entry, act."""
    for i in range(n):
        thing = g.pick(THINGS)
        a, b = g.pick(PEOPLE, 2)
        qa, qb = g.int(20, 400), g.int(401, 900)
        orders = f'{thing}-orders.txt'
        out = f'{thing}-quantity.txt'
        req = g.choice(('Put the approved {t} quantity in {o} as a single number.',
                        'Write the signed-off {t} quantity to {o}, just the number.')).format(t=thing, o=out)
        if i % 2 == 0:
            text = f'order A: {qa} units, approved by {a}\norder B: {qb} units, approved by {b}\n'
            yield dict(id=f'ask-read-{i}', family='ask_after_read', category='ask', behaviour='ask-ambiguous',
                       request=req, files={orders: text},
                       oracle=(read(orders), ask(f'{orders} has two approved orders: {qa} units ({a}) and {qb} units '
                                                 f'({b}). Which quantity should go in {out}?')),
                       changes={}, terminal='ask', facts=(str(qa), str(qb)))
        else:
            text = f'order A: {qa} units, approved by {a}\norder B: {qb} units, rejected by {b}\n'
            yield dict(id=f'act-read-{i}', family='ask_after_read', category='ask', behaviour='act-unambiguous',
                       request=req, files={orders: text},
                       oracle=(read(orders), run(f"printf '%s\\n' {qa} > {out}"),
                               done(f'Only order A is approved, so {out} contains {qa}.')),
                       changes={out: f'{qa}\n'}, facts=(str(qa),))


def fam_inspect_misc(g, n):
    """Read-only checks answered from command output, never guessed."""
    for i in range(n):
        thing = g.pick(THINGS)
        mode = i % 4
        if mode == 0:
            a, b = f'old/{thing}.txt', f'new/{thing}.txt'
            text = f'{thing} {g.choice(WORDS)}\n'
            same = i % 8 == 0
            other = text if same else text.rstrip('\n') + ' \n'
            req = f'Are {a} and {b} byte-for-byte identical? Leave both files alone.'
            if same:
                yield dict(id=f'cmp-same-{i}', family='inspect_cmp', category='inspect', behaviour='factual-answer',
                           request=req, files={a: text, b: other}, source_page='cmp',
                           oracle=(run(f'cmp {a} {b} && echo identical'), done(f'Yes, cmp reports {a} and {b} identical.')),
                           changes={}, facts=('identical',))
            else:
                yield dict(id=f'cmp-diff-{i}', family='inspect_cmp', category='inspect', behaviour='factual-answer',
                           request=req, files={a: text, b: other}, source_page='cmp',
                           oracle=(run(f'cmp {a} {b}'), run(f'cmp -l {a} {b} | head -n 3; wc -c {a} {b}'),
                                   done(f'No, they differ: cmp found a difference, and {b} is one byte longer.')),
                           changes={}, error_turns=(0,), facts=('differ',))
        elif mode == 1:
            rows = []
            for _ in range(g.int(4, 9)):
                rows.append('' if g.int(0, 2) == 0 else f'{g.choice(WORDS)} {g.choice(PEOPLE)}')
            if all(rows):
                rows[1] = ''
            path = f'{thing}-journal.txt'
            count = sum(1 for r in rows if r)
            req = f'How many non-blank lines does {path} have?'
            yield dict(id=f'nonblank-{i}', family='inspect_nonblank', category='inspect', behaviour='factual-answer',
                       request=req, files={path: _lines(rows)}, source_page='grep',
                       oracle=(run(f"grep -c '[^[:space:]]' {path}"), done(f'{path} has {count} non-blank lines.')),
                       changes={}, facts=(str(count),))
        elif mode == 2:
            path = f'{thing}-snippet.txt'
            body = ' '.join(g.shuffle(WORDS)[:3])
            ends = i % 8 == 2
            text = body + ('\n' if ends else '')
            req = f'Does {path} end with a newline? Do not modify it.'
            answer = (f'Yes: the last byte of {path} is a newline (od shows \\n).' if ends
                      else f"No: {path} ends with '{body[-1]}', not a newline.")
            yield dict(id=f'lastbyte-{i}', family='inspect_lastbyte', category='inspect', behaviour='factual-answer',
                       request=req, files={path: text}, source_page='tail',
                       oracle=(run(f'tail -c 1 {path} | od -c'), done(answer)),
                       changes={}, facts=())
        else:
            folder = g.choice(('profile', 'home', 'settings'))
            key = g.choice(('theme', 'accent', 'layout'))
            value = g.choice(WORDS)
            hidden = f'{folder}/.{thing}rc'
            files = {hidden: f'{key}={value}\n', f'{folder}/README': f'{folder} files\n'}
            req = g.choice(('The {k} is set in a hidden file under {f}/. What is it? Do not change anything.',
                            'Find the {k} value in the dotfile inside {f}/ and tell me.')).format(k=key, f=folder)
            yield dict(id=f'hidden-{i}', family='inspect_hidden', category='read-only', behaviour='factual-answer',
                       request=req, files=files,
                       oracle=(f'tool fs.list\npath: {folder}\nshow_hidden: true', read(hidden),
                               done(f'{hidden} sets {key}={value}.')),
                       changes={}, facts=(value,))


def fam_verify_fix(g, n):
    """Check the output; if the first attempt kept a header row, fix it before saying done."""
    for i in range(n):
        thing = g.pick(THINGS)
        src = f'{thing}.csv'
        col = g.choice(('email', 'city', 'code'))
        def value(person):
            word = g.choice(WORDS)
            return {'email': f'{person}@{word}.org', 'city': word.title(), 'code': f'{word[:3].upper()}{g.int(10, 99)}'}[col]
        rows = [(p, value(p)) for p in g.shuffle(PEOPLE)[:g.int(3, 5)]]
        text = f'name,{col}\n' + ''.join(f'{a},{b}\n' for a, b in rows)
        out = f'{thing}-{col}s.txt'
        req = g.choice(('Write the {c} column of {s} to {o}, one value per line, without the header.',
                        'Extract the {c} values from {s} into {o} (no header line).')).format(c=col, s=src, o=out)
        result = [b for _, b in rows]
        yield dict(id=f'verify-fix-{i}', family='verify_fix', category='edit', behaviour='verify-before-done',
                   request=req, files={src: text}, source_page='cut',
                   oracle=(read(src), run(f'cut -d, -f2 {src} > {out}'), read(out),
                           run(f'tail -n +2 {src} | cut -d, -f2 > {out}'), read(out),
                           done(f'The first try kept the {col} header, so I redid it; {out} now starts with {result[0]}.')),
                   changes={out: _lines(result)}, facts=(result[0],), train_skip=(1,))


FAMILIES_R2 = {
    'ask_conflict': (fam_ask_conflict, 60), 'ask_collision': (fam_ask_collision, 60),
    'idempotent': (fam_idempotent, 40), 'conditional_copy': (fam_conditional_copy, 40),
    'awk_sum': (fam_awk_sum, 30), 'set_diff': (fam_set_diff, 40), 'text_misc': (fam_text_misc, 64),
    'ask_after_read': (fam_ask_after_read, 60), 'inspect_misc': (fam_inspect_misc, 64), 'verify_fix': (fam_verify_fix, 30),
}


# --- revision 4: decision-sprint treatment (training-fit and trace diagnosis, 2026-11-19) -----------

def fam_orient_output(g, n):
    """The request names an output that does not exist yet. Missing output is expected: list the
    inputs, then act on the only candidate or ask which of two candidates to use. Half the episodes
    start with a masked slip that probes the output path, so the recovery state is trained without
    teaching the probe itself or an 'X does not exist' question about an output."""
    pairs = (('north', 'south'), ('spring', 'autumn'), ('day', 'night'), ('east', 'west'), ('blue', 'green'))
    for i in range(n):
        place, thing = g.pick(PLACES), g.pick(THINGS)
        a, b = g.choice(pairs)
        out = f'{place}-{thing}-{g.choice(("handout", "sheet", "final", "print"))}.txt'
        rows = g.shuffle(WORDS)[:g.int(3, 5)]
        sort = i % 8 >= 4
        template = ('Write the {p} {t} list to {o}, sorted alphabetically.' if sort
                    else 'Copy the {p} {t} list into {o}.')
        req = template.format(p=place, t=thing, o=out)
        first, second = f'{place}-{thing}-{a}.txt', f'{place}-{thing}-{b}.txt'
        ambiguous, slip = i % 2 == 1, i % 4 >= 2
        files = {first: _lines(rows), 'README.md': f'# {place}\n'}
        if ambiguous:
            files[second] = _lines(g.shuffle(WORDS)[:3])
        prefix, errors = (), ()
        if slip:
            prefix = (read(out),) if i % 8 in (2, 3) else (find(out),)
            errors = (0,) if prefix[0].startswith('tool fs.read') else ()
        common = dict(family='orient_output', category='ask', request=req, files=files, error_turns=errors,
                      train_skip=(0,) if slip else (), meta={'output': out})
        if ambiguous:
            yield dict(id=f'orient-ask-{i}', behaviour='ask-ambiguous', terminal='ask', changes={},
                       oracle=prefix + (ls('.'), ask(f'There are two {place} {thing} lists, {first} and {second}. '
                                                      f'Which one should go into {out}?')),
                       facts=(first, second), **common)
        else:
            result = sorted(rows) if sort else rows
            command = f'sort {first} > {out}' if sort else f'cp {first} {out}'
            yield dict(id=f'orient-act-{i}', behaviour='act-unambiguous', changes={out: _lines(result)},
                       oracle=prefix + (ls('.'), run(command),
                                        done(f'{first} is the only {place} {thing} list; wrote it '
                                             f'{"sorted " if sort else ""}to {out}.')),
                       facts=(first,), **common)


FAMILIES_R4 = {'orient_output': (fam_orient_output, 120)}


def generate(seed=DEFAULT_SEED, scale=1.0, families=None, revision=1):
    global _REV
    _REV = revision
    out = []
    table = {**FAMILIES, **(FAMILIES_R2 if revision >= 2 else {}), **(FAMILIES_R4 if revision >= 4 else {})}
    for name, (fn, count) in table.items():
        if families and name not in families:
            continue
        g = Gen(seed, name)
        for spec in fn(g, max(1, round(count * scale))):
            spec['id'] = 'v2-' + spec['id']
            spec['oracle'] = tuple(_canon(line) for line in spec['oracle'])
            spec['changes'] = dict(sorted(spec['changes'].items()))
            out.append(Example(**spec))
    return out


# --- grading ---------------------------------------------------------------------------------

def stdout_text(observation):
    """Successful output content only: no exit line, no line-count header, no changes/policy footer."""
    lines = observation.split('\n')
    if not lines or not lines[0].startswith('exit=0'):
        return ''
    body = []
    for line in lines[1:]:
        if line.startswith('changes: ') or line.startswith('policy: '):
            break
        if _HEADER.match(line):
            continue
        body.append(line)
    return '\n'.join(body)


def grade(task, *, terminal, answer, changes, events, original_unchanged):
    reasons = []
    if original_unchanged is not True:
        reasons.append('original workspace changed')
    if changes != task.changes:
        reasons.append(f'changes {changes!r} != expected {task.changes!r}')
    if terminal != task.terminal or not answer:
        reasons.append(f'terminal {terminal!r} != {task.terminal!r}')
    if not events:
        reasons.append('no inspection before the terminal action')
        return reasons
    errors = tuple(i for i, (_, _, error) in enumerate(events) if error)
    if errors != task.error_turns:
        reasons.append(f'error turns {errors} != {task.error_turns}')
    if any(loop.policy_of(obs) != 'ok' for _, obs, _ in events[:-1]):
        reasons.append('non-final step left the ok policy')
    if loop.policy_of(events[-1][1]) != task.policy_end:
        reasons.append(f'final policy {loop.policy_of(events[-1][1])} != {task.policy_end}')
    low = (answer or '').casefold()
    if task.policy_end == 'pending' and PENDING not in low:
        reasons.append('pending change not reported as awaiting approval')
    if task.policy_end == 'rejected' and 'rejected' not in low:
        reasons.append('rejection not reported')
    if task.terminal == 'ask' and not (answer or '').rstrip().endswith('?'):
        reasons.append('ask is not a question')
    evidence = '\n'.join(stdout_text(obs) for _, obs, error in events if not error)
    if task.error_turns:
        evidence += '\n' + '\n'.join(obs for _, obs, error in events if error)
    for fact in task.facts:
        if fact.casefold() not in low:
            reasons.append(f'answer omits fact {fact!r}')
        if fact not in evidence:
            reasons.append(f'fact {fact!r} not grounded in an observation')
    return reasons


# --- verification pipeline -------------------------------------------------------------------

def _record(task, reference):
    return dict(version=protocol.INTERFACE_VERSION, request=task.request, terminal=reference['terminal'],
                answer=reference['answer'], turns=reference['events'])


def verify_one(task):
    """Gold run + independent replay on fresh guarded fixtures. Returns (status, payload)."""
    tools = _tools()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reference = fast12_runner.run_oracle(root / 'reference', task, tools, grade)
        if reference['infra_error'] is not None:
            return 'infra', {'id': task.id, 'reason': reference['infra_error']}
        if reference['failures']:
            return 'gold', {'id': task.id, 'reason': reference['failures']}
        saved = _record(task, reference)
        lines = tuple(m['content'] for m in episodes.to_messages(saved, tools) if m['role'] == 'assistant')
        if lines != task.oracle:
            return 'gold', {'id': task.id, 'reason': 'recorded actions do not round-trip to the oracle'}
        replay = fast12_runner.run_episode(root / 'replay', task, fast12_runner._scripted(lines, tools), tools, grade)
    if replay != reference:
        return 'replay', {'id': task.id, 'reason': 'replay record differs from reference'}
    return 'ok', {'id': task.id, 'record': saved, 'staged': reference['changes']}


def _norm_key(entry):
    return (split_audit._normalize_text(entry['request']), split_audit._normalize_files(entry['files']))


def dedup(examples):
    """Drop exact and near duplicates inside the corpus and against development tasks."""
    dev = development_rows()
    seen_req = {row['request'] for row in dev}
    seen_files = {tuple(sorted(row['files'].items())) for row in dev}
    seen_norm = {_norm_key(row) for row in dev}
    kept, dropped = [], []
    for ex in examples:
        m = ex.manifest()
        keys = (m['request'], tuple(sorted(m['files'].items())), _norm_key(m))
        if keys[0] in seen_req or keys[1] in seen_files or keys[2] in seen_norm:
            dropped.append(ex.id)
            continue
        seen_req.add(keys[0])
        seen_files.add(keys[1])
        seen_norm.add(keys[2])
        kept.append(ex)
    return kept, dropped


def gate(examples):
    rows = development_rows() + [ex.manifest() for ex in examples]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'candidate.json'
        path.write_text(json.dumps(rows), encoding='utf8')
        pin = (ROOT / 'dev/holdout_manifest.sha256').read_text().split()[0]
        return eval_gate.verify(ROOT / 'dev/holdout_manifest.json', pin, path)


def next_action_rows(messages, skip=()):
    targets = [i for i, message in enumerate(messages) if message['role'] == 'assistant']
    return [messages[:i + 1] for n, i in enumerate(targets) if n not in skip]


def build(out, *, seed=DEFAULT_SEED, scale=1.0, families=None, workers=12, revision=1):
    generated = generate(seed, scale, families, revision)
    stages = {'generated': len(generated)}
    kept, dup_ids = dedup(generated)
    stages['dedup'] = len(kept)
    split = gate(kept)
    if not split['ok']:
        raise SystemExit(f"split gate refused corpus v2: {split['reason']}")
    stages['leakage_gate'] = len(kept)
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for task, (status, payload) in zip(kept, pool.map(verify_one, kept, chunksize=4)):
            results[task.id] = (status, payload)
    failures = {k: [] for k in ('infra', 'gold', 'replay')}
    accepted = []
    for task in kept:
        status, payload = results[task.id]
        if status == 'ok':
            accepted.append((task, payload))
        else:
            failures[status].append(payload)
    stages['gold_ok'] = len(kept) - len(failures['gold']) - len(failures['infra'])
    stages['replay_match'] = len(accepted)
    tools = _tools()
    rows, evidence = [], []
    for task, payload in accepted:
        messages = episodes.to_messages(payload['record'], tools)
        rows.extend(dict(episode=task.id, messages=row) for row in next_action_rows(messages, task.train_skip))
        evidence.append(dict(task=task.manifest(), family=task.family, category=task.category,
                             behaviour=task.behaviour, source=task.provenance(), record=payload['record'],
                             staged=payload['staged'], original_unchanged=True))
    stages['episodes'] = len(evidence)
    stages['next_action_rows'] = len(rows)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    meta = dict(corpus_version=CORPUS_VERSION, interface=protocol.INTERFACE_VERSION, seed=seed, scale=scale,
                families=sorted(families) if families else None, revision=revision, split_gate=split)
    (out / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n')
    (out / 'train.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf8')
    (out / 'effects.json').write_text(json.dumps(evidence, indent=1) + '\n', encoding='utf8')
    (out / 'rejected.json').write_text(json.dumps(dict(duplicates=dup_ids, **failures), indent=1) + '\n')
    card = datacard(generated, kept, accepted, failures, dup_ids, stages, meta, rows)
    (out / 'datacard.json').write_text(json.dumps(card, indent=2) + '\n')
    return card


def datacard(generated, kept, accepted, failures, dup_ids, stages, meta, rows):
    by = lambda items, attr: dict(sorted(Counter(getattr(x, attr) for x in items).items()))  # noqa: E731
    ok = [task for task, _ in accepted]
    gen_family = by(generated, 'family')
    acc_family = by(ok, 'family')
    rows_by_kind = Counter(row['messages'][-1]['content'].split('\n', 1)[0].split(' ')[0] for row in rows)
    return dict(meta=meta, stages=stages,
                family=[dict(family=f, generated=gen_family[f], accepted=acc_family.get(f, 0)) for f in gen_family],
                category=by(ok, 'category'), behaviour=by(ok, 'behaviour'), terminal=by(ok, 'terminal'),
                policy_end=by(ok, 'policy_end'), tldr_attributed=sum(t.source_page is not None for t in ok),
                target_action_kinds=dict(sorted(rows_by_kind.items())),
                failures={k: len(v) for k, v in failures.items()}, duplicates=len(dup_ids))


def verified_rows(path):
    """Trainer entry point: regenerate the corpus, re-check every stored record, return messages.

    Refuses on any mismatch between stored evidence, the deterministic generator, the grader and
    train.jsonl, and re-runs the held-out split gate on the accepted examples.
    """
    path = Path(path)
    meta = json.loads((path / 'meta.json').read_text())
    if meta.get('corpus_version') != CORPUS_VERSION or meta.get('interface') != protocol.INTERFACE_VERSION:
        raise ValueError('corpus or interface version mismatch')
    examples = {ex.id: ex for ex in generate(meta['seed'], meta['scale'], meta['families'], meta.get('revision', 1))}
    evidence = json.loads((path / 'effects.json').read_text())
    tools = _tools()
    accepted, expected = [], []
    for entry in evidence:
        task = examples.get(entry['task']['id'])
        if task is None or entry['task'] != task.manifest() or entry['source'] != task.provenance():
            raise ValueError(f"effect evidence does not match the generator: {entry['task']['id']}")
        record = entry['record']
        if (entry['staged'] != task.changes or entry['original_unchanged'] is not True
                or record['request'] != task.request or record['terminal'] != task.terminal):
            raise ValueError(f'effect evidence mismatch: {task.id}')
        events = [(protocol.Action(**t['action']), t['observation'], t['is_error']) for t in record['turns']]
        if grade(task, terminal=record['terminal'], answer=record['answer'], changes=entry['staged'],
                 events=events, original_unchanged=True):
            raise ValueError(f'stored record fails its grader: {task.id}')
        messages = episodes.to_messages(record, tools)
        if tuple(m['content'] for m in messages if m['role'] == 'assistant') != task.oracle:
            raise ValueError(f'stored actions differ from the oracle: {task.id}')
        accepted.append(task)
        expected.extend(dict(episode=task.id, messages=row) for row in next_action_rows(messages, task.train_skip))
    if len({t.id for t in accepted}) != len(accepted):
        raise ValueError('duplicate episode in evidence')
    split = gate(accepted)
    if not split['ok']:
        raise ValueError(f"split gate failed: {split['reason']}")
    actual = [json.loads(line) for line in (path / 'train.jsonl').read_text().splitlines()]
    if actual != expected:
        raise ValueError('training rows do not match sandbox effect evidence')
    return [row['messages'] for row in actual]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('out', type=Path)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--scale', type=float, default=1.0)
    parser.add_argument('--families', help='comma-separated subset (debugging)')
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--revision', type=int, default=1, choices=(1, 2, 3, 4))
    args = parser.parse_args(argv)
    families = set(args.families.split(',')) if args.families else None
    card = build(args.out, seed=args.seed, scale=args.scale, families=families, workers=args.workers,
                 revision=args.revision)
    print(json.dumps(card['stages']), flush=True)
    return 0 if card['stages']['episodes'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
