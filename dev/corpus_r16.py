"""Revision 16 families (interface v8, docs/data/R16-V8.md). No development or held-out paths,
labels or rows.

Revision 16 is revision 15 plus two spaces_to_dashes families aimed at r15's one probe habit: the
model scoped `glob` with a pattern in the *new* form (`track-*.wav` for `track one.wav`), which
matches nothing that changes.

  - rename_spaces_prefix: the request names a subset by its leading word ("the track files"),
    and the call scopes it with that word and the space still in it (`glob: track *.wav`). Other
    spaced files in the same folder are left alone.
  - rename_glob_recover: the first fs.rename uses the new-form glob; lilguy's message says the
    glob matches current names and lists the files left out; the next call uses the current form
    and the episode ends with a bare `done`. The wrong first call is masked out of the training
    targets (train_skip) and kept only as context.
"""
from dev.corpus_r15 import tool


def families(c):
    def subset(g, i):
        place, thing = g.pick(c.PLACES), g.pick(c.THINGS)
        folder = f'{place}-{thing}'
        lead = g.choice(('track', 'clip', 'scan', 'page', 'take', 'shot', 'memo', 'draft'))
        ext = g.choice(('.wav', '.mp4', '.png', '.txt', '.pdf', '.jpg'))
        words = g.shuffle(c.WORDS)[:6]
        count = g.int(2, 4)
        names = [f'{lead} {words[k]}{ext}' for k in range(count)]
        others = [f'{words[4]} {words[5]}{ext}']  # spaced, outside the subset: left alone
        files = {f'{folder}/{n}': f'{n} data\n' for n in names + others}
        if i % 2:
            files[f'{folder}/{lead}-{words[4]}{ext}'] = 'already dashed\n'  # never a rename target
        changes = {}
        for n in names:
            changes[f'{folder}/{n}'] = None
            changes[f"{folder}/{n.replace(' ', '-')}"] = files[f'{folder}/{n}']
        return folder, lead, ext, files, changes

    requests = (
        'In {f}/, replace the spaces with dashes in the names of the {l} files only.',
        'Rename just the {l} files in {f}/ so spaces become dashes.',
        '{f}/: dash out the spaces in the {l} file names; leave the other files as they are.',
        'For the files in {f}/ whose names start with "{l} ", turn the spaces into dashes.',
        'Only the {l} files in {f}/: swap spaces for dashes in their names.',
    )

    def rename_spaces_prefix(g, n):
        for i in range(n):
            folder, lead, ext, files, changes = subset(g, i)
            req = g.choice(requests).format(f=folder, l=lead)
            oracle = (c.ls(folder), tool('fs.rename', path=folder, rule='spaces_to_dashes', glob=f'{lead} *{ext}'),
                      'done')
            yield dict(id=f'r16-spaces-prefix-{i}', family='rename_spaces_prefix', category='organise',
                       behaviour='pending-stop', request=req, files=files, oracle=oracle, changes=changes,
                       error_turns=(1,), policy_end='pending')

    def rename_glob_recover(g, n):
        for i in range(n):
            folder, lead, ext, files, changes = subset(g, i)
            req = g.choice(requests).format(f=folder, l=lead)
            oracle = (c.ls(folder),
                      tool('fs.rename', path=folder, rule='spaces_to_dashes', glob=f'{lead}-*{ext}'),
                      tool('fs.rename', path=folder, rule='spaces_to_dashes', glob=f'{lead} *{ext}'),
                      'done')
            yield dict(id=f'r16-glob-recover-{i}', family='rename_glob_recover', category='recovery',
                       behaviour='recover-after-error', request=req, files=files, oracle=oracle,
                       changes=changes, error_turns=(1, 2), train_skip=(1,), policy_end='pending')

    return {'rename_spaces_prefix': (rename_spaces_prefix, 40), 'rename_glob_recover': (rename_glob_recover, 30)}
