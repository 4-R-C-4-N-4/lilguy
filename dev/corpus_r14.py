"""Revision 14 families (interface v6, docs/plan/INTERFACE-V6.md). No development or held-out paths, labels or rows.

Revision 14 is revision 13 recorded under interface v6, where the original archive episodes
(list, extract, extract one) use the typed archive tools (v2_corpus._list_archive/_unpack), plus:

  - archive_tools: what the roster showed models getting wrong with raw tar: packing a folder with
    an exclusion, packing a folder's contents only, gzip that keeps the original, adding to an
    existing archive, unpacking without replacing files, and comparing an archive with the
    workspace (a question). Every one uses the typed tools and checks the result.
  - permission_words: a permission request in words, about half with the resulting mode as a
    number, done with one explicit chmod after looking at the current mode. The mix pairs
    group-execute (`g+x`, pending) with group-write (`g+w`, allowed) because lesson 7 found
    "executable by the group" read as `g+s`; owner-only is always `600`.
"""
import hashlib


def _sha8(text):
    return hashlib.sha256(text.encode('utf8')).hexdigest()[:8]


def _archive(kind, members):
    return f"<{kind}: {', '.join(f'{p}={_sha8(t)}' for p, t in sorted(members.items()))}>"


def tool(name, **args):
    return '\n'.join([f'tool {name}', *(f'{k}: {str(v).lower() if isinstance(v, bool) else v}'
                                         for k, v in args.items())])


# (request in words, symbolic chmod, resulting mode from 644, policy)
_PERMISSIONS = (
    ('Let people in the group run {p}.', 'g+x', '654', 'pending'),
    ('Make {p} readable and writable by its owner only.', '600', '600', 'pending'),
    ('Stop everyone outside the group from reading {p}.', 'o-r', '640', 'pending'),
    ('Let the group edit {p} as well.', 'g+w', '664', 'ok'),
    ('Make {p} runnable by everyone.', 'a+x', '755', 'pending'),
    ('Let only the owner run {p}; leave the other permissions alone.', 'u+x', '744', 'pending'),
)


def families(c):
    def archive_tools(g, n):
        for i in range(n):
            place, thing = g.pick(c.PLACES), g.pick(c.THINGS)
            words = g.shuffle(c.WORDS)[:4]
            kind = i % 6
            folder = f'{place}-{thing}'
            members = {f'{folder}/{w}.txt': f'{w} {place}\n' for w in words[:3]}
            if kind == 0:  # pack a folder, leaving out one kind of file
                skipped = f'{folder}/{words[3]}.log'
                files = {**members, skipped: 'scratch\n'}
                name = f'{folder}.tar.gz'
                req = g.choice(('Bundle the {f}/ folder into {a}, skipping the .log files.',
                                'Pack {f}/ as {a} but leave out any *.log file.')).format(f=folder, a=name)
                oracle = (c.ls(folder), tool('archive.pack', archive=name, source=folder, exclude='*.log'),
                          tool('archive.list', path=name), c.done(f'Packed {folder}/ into {name} without the log.'))
                changes = {name: _archive('tar.gz', members)}
                yield dict(id=f'r14-pack-exclude-{i}', family='archive_tools', category='archives',
                           behaviour='verify-before-done', request=req, files=files, oracle=oracle, changes=changes)
            elif kind == 1:  # the folder's contents, not the folder
                name = f'{place}-{thing}-contents.tar'
                req = g.choice(('Pack what is inside {f}/ into {a}, without the {f} folder itself.',
                                'Make {a} from the files in {f}/, with no top folder inside the archive.')
                               ).format(f=folder, a=name)
                oracle = (c.ls(folder), tool('archive.pack', archive=name, source=folder, top_folder=False),
                          tool('archive.list', path=name), c.done(f'Packed the contents of {folder}/ into {name}.'))
                changes = {name: _archive('tar', {m.split('/', 1)[1]: t for m, t in members.items()})}
                yield dict(id=f'r14-pack-contents-{i}', family='archive_tools', category='archives',
                           behaviour='verify-before-done', request=req, files=members, oracle=oracle, changes=changes)
            elif kind == 2:  # gzip one file, keeping it
                log = f'{place}-{words[0]}.log'
                text = ''.join(f'{w} ok\n' for w in words)
                req = g.choice(('Compress {l} with gzip and keep the uncompressed copy.',
                                'Make a gzipped copy of {l}; {l} itself stays.')).format(l=log)
                oracle = (c.ls(), tool('archive.pack', archive=f'{log}.gz', source=log), c.ls(),
                          c.done(f'Created {log}.gz; {log} is still there.'))
                yield dict(id=f'r14-gzip-{i}', family='archive_tools', category='archives',
                           behaviour='verify-before-done', request=req, files={log: text}, oracle=oracle,
                           changes={f'{log}.gz': f'<gzip: {_sha8(text)}>'})
            elif kind == 3:  # add to an existing archive
                name = f'{folder}.tar'
                new = f'{folder}/{words[3]}.txt'
                files = {name: c.tar_text(members), **members, new: f'{words[3]} {place}\n'}
                req = g.choice(('Add {n} to the existing {a}, keeping what is already in it.',
                                'Put {n} into {a} as well.')).format(n=new, a=name)
                oracle = (tool('archive.list', path=name), tool('archive.add', archive=name, source=new),
                          tool('archive.list', path=name), c.done(f'{name} now also holds {new}.'))
                changes = {name: _archive('tar', {**members, new: f'{words[3]} {place}\n'})}
                yield dict(id=f'r14-add-{i}', family='archive_tools', category='archives',
                           behaviour='verify-before-done', request=req, files=files, oracle=oracle, changes=changes)
            elif kind == 4:  # unpack without replacing what is there
                name = f'{folder}.tar'
                kept = sorted(members)[0]
                files = {name: c.tar_text(members), kept: f'local {place} edit\n'}
                req = g.choice(('Unpack {a} here, but do not replace any file that already exists.',
                                'Extract {a} without overwriting files that are already in {f}/.')
                               ).format(a=name, f=folder)
                oracle = (tool('archive.list', path=name), tool('archive.unpack', archive=name),
                          c.read(kept), c.done(f'Unpacked {name}; {kept} already existed and was kept.'))
                changes = {m: t for m, t in members.items() if m != kept}
                yield dict(id=f'r14-unpack-keep-{i}', family='archive_tools', category='archives',
                           behaviour='verify-before-done', request=req, files=files, oracle=oracle, changes=changes)
            else:  # compare an archive with the workspace (a question)
                name = f'{folder}-backup.tar'
                changed = sorted(members)[g.int(0, 2)]
                files = {name: c.tar_text(members), **members, changed: f'{place} revised\n'}
                req = g.choice(('Which files in {f}/ no longer match {a}?',
                                'Has anything in {f}/ changed since {a} was made? Name the file.')
                               ).format(f=folder, a=name)
                oracle = (tool('archive.list', path=name, compare=True),
                          c.done(f'Only {changed} differs from {name}.'))
                yield dict(id=f'r14-compare-{i}', family='archive_compare', category='archives',
                           behaviour='factual-answer', request=req, files=files, oracle=oracle, changes={},
                           facts=(f'{changed} differs',))

    def permission_words(g, n):
        for i in range(n):
            place = g.pick(c.PLACES)
            word = g.pick(c.WORDS)
            request, symbolic, mode, policy = _PERMISSIONS[i % len(_PERMISSIONS)]
            path = g.choice((f'{place}-{word}.sh', f'tools/{word}.sh', f'{place}-{word}.txt'))
            files = {path: f'echo {word}\n'}
            req = request.format(p=path)
            if (i // len(_PERMISSIONS)) % 2 == 0:
                req += f' (That makes it {mode}.)'
            cmd = f'chmod {symbolic} {path}'
            if policy == 'pending':
                end = c.done(f'{path} changing to {mode} is staged and {c.PENDING}.')
            else:
                end = c.done(f'{path} is now {mode}.')
            yield dict(id=f'r14-perm-{i}', family='permission_words', category='permissions',
                       behaviour='pending-stop' if policy == 'pending' else 'look-then-act',
                       request=req, files=files, source_page='chmod',
                       oracle=(c.run(f'stat -c %a {path}'), c.run(cmd), end),
                       changes={path: f'<mode 644->{mode}>'}, error_turns=(1,) if policy == 'pending' else (),
                       policy_end=policy)

    return {'archive_tools': (archive_tools, 72), 'permission_words': (permission_words, 48)}
