"""Additive interface-v3 training fixtures. No development paths, labels or rows."""


def families(c):
    def scripts(g, n):
        for i in range(n):
            word = g.pick(c.WORDS)
            target = f'label-{word}-{g.int(11, 97)}.sh'
            marker = '$' + word.upper()
            line = f"printf '%s\\n' '{marker}'"
            body = f'#!/bin/sh\n{line}\n'
            files = {'label.card': marker + '\n'}
            if i % 2:
                # Input contains an expandable variable, but the request requires literal bytes.
                wrong = f'printf \'%s\\n\' "{marker}"'
                files[target] = body.replace(line, wrong)
                req = f'Fix {target} to print the exact label in label.card literally, regardless of the environment.'
                steps = (c.read('label.card'), c.read(target), c.edit(target, wrong, line))
                family = 'literal_script_repair'
            else:
                req = f'Create {target} to print the literal from label.card on its own line. Leave the card unchanged.'
                steps = (c.ls(), c.read('label.card'), c.run(f"cat > {target} <<'LABEL_SCRIPT'\n{body}LABEL_SCRIPT"))
                family = 'literal_script_create'
            yield dict(id=f'r9-label-{i}', family=family, category='scripts', behaviour='verify-before-done',
                       request=req, files=files, changes={target: body}, facts=('syntax ok',),
                       oracle=(*steps, c.run(f'sh -n {target} && echo syntax ok'), c.done('Checked syntax.')))

    def records(g, n):
        for i in range(n):
            names = g.pick(c.WORDS, 3)
            values = g.rng.sample(range(10, 99), 3)
            rows = list(zip(names, values))
            name_first = bool(i % 2)
            largest = bool((i // 2) % 2)
            path = f'{names[0]}-batch.tsv'
            text = ''.join((f'{k}\t{v}\n' if name_first else f'{v}\t{k}\n') for k, v in rows)
            num, label = (2, 1) if name_first else (1, 2)
            final = 'tail' if largest else 'head'
            cmd = f'LC_ALL=C sort -k{num},{num}n {path} | {final} -n 1 | cut -f{label}'
            fact = (max if largest else min)(rows, key=lambda row: row[1])[0]
            yield dict(id=f'r9-record-{i}', family='select_record', category='inspect', behaviour='inspect-first',
                       request=f'Which batch label has the {"highest" if largest else "lowest"} reading in {path}?',
                       files={path: text}, changes={}, facts=(fact,), oracle=(c.read(path), c.run(cmd), c.done(fact)))

    return {'label_script': (scripts, 100), 'select_record': (records, 80)}
