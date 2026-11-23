"""Additive interface-v5 training families (revision 11). No development or held-out paths, labels or rows.

Written from the focus-r11 diagnosis (docs/data/FOCUS-R11-DIAGNOSIS.md), which used only the
weakness names 2.0's card lists:
  - a file without a final newline is now visible (`(no newline at end of output)`): append
    after a newline when the marker is there, plainly when it is not, and repair a joined line;
  - a named file that does not exist (`No such file: PATH`): ask, never change a look-alike;
    the contrast family edits the named file when it does exist beside look-alikes;
  - counts that need precision: exact lines (-x), whole words (-w), rows without the header;
  - exact multi-line file creation, with empty and indented lines.
Everything else in revision 11 is revision 10, re-recorded under interface v5.
"""


def block(key, text):
    return f'{key} <<<\n{text.rstrip(chr(10))}\n>>>'


def edit_block(path, old, new):
    return f'tool fs.edit\npath: {path}\n{block("old", old)}\n{block("new", new)}'


def _q(items):
    return ' '.join("'" + item + "'" for item in items)


def families(c):
    def append_marker(g, n):
        """Read, see (or not) the missing-newline marker, append accordingly; a third repair a joined line."""
        for i in range(n):
            words = g.pick(c.WORDS, 4)
            shape = i % 3
            if shape == 0:
                path, body = f'{words[0]}-names.txt', [words[1], words[2]]
                new = [words[3]]
                req = f'Add {new[0]} as a new last line of {path}.'
            elif shape == 1:
                path, body = f'{words[0]}.csv', ['item,qty', f'{words[1]},{g.int(1, 9)}']
                new = [f'{words[2]},{g.int(1, 9)}', f'{words[3]},{g.int(1, 9)}']
                req = f'Append the rows {new[0]} and {new[1]} to {path}.'
            else:
                path, body = f'{words[0]}-todo.md', [f'# {words[0]}', f'- {words[1]}']
                new = [f'- {words[2]}', f'- {words[3]}']
                req = f'Add "{new[0][2:]}" and "{new[1][2:]}" as list items at the end of {path}.'
            eol = (i // 3) % 4 == 3  # a quarter end in a newline: no marker, plain append
            text = '\n'.join(body) + ('\n' if eol else '')
            after = '\n'.join(body) + '\n' + ''.join(x + '\n' for x in new)
            repair = not eol and (i // 3) % 4 == 1
            steps, skip = [c.read(path)], ()
            if eol:
                steps.append(c.run(f"printf '%s\\n' {_q(new)} >> {path}"))
            elif repair:
                # the slip: appending without the newline the marker called for, then the repair
                steps.append(c.run(f"printf '%s\\n' {_q(new)} >> {path}"))
                steps.append(c.read(path))
                joined = body[-1] + new[0]
                steps.append(edit_block(path, joined + '\n', body[-1] + '\n' + new[0] + '\n'))
                skip = (1,)
            else:
                steps.append(c.run(f"printf '\\n' >> {path} && printf '%s\\n' {_q(new)} >> {path}"))
            steps.append(c.read(path))
            yield dict(id=f'r11-eol-{i}', family='append_after_marker', category='edit',
                       behaviour='recover-after-error' if repair else 'look-then-act', request=req,
                       files={path: text}, changes={path: after}, oracle=(*steps, c.done('Appended.')),
                       train_skip=skip)

    def named_missing(g, n):
        """The named file is absent and look-alikes exist: look, then ask; change nothing."""
        for i in range(n):
            words = g.pick(c.WORDS, 3)
            stem = words[0]
            ext = g.choice(('txt', 'md', 'conf', 'ini', 'csv'))
            kind = i % 4
            if kind == 0:
                missing, near = f'{stem}-final.{ext}', [f'{stem}-draft.{ext}', f'{stem}-old.{ext}']
            elif kind == 1:
                year = g.int(2020, 2030)
                missing, near = f'{stem}-{year}.{ext}', [f'{stem}-{year - 2}.{ext}', f'{stem}-{year - 1}.{ext}']
            elif kind == 2:
                missing, near = f'{stem}.local.{ext}', [f'{stem}.{ext}', f'{stem}.dev.{ext}']
            else:
                missing, near = f'{stem}.sh', [f'{stem}.py', f'{words[1]}.sh']
            key = words[2]
            req = g.choice(('Set {k} to on in {m}.', 'Add a line "{k}" to the end of {m}.',
                            'In {m}, change {k} to 5.', 'Remove the {k} line from {m}.')).format(k=key, m=missing)
            files = {name: f'{key}={g.int(1, 4)}\n' for name in near}
            look = c.read(missing) if i % 2 == 0 else c.find(missing)
            question = (f'{missing} does not exist; I found {near[0]} and {near[1]}. '
                        f'Which file should I change, or should I create {missing}?')
            yield dict(id=f'r11-missing-{i}', family='named_file_missing', category='recovery',
                       behaviour='honest-failure', request=req, files=files, changes={}, terminal='ask',
                       oracle=(look, c.ls(), c.ask(question)), error_turns=(0,) if i % 2 == 0 else (),
                       facts=(missing,) if i % 2 == 0 else (near[0],))  # facts must appear in an observation

    def named_present(g, n):
        """Contrast: the named file exists beside look-alikes; edit exactly that one."""
        for i in range(n):
            words = g.pick(c.WORDS, 3)
            stem, key = words[0], words[1]
            ext = g.choice(('txt', 'conf', 'ini'))
            target = g.choice((f'{stem}.local.{ext}', f'{stem}-final.{ext}', f'{stem}-{g.int(2020, 2030)}.{ext}'))
            others = [f'{stem}.{ext}', f'{stem}-copy.{ext}']
            old, new = g.int(1, 40), g.int(41, 99)
            files = {name: f'{key}={old}\n' for name in [target, *others]}
            req = f'Change {key} to {new} in {target}. Leave the other {stem} files alone.'
            yield dict(id=f'r11-present-{i}', family='named_file_present', category='edit',
                       behaviour='look-then-act', request=req, files=files,
                       changes={target: f'{key}={new}\n'},
                       oracle=(c.read(target), c.edit(target, f'{key}={old}', f'{key}={new}'), c.read(target),
                               c.done('Changed.')))

    def precise_count(g, n):
        """Questions whose naive count is wrong: exact lines, whole words, rows without a header."""
        for i in range(n):
            words = g.pick(c.WORDS, 4)
            kind = i % 3
            if kind == 0:
                word = g.choice(('yes', 'no', 'done', 'open', 'paid', 'late'))
                near = {'yes': ['yesterday', 'yes?'], 'no': ['none', 'not yet'], 'done': ['undone', 'done?'],
                        'open': ['reopened', 'open?'], 'paid': ['unpaid', 'prepaid'], 'late': ['later', 'not late']}[word]
                rows = [word] * g.int(1, 5) + near + [words[1]] * g.int(0, 2)
                rows = g.shuffle(rows)
                path = f'{words[0]}-status.txt'
                count = rows.count(word)
                req = f'How many lines of {path} are exactly "{word}"?'
                cmd = f"grep -cx -- '{word}' {path}"
            elif kind == 1:
                word = g.choice(('cat', 'red', 'map', 'pen', 'tea', 'log'))
                longer = {'cat': 'catalog', 'red': 'reduce', 'map': 'mapping', 'pen': 'pencil', 'tea': 'team',
                          'log': 'logbook'}[word]
                rows = [f'{words[1]} {word}'] * g.int(1, 4) + [f'{words[2]} {longer}'] * g.int(1, 3) + [words[3]]
                rows = g.shuffle(rows)
                path = f'{words[0]}-notes.txt'
                count = sum(1 for r in rows if word in r.split())
                req = f'How many lines in {path} contain the word "{word}" (not as part of a longer word)?'
                cmd = f"grep -cw -- '{word}' {path}"
            else:
                path = f'{words[0]}.csv'
                rows = ['name,value'] + [f'{w},{g.int(1, 99)}' for w in g.pick(c.WORDS, g.int(2, 6))]
                count = len(rows) - 1
                req = g.choice(('How many entries does {p} list, not counting the header?',
                                'How many data rows are in {p}?')).format(p=path)
                cmd = f'tail -n +2 {path} | wc -l'
            yield dict(id=f'r11-count-{i}', family='precise_count', category='inspect',
                       behaviour='factual-answer', request=req, files={path: c._lines(rows)}, changes={},
                       oracle=(c.read(path), c.run(cmd), c.done(str(count))), facts=(str(count),))

    def exact_create(g, n):
        """Create a file with exact lines, including an empty line or an indented one."""
        for i in range(n):
            words = g.pick(c.WORDS, 4)
            if i % 2 == 0:
                path = f'{words[0]}-letter.txt'
                lines = [f'Dear {words[1].title()},', '', f'The {words[2]} arrives soon.', '', 'Thanks']
                req = (f'Create {path} with exactly these lines: "{lines[0]}", an empty line, "{lines[2]}", '
                       f'another empty line, and "Thanks".')
            else:
                path = f'{words[0]}.yaml'
                lines = [f'{words[0]}:', f'  name: {words[1]}', f'  size: {g.int(1, 9)}']
                req = f'Create {path} containing exactly: "{lines[0]}", then "{lines[1]}", then "{lines[2]}".'
            seed = {f'{words[3]}.txt': f'{words[3]}\n'}
            yield dict(id=f'r11-create-{i}', family='exact_create', category='edit', behaviour='verify-before-done',
                       request=req, files=seed, changes={path: ''.join(x + '\n' for x in lines)},
                       oracle=(c.ls(), c.run(f"printf '%s\\n' {_q(lines)} > {path}"), c.read(path),
                               c.done('Created.')))

    return {'append_after_marker': (append_marker, 72), 'named_file_missing': (named_missing, 60),
            'named_file_present': (named_present, 40), 'precise_count': (precise_count, 60),
            'exact_create': (exact_create, 30)}
