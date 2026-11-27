"""Revision 15 families (interface v8, docs/plan/INTERFACE-V8.md). No development or held-out
paths, labels or rows.

Revision 15 is revision 14 recorded under interface v8, where bulk renames by one of the two
fs.rename rules (spaces_to_dashes, zero_pad) use the typed tool, plus:

  - rename_spaces: spaces in file names in a folder become dashes (one explicit fs.rename call,
    optionally scoped with glob), then a bare `done` right after the pending preview -- the
    untrained model's habit was to emit an invalid action there instead.
  - rename_zero_pad: the last run of digits before the extension is left-padded to a stated
    width; some files are already at width and are left alone; some calls are glob-scoped by
    extension or prefix.
  - rename_collision: fs.rename refuses the whole batch on any collision (an existing target, or
    two sources landing on the same name); the episode ends with `ask`, naming the conflicting
    names, and nothing is staged.
  - rename_twin: near-misses where fs.rename is *not* the right tool: a single named file
    (`mv`), a copy into another folder with dashes (`mkdir -p` + `cp`, originals kept),
    lowercasing names, or stripping a literal prefix (both unsupported rules) -- scripted `mv`.

No existing revision-14 family does a bulk rename by spaces_to_dashes or zero_pad, so none are
re-recorded; `rename_pending` (one file) and `move_glob_pending` (same names, new folder) are
untouched -- neither matches fs.rename's two rules.
"""
import hashlib


def _sha8(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:8]


def tool(name, **args):
    return '\n'.join([f'tool {name}', *(f'{k}: {str(v).lower() if isinstance(v, bool) else v}'
                                         for k, v in args.items())])


def _pad(name, width):
    if '.' in name and not name.startswith('.'):
        stem, _, ext = name.rpartition('.')
        ext = '.' + ext
    else:
        stem, ext = name, ''
    import re
    matches = list(re.finditer(r'[0-9]+', stem))
    if not matches:
        return name
    last = matches[-1]
    digits = last.group(0)
    if len(digits) >= width:
        return name
    return stem[:last.start()] + digits.zfill(width) + stem[last.end():] + ext


def families(c):
    def _preview(folder, pairs):
        count = len(pairs)
        lines = [f'renamed {count} file{"s" if count != 1 else ""} in {folder}:']
        for old, new in sorted(pairs):
            lines.append(f'  {old} -> {new}')
        return '\n'.join(lines)

    def rename_spaces(g, n):
        exts = ('.png', '.jpg', '.txt', '.wav', '.mp4', '.pdf', '.csv', '.md')
        templates_glob = (
            'In {f}/, replace the spaces in the {e} file names with dashes.',
            'Rename the {e} files in {f}/ so spaces become dashes.',
            '{f}/: swap spaces for dashes in the {e} file names.',
            'For every {e} file in {f}/, turn spaces in the name into dashes.',
        )
        templates_all = (
            'Rename the files in {f}/ so spaces become dashes.',
            'In {f}/, replace spaces in file names with dashes.',
            '{f}/: dash out the spaces in every file name.',
            'Swap spaces for dashes in the names of the files in {f}/.',
        )
        example_glob = ('In {f}/, replace spaces with dashes in the {e} names '
                         "(for example 'one two{e}' becomes 'one-two{e}').")
        for i in range(n):
            place, thing = g.pick(c.PLACES), g.pick(c.THINGS)
            folder = f'{place}-{thing}'
            use_glob = i % 3 != 0
            ext = g.choice(exts)
            count = g.int(2, 6)
            words = g.shuffle(c.WORDS)[:count + 2]
            names = [f'{words[k]} {words[k + 1]}{ext}' for k in range(count)]
            files = {f'{folder}/{n_}': f'{n_} text\n' for n_ in names}
            # distractor: a file with no spaces, same extension, left alone
            flat = f'{folder}/{words[-1]}{ext}'
            files[flat] = 'flat\n'
            extra = i % 5 == 0
            other_folder = g.pick(c.PLACES)
            if extra:
                files[f'{other_folder}/{words[-2]} {words[-1]}{ext}'] = 'elsewhere\n'
            pairs = [(f'{folder}/{n_}', f"{folder}/{n_.replace(' ', '-')}") for n_ in names]
            if use_glob:
                req = g.choice(templates_glob if i % 7 else (example_glob,)).format(f=folder, e=ext)
                rename_args = dict(path=folder, rule='spaces_to_dashes', glob=f'*{ext}')
            else:
                req = g.choice(templates_all).format(f=folder)
                rename_args = dict(path=folder, rule='spaces_to_dashes')
            changes = {}
            for old, new in pairs:
                changes[old] = None
                changes[new] = files[old]
            oracle = (c.ls(folder), tool('fs.rename', **rename_args), 'done')
            yield dict(id=f'r15-spaces-{i}', family='rename_spaces', category='organise',
                       behaviour='pending-stop', request=req, files=files, oracle=oracle,
                       changes=changes, error_turns=(1,), policy_end='pending')

    def rename_zero_pad(g, n):
        stems = ('page', 'scan', 'img', 'track', 'chapter', 'invoice', 'receipt', 'photo', 'frame', 'slide')
        exts = ('.txt', '.png', '.jpg', '.pdf', '.csv', '.mp3')
        templates = (
            'In {f}/, pad the numbers in the {s} file names to {w} digits.',
            'Zero-pad the numbers in {f}/ to {w} digits.',
            '{f}/: pad every number to {w} digits in the file names.',
            'Make the numbers in the {f}/ file names {w} digits wide, with leading zeros.',
        )
        example = ("In {f}/, pad the numbers to {w} digits (so '{a}' becomes '{b}')."
                   )
        for i in range(n):
            place, thing = g.pick(c.PLACES), g.pick(c.THINGS)
            folder = f'{place}-{thing}'
            stem = g.choice(stems)
            ext = g.choice(exts)
            width = (2, 3, 4)[i % 3]
            total = g.int(3, 8)
            nums = list(range(1, total + 1))
            # one file already at width, to be left alone
            already_idx = g.int(0, total - 1)
            already_num = int('9' * width) if width <= 4 else 9999
            files = {}
            pairs = []
            for k, num in enumerate(nums):
                use_num = already_num if k == already_idx else num
                name = f'{stem}{use_num}{ext}'
                files[f'{folder}/{name}'] = f'content {use_num}\n'
                new_name = _pad(name, width)
                if new_name != name:
                    pairs.append((f'{folder}/{name}', f'{folder}/{new_name}'))
            use_glob = i % 4 == 0
            if not pairs:
                continue
            if use_glob:
                req = g.choice(templates).format(f=folder, s=stem, w=width)
                glob = f'{stem}*{ext}'
                rename_args = dict(path=folder, rule='zero_pad', width=width, glob=glob)
            elif i % 11 == 0:
                a, b = f'{stem}1{ext}', _pad(f'{stem}1{ext}', width)
                req = example.format(f=folder, w=width, a=a, b=b)
                rename_args = dict(path=folder, rule='zero_pad', width=width)
            else:
                req = g.choice(templates).format(f=folder, s=stem, w=width)
                rename_args = dict(path=folder, rule='zero_pad', width=width)
            distractor = f'{folder}/notes.log'
            files[distractor] = 'notes\n'
            changes = {}
            for old, new in pairs:
                changes[old] = None
                changes[new] = files[old]
            oracle = (c.ls(folder), tool('fs.rename', **rename_args), 'done')
            yield dict(id=f'r15-zeropad-{i}', family='rename_zero_pad', category='organise',
                       behaviour='pending-stop', request=req, files=files, oracle=oracle,
                       changes=changes, error_turns=(1,), policy_end='pending')

    def rename_collision(g, n):
        exts = ('.txt', '.png', '.csv', '.pdf')
        for i in range(n):
            place, thing = g.pick(c.PLACES), g.pick(c.THINGS)
            folder = f'{place}-{thing}'
            ext = g.choice(exts)
            kind = i % 2
            if kind == 0:  # existing target
                width = 2
                req = g.choice(('In {f}/, pad the page numbers to two digits.',
                                 'Zero-pad the numbers in {f}/ to two digits.')).format(f=folder)
                src = f'{folder}/page1{ext}'
                target = f'{folder}/page01{ext}'
                files = {src: 'one\n', target: 'old one\n'}
                ask_text = f'ask\n{target} already exists; which should keep the name?'
                oracle = (c.ls(folder), tool('fs.rename', path=folder, rule='zero_pad', width=width), ask_text)
            else:  # two sources collide
                width = 3
                req = g.choice(('In {f}/, pad the numbers to three digits.',
                                 'Zero-pad the file numbers in {f}/ to three digits.')).format(f=folder)
                a, b = f'{folder}/page1{ext}', f'{folder}/page01{ext}'
                files = {a: 'first\n', b: 'second\n', f'{folder}/page2{ext}': 'two\n'}
                target = f'{folder}/page001{ext}'
                ask_text = f'ask\n{a} and {b} both become {target}; which should keep the name?'
                oracle = (c.ls(folder), tool('fs.rename', path=folder, rule='zero_pad', width=width), ask_text)
            yield dict(id=f'r15-collision-{i}', family='rename_collision', category='organise',
                       behaviour='pending-stop', request=req, files=files, oracle=oracle,
                       changes={}, error_turns=(1,), terminal='ask', policy_end='ok')

    def rename_twin(g, n):
        kind_count = 4
        for i in range(n):
            place, thing = g.pick(c.PLACES), g.pick(c.THINGS)
            folder = f'{place}-{thing}'
            other = g.pick(c.PLACES)
            kind = i % kind_count
            if kind == 0:  # single named file
                a = f'{folder}/old_{thing}.txt'
                b = f'{folder}/new_{thing}.txt'
                files = {a: 'content\n', f'{folder}/keep.txt': 'keep\n'}
                req = g.choice((f'Rename {a} to {b}.', f'Change the name of {a} to {b}.'))
                oracle = (c.ls(folder), c.run(f'mv -- {a} {b}'), c.done('Renamed.'))
                yield dict(id=f'r15-twin-single-{i}', family='rename_twin', category='organise',
                           behaviour='pending-stop', request=req, files=files, oracle=oracle,
                           changes={a: None, b: 'content\n'}, error_turns=(1,), policy_end='pending')
            elif kind == 1:  # copy with dashes, keep originals
                words = g.shuffle(c.WORDS)[:2]
                names = [f'{w} plan.txt' for w in words]
                files = {f'{folder}/{n_}': f'{n_} text\n' for n_ in names}
                req = g.choice((f'Copy the files in {folder}/ into {other}/, replacing spaces '
                                 'with dashes in the new names.',
                                 f'Make dashed-name copies of everything in {folder}/ inside {other}/, '
                                 'keeping the originals.'))
                cp_cmds = ' && '.join(f"cp -- '{folder}/{n_}' '{other}/{n_.replace(' ', '-')}'" for n_ in names)
                oracle = (c.ls(folder), c.run(f'mkdir -p {other} && {cp_cmds}'), c.done('Copied.'))
                changes = {other: '<dir added>'}
                for n_ in names:
                    changes[f'{other}/{n_.replace(" ", "-")}'] = files[f'{folder}/{n_}']
                yield dict(id=f'r15-twin-copy-{i}', family='rename_twin', category='organise',
                           behaviour='look-then-act', request=req, files=files, oracle=oracle,
                           changes=changes, policy_end='ok')
            elif kind == 2:  # lowercase names
                words = g.shuffle(c.WORDS)[:2]
                names = [f'IMG_{w.capitalize()}.png' for w in words]
                files = {f'{folder}/{n_}': f'{n_} data\n' for n_ in names}
                req = g.choice((f'Lowercase all the file names in {folder}/.',
                                 f'Make every file name in {folder}/ lowercase.'))
                mv_cmds = ' && '.join(f'mv -- {folder}/{n_} {folder}/{n_.lower()}' for n_ in names)
                oracle = (c.ls(folder), c.run(mv_cmds),
                          c.done(f'The {len(names)} renames are staged and {c.PENDING}.'))
                changes = {}
                for n_ in names:
                    changes[f'{folder}/{n_}'] = None
                    changes[f'{folder}/{n_.lower()}'] = files[f'{folder}/{n_}']
                yield dict(id=f'r15-twin-lowercase-{i}', family='rename_twin', category='organise',
                           behaviour='pending-stop', request=req, files=files, oracle=oracle,
                           changes=changes, error_turns=(1,), policy_end='pending')
            else:  # strip a literal prefix
                words = g.shuffle(c.WORDS)[:2]
                prefix = g.choice(('draft-', 'old_', 'tmp_'))
                names = [f'{prefix}{w}.txt' for w in words]
                files = {f'{folder}/{n_}': f'{n_} body\n' for n_ in names}
                files[f'{folder}/final.txt'] = 'final\n'
                req = g.choice((f"Remove the '{prefix}' prefix from the file names in {folder}/.",
                                f"Strip the '{prefix}' prefix off every file name in {folder}/."))
                mv_cmds = ' && '.join(
                    f'mv -- {folder}/{n_} {folder}/{n_[len(prefix):]}' for n_ in names)
                oracle = (c.ls(folder), c.run(mv_cmds),
                          c.done(f'The {len(names)} renames are staged and {c.PENDING}.'))
                changes = {}
                for n_ in names:
                    changes[f'{folder}/{n_}'] = None
                    changes[f'{folder}/{n_[len(prefix):]}'] = files[f'{folder}/{n_}']
                yield dict(id=f'r15-twin-prefix-{i}', family='rename_twin', category='organise',
                           behaviour='pending-stop', request=req, files=files, oracle=oracle,
                           changes=changes, error_turns=(1,), policy_end='pending')

    return {'rename_spaces': (rename_spaces, 50), 'rename_zero_pad': (rename_zero_pad, 50),
            'rename_collision': (rename_collision, 20), 'rename_twin': (rename_twin, 40)}
