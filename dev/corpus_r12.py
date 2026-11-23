"""Additive interface-v5 contrast families (revision 12). No development or held-out paths, labels or rows.

Revision 11 fixed its focus set but lost five roster tasks at both seeds
(docs/data/R11-V5-RESULT.md): an end-of-file append where a line belonged under a heading, `done`
straight after a failed or empty step, and a folder copied into itself. These families supply the
missing contrasts; everything else in revision 12 is revision 11.

  - insert_under_heading: add a line inside a section (first item, or the end of a section that
    is not the last) with a block fs.edit, never an append;
  - recover_after_empty: a question whose first command fails or prints a useless 0 or nothing;
    the model reads the file and recomputes before done (the slip is never a training target);
  - copy_folder_contents: copy what is *inside* a folder (`src/.`), then list the result.
"""


def block(key, text):
    return f'{key} <<<\n{text.rstrip(chr(10))}\n>>>'


def edit_block(path, old, new):
    return f'tool fs.edit\npath: {path}\n{block("old", old)}\n{block("new", new)}'


def families(c):
    def insert_under_heading(g, n):
        for i in range(n):
            words = g.pick(c.WORDS, 7)
            shape, where = i % 3, (i // 3) % 2  # where: 0 = first item, 1 = end of a section that is not last
            if shape == 0:
                path = f'{words[0]}-plan.md'
                a, b = words[1].title(), words[2].title()
                text = f'# {words[0]}\n## {a}\n- {words[3]}\n- {words[4]}\n\n## {b}\n- {words[5]}\n'
                item = f'- {words[6]}'
                if where == 0:
                    old, new = f'## {a}\n- {words[3]}\n', f'## {a}\n{item}\n- {words[3]}\n'
                    req = f'Add "{words[6]}" as the first item under ## {a} in {path}.'
                else:
                    old, new = f'- {words[4]}\n\n## {b}\n', f'- {words[4]}\n{item}\n\n## {b}\n'
                    req = f'Add "{words[6]}" to the end of the {a} section in {path}; {b} stays as it is.'
            elif shape == 1:
                path = f'{words[0]}.ini'
                a, b = words[1], words[2]
                text = f'[{a}]\nmode={words[3]}\n\n[{b}]\nmode={words[4]}\n'
                line = f'{words[5]}={g.int(1, 99)}'
                if where == 0:
                    old, new = f'[{a}]\nmode={words[3]}\n', f'[{a}]\n{line}\nmode={words[3]}\n'
                    req = f'In {path}, add {line} as the first line of the [{a}] section.'
                else:
                    old, new = f'mode={words[3]}\n\n[{b}]\n', f'mode={words[3]}\n{line}\n\n[{b}]\n'
                    req = f'In {path}, add {line} at the end of the [{a}] section, before [{b}].'
            else:
                path = f'{words[0]}-steps.txt'
                lines = [f'1. {words[1]}', f'2. {words[2]}', f'3. {words[3]}']
                text = '\n'.join(lines) + '\n'
                extra = f'   - check {words[4]}'
                k = where  # after step 1 or after step 2
                old = lines[k] + '\n' + lines[k + 1] + '\n'
                new = lines[k] + '\n' + extra + '\n' + lines[k + 1] + '\n'
                req = f'In {path}, insert the line "{extra.strip()}" (indented by three spaces) right after "{lines[k]}".'
            yield dict(id=f'r12-insert-{i}', family='insert_under_heading', category='edit',
                       behaviour='look-then-act', request=req, files={path: text},
                       changes={path: text.replace(old, new, 1)},
                       oracle=(c.read(path), edit_block(path, old, new), c.read(path), c.done('Inserted.')))

    def recover_after_empty(g, n):
        for i in range(n):
            words = g.pick(c.WORDS, 6)
            kind = i % 3
            if kind == 0:  # a count whose first pattern assumes another format: 0, exit 1
                path = f'{words[0]}-orders.csv'
                state = g.choice(('pending', 'shipped', 'held', 'paid'))
                other = 'done' if state != 'done' else 'open'
                rows = ['id,status'] + [f'{k},{state if g.int(0, 1) else other}' for k in range(1, g.int(4, 8))]
                if not any(r.endswith(',' + state) for r in rows[1:]):
                    rows.append(f'{len(rows)},{state}')
                count = sum(r.endswith(',' + state) for r in rows[1:])
                files = {path: c._lines(rows)}
                req = f'How many orders in {path} are {state}?'
                steps = (c.run(f"grep -c -- 'status: {state}' {path}"), c.read(path),
                         c.run(f"awk -F, 'NR>1 && $2==\"{state}\" {{c++}} END {{print c+0}}' {path}"))
                facts = (str(count),)
            elif kind == 1:  # comm on unsorted input fails; an order-free comparison answers
                want = g.pick(c.WORDS, 4)
                have = [want[1], want[3], words[1]]
                a, b = f'{words[0]}-wanted.txt', f'{words[0]}-got.txt'
                files = {a: c._lines(want), b: c._lines(have)}
                missing = [w for w in want if w not in have]
                if sorted(want) == want or sorted(have) == have:  # comm must really fail
                    files = {a: c._lines(list(reversed(want)) if sorted(want) == want else want),
                             b: c._lines(list(reversed(have)) if sorted(have) == have else have)}
                req = f'Which entries of {a} are missing from {b}?'
                steps = (c.run(f'comm -23 {a} {b}'), c.run(f'grep -vxF -f {b} {a}'))
                facts = tuple(missing)
            else:  # a yes/no whose first pattern is too strict prints nothing, exit 1
                path = f'{words[0]}-rota.txt'
                word = g.choice(('CANCELLED', 'MOVED', 'SWAPPED', 'OPEN'))
                present = (i // 3) % 2 == 0
                rows = [f'{words[1]} mon', f'{words[2]} tue'] + ([word] if present else []) + [f'{words[3]} wed']
                files = {path: c._lines(rows)}
                req = f'Does any line of {path} start with {word}?'
                steps = (c.run(f"grep -n '^{word} ' {path}"), c.read(path),
                         c.run(f"grep -n '^{word}' {path} && echo yes || echo 'no line starts with {word}'"))
                facts = ('yes',) if present else (f'no line starts with {word}',)
                if not present:  # the strict pattern was not wrong: the honest answer is still no
                    steps = (steps[0], steps[2])
            yield dict(id=f'r12-recover-{i}', family='recover_after_empty', category='recovery',
                       behaviour='recover-after-error', request=req, files=files, changes={},
                       oracle=(*steps, c.done(' '.join(facts))), facts=facts, error_turns=(0,), train_skip=(0,))

    def copy_folder_contents(g, n):
        for i in range(n):
            words = g.pick(c.WORDS, 5)
            src, dest = f'{words[0]}', f'{words[1]}-copy'
            files = {f'{src}/{words[2]}.txt': f'{words[2]}\n', f'{src}/{words[3]}/{words[4]}.txt': f'{words[4]}\n'}
            new_dest = i % 2 == 0
            changes = {f'{dest}/{words[2]}.txt': f'{words[2]}\n', f'{dest}/{words[3]}': '<dir added>',
                       f'{dest}/{words[3]}/{words[4]}.txt': f'{words[4]}\n'}
            if new_dest:
                changes[dest] = '<dir added>'
                cmd = f'mkdir -p {dest} && cp -r {src}/. {dest}/'
                req = f'Make a new folder {dest} with the same contents as {src}, including subfolders.'
            else:
                files[f'{dest}/keep.txt'] = 'keep\n'
                cmd = f'cp -r {src}/. {dest}/'
                req = f'Copy everything inside {src} into {dest}, keeping what {dest} already has.'
            yield dict(id=f'r12-copy-{i}', family='copy_folder_contents', category='organise',
                       behaviour='verify-before-done', request=req, files=files, changes=dict(sorted(changes.items())),
                       oracle=(c.ls(src), c.run(cmd), c.ls(dest), c.done('Copied.')))

    return {'insert_under_heading': (insert_under_heading, 84), 'recover_after_empty': (recover_after_empty, 72),
            'copy_folder_contents': (copy_folder_contents, 40)}
