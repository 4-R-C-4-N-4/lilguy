"""Additive interface-v4 training families (revision 10). No development paths, labels or rows.

Written from the v4 focus diagnosis (docs/data/FOCUS-V4-DIAGNOSIS.md): the r8 corpus never used
a multi-line `old <<<` value, and every append was one line to a file ending in a newline.
These families teach exactly those moves; everything else in revision 10 is revision 8.
"""


def block(key, text):
    return f'{key} <<<\n{text.rstrip(chr(10))}\n>>>'


def edit_block(path, old, new):
    return f'tool fs.edit\npath: {path}\n{block("old", old)}\n{block("new", new)}'


# Section shapes: (render one section, the header line, the repeated line, its new form).
def _ini(name, key, old, new):
    return f'[{name}]\n{key}={old}\n', f'[{name}]\n', f'{key}={old}\n', f'{key}={new}\n'


def _md(name, key, old, new):
    return f'## {name}\n- [ ] {key}\n', f'## {name}\n', f'- [ ] {key}\n', f'- [x] {key}\n'


def _record(name, key, old, new):
    return f'item: {name}\n{key}: {old}\n', f'item: {name}\n', f'{key}: {old}\n', f'{key}: {new}\n'


def _nested(name, key, old, new):
    return f'{name}:\n  {key}: {old}\n', f'{name}:\n', f'  {key}: {old}\n', f'  {key}: {new}\n'


SHAPES = (
    ('ini', _ini, 'In {path}, set {key} to {new} in the [{target}] section only.'),
    ('md', _md, 'In {path}, tick "{key}" under {target} only; leave the other one unticked.'),
    ('record', _record, 'In {path}, change {key} to {new} for item {target}. The other item keeps {old}.'),
    ('nested', _nested, 'In {path}, change {key} under {target} to {new}; the other section keeps {old}.'),
)
EXTENSIONS = {'ini': 'ini', 'md': 'md', 'record': 'txt', 'nested': 'yaml'}


def families(c):
    def repeated(g, n):
        for i in range(n):
            label, render, template = SHAPES[i % len(SHAPES)]
            names = g.pick(c.WORDS, 3)
            key = g.pick(('port', 'qty', 'level', 'mode', 'limit', 'owner', 'review')) if label != 'md' else \
                f'{g.pick(("water", "pack", "file", "send"))} {names[2]}'
            old, new = (str(g.int(2, 40)), str(g.int(41, 99))) if label != 'md' else ('', '')
            sections = [render(name, key, old, new) for name in names[:2]]
            target = (i // len(SHAPES)) % 2  # alternate first and second occurrence
            text = '\n'.join(s[0] for s in sections)
            _, header, line, changed = sections[target]
            path = f'{names[0]}.{EXTENSIONS[label]}'
            after = text.replace(header + line, header + changed, 1)
            req = template.format(path=path, key=key, new=new, old=old, target=names[target])
            # A third first try the bare line and read the v4 refusal (not for indented lines).
            refused = label != 'nested' and (i // (2 * len(SHAPES))) % 3 == 0
            steps = [c.read(path)]
            skip, errors = (), ()
            if refused:
                steps.append(c.edit(path, line.rstrip('\n'), changed.rstrip('\n')))
                skip, errors = (1,), (1,)
            steps += [edit_block(path, header + line, header + changed), c.read(path)]
            yield dict(id=f'r10-repeated-{i}', family='block_edit_repeated', category='edit',
                       behaviour='recover-after-error' if refused else 'look-then-act', request=req,
                       files={path: text}, changes={path: after}, oracle=(*steps, c.done('Edited one section.')),
                       error_turns=errors, train_skip=skip)

    def appends(g, n):
        for i in range(n):
            words = g.pick(c.WORDS, 4)
            kind = i % 3
            if kind == 0:
                path, text = f'{words[0]}-notes.md', f'# {words[0]}\n- {words[1]}\n'
                lines = [f'- {words[2]}', f'- {words[3]}']
                req = f'Add two items to the end of {path}: "{lines[0][2:]}" and then "{lines[1][2:]}", as list items.'
            elif kind == 1:
                path, text = f'{words[0]}.csv', f'name,count\n{words[1]},{g.int(1, 9)}\n'
                lines = [f'{words[2]},{g.int(1, 9)}', f'{words[3]},{g.int(1, 9)}']
                req = f'Append two rows to {path}: {lines[0]} and then {lines[1]}.'
            else:
                path, text = f'{words[0]}.log', f'{g.int(10, 19)}:00 {words[1]}\n'
                lines = [f'{g.int(20, 21)}:00 {words[2]}', f'{g.int(22, 23)}:00 {words[3]}', '-- end --']
                req = f'Append these three lines to {path}: {lines[0]}, then {lines[1]}, then {lines[2]}.'
            quoted = ' '.join("'" + line + "'" for line in lines)
            yield dict(id=f'r10-append-{i}', family='multiline_append', category='edit', behaviour='verify-before-done',
                       request=req, files={path: text}, changes={path: text + ''.join(x + '\n' for x in lines)},
                       oracle=(c.read(path), c.run(f"printf '%s\\n' {quoted} >> {path}"), c.read(path),
                               c.done('Appended.')))

    def no_final_newline(g, n):
        for i in range(n):
            words = g.pick(c.WORDS, 4)
            path = f'{words[0]}-list.txt'
            text = f'{words[1]}\n{words[2]}'  # no newline at the end
            if i % 2:
                text += '\n'  # the same safe idiom is a no-op when the newline is there
            new = [words[3], f'{words[3]}-{g.int(2, 9)}']
            req = f'Add {new[0]} and then {new[1]} to the end of {path}, each on its own line.'
            fix = f"[ -n \"$(tail -c 1 {path})\" ] && printf '\\n' >> {path}; printf '%s\\n' '{new[0]}' '{new[1]}' >> {path}"
            after = text.rstrip('\n') + '\n' + ''.join(x + '\n' for x in new)
            yield dict(id=f'r10-eol-{i}', family='append_after_missing_newline', category='edit',
                       behaviour='verify-before-done', request=req, files={path: text}, changes={path: after},
                       oracle=(c.read(path), c.run(fix), c.read(path), c.done('Appended on new lines.')))

    def indented(g, n):
        for i in range(n):
            words = g.pick(c.WORDS, 3)
            path = f'{words[0]}-jobs.yaml'
            every = g.pick(('daily', 'weekly', 'hourly'))
            text = f'jobs:\n  - name: {words[1]}\n    every: weekly\n'
            add = [f'  - name: {words[2]}', f'    every: {every}']
            req = f'Add a job named {words[2]} that runs {every} to the end of {path}, formatted like the existing job.'
            quoted = ' '.join("'" + line + "'" for line in add)
            yield dict(id=f'r10-indent-{i}', family='indented_append', category='edit', behaviour='look-then-act',
                       request=req, files={path: text}, changes={path: text + ''.join(x + '\n' for x in add)},
                       oracle=(c.read(path), c.run(f"printf '%s\\n' {quoted} >> {path}"), c.read(path),
                               c.done('Added the job.')))

    return {'block_edit_repeated': (repeated, 120), 'multiline_append': (appends, 90),
            'append_after_missing_newline': (no_final_newline, 60), 'indented_append': (indented, 50)}
