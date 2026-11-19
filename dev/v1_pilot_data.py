"""Small training-only corpus for the first v1 adapter feasibility run.

The shell patterns are hand adaptations of pinned tldr-pages documentation;
requests, fixture bytes, and expected results are original. No fetched code runs.
"""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile

from dev import episodes, eval_gate, fast12_runner
from dev.broad_runner import development_rows
from lilguy import loop, protocol

REVISION = '2d64595223d89a23d249fed57d8f401d95f8ccf9'
PROJECT = f'https://github.com/tldr-pages/tldr/tree/{REVISION}'
ATTRIBUTION = 'tldr-pages team and contributors'
LICENCE = 'https://creativecommons.org/licenses/by/4.0/'
ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('original', 'recovery', 'handoff')


@dataclass(frozen=True)
class Example:
    id: str
    family: str
    request: str
    files: dict[str, str]
    oracle: tuple[str, ...]
    changes: dict[str, str]
    terminal: str = 'done'
    source_page: str | None = None
    error_turns: tuple[int, ...] = ()
    read_evidence: str = ''
    policy_end: str = 'ok'

    def manifest(self):
        return dict(id=self.id, template_id='pilot-' + self.family, split='train',
                    request=self.request, files=self.files)

    def provenance(self):
        if self.source_page is None:
            return {'origin': 'original lilguy fixture'}
        return {'source': f'{PROJECT}/pages/common/{self.source_page}.md', 'revision': REVISION,
                'credit': ATTRIBUTION, 'licence': LICENCE,
                'changes': 'Adapted usage to a new request, fixture, output and multi-turn protocol.'}


def _copy(id, family, request, files, command, out, expected):
    inspections = tuple(f'tool fs.read\npath: {path}' for path in files)
    return Example(id, family, request, files, (*inspections, 'run\n' + command,
                   f'tool fs.read\npath: {out}', f'done\nWrote {out} and verified its contents.'),
                   {out: expected}, source_page=family)


def tasks(profile='original'):
    if profile not in PROFILES:
        raise ValueError(f'unknown pilot profile: {profile}')
    for domain, lines in (
        ('orchard', ('plum', 'pear', 'apricot', 'damson')),
        ('workshop', ('borer', 'chisel', 'auger', 'square')),
        ('observatory', ('lunar', 'meteor', 'quasar', 'nebula')),
        ('terrarium', ('moss', 'lichen', 'fern', 'sedge')),
    ):
        folder_file = f'{domain}-notes.txt'
        first = f'{domain}-preview.txt'
        last = f'{domain}-ending.txt'
        source = {folder_file: '\n'.join(lines) + '\n'}
        recent = f'{domain}-journal.txt'
        recent_lines = (f'{domain} started', f'{domain} checked', f'{domain} finished')
        yield _copy(f'pilot-{domain}-preview', 'head',
                    f'Save the opening two entries of {folder_file} to {first} as a preview.',
                    source, f'head -n 2 -- {folder_file} > {first}', first, '\n'.join(lines[:2]) + '\n')
        yield _copy(f'pilot-{domain}-journal', 'tail',
                    f'Put just the latest entry from {recent} in {last}, leaving the journal as it is.',
                    {recent: '\n'.join(recent_lines) + '\n'}, f'tail -n 1 -- {recent} > {last}',
                    last, recent_lines[-1] + '\n')
        if profile != 'handoff':
            yield _copy(f'pilot-{domain}-lowercase', 'tr',
                        f'Create {domain}-normal.txt with the ASCII letters in {domain}-tags.txt folded to lower case.',
                        {f'{domain}-tags.txt': f'{domain.upper()}_ONE\n{lines[0].upper()}-Two\n'},
                        f"LC_ALL=C tr 'A-Z' 'a-z' < {domain}-tags.txt > {domain}-normal.txt",
                        f'{domain}-normal.txt', f'{domain}_one\n{lines[0]}-two\n')
        left, right, dest = (f'{domain}-{kind}.txt' for kind in ('objects', 'slots', 'pairs'))
        yield _copy(f'pilot-{domain}-pair', 'paste',
                    f'Pair the rows of {left} and {right} side by side separated by tabs, into {dest}.',
                    {left: '\n'.join(lines[:2]) + '\n', right: 'shelf\ntray\n'},
                    f'paste -- {left} {right} > {dest}', dest, f'{lines[0]}\tshelf\n{lines[1]}\ttray\n')
    if profile != 'handoff':
        for name, left, right in (('badge', 'amber-label', 'cobalt-label'), ('roster', 'spring-list', 'summer-list'),
                                  ('menu', 'north-card', 'south-card'), ('route', 'riverside-map', 'hill-map')):
            yield Example(f'pilot-which-{name}', 'clarify', f'Add the new membership entry to the {name} file.',
                          {left + '.txt': f'{name}: draft for one group\n',
                           right + '.txt': f'{name}: draft for another group\n'},
                          ('tool fs.list\npath: .', f'ask\nWhich file should I use, {left}.txt or {right}.txt, '
                           'and what membership entry should I add?'), {}, terminal='ask')

    if profile in ('recovery', 'handoff'):
        yield from _recovery_examples()
    if profile == 'handoff':
        yield from _handoff_examples()


def _handoff_examples():
    for subject, left, right, one, two in (
        ('parcel', 'domestic', 'overseas', 'vireo', 'turnstone'),
        ('voucher', 'staff', 'visitor', 'topaz', 'onyx'),
        ('display', 'east-wing', 'west-wing', 'magenta', 'cyan'),
    ):
        paths = [f'{subject}-{edition}.txt' for edition in (left, right)]
        first, second = paths
        # Rotate the selected entry; the filename position is not predictive.
        chosen, leftover = (second, first) if subject == 'voucher' else (first, second)
        edition = right if chosen == second else left
        yield Example(f'pilot-handoff-ask-{subject}', 'edition-choice',
                      f'Tell me the passphrase in the {subject} notes.',
                      {first: f'Passphrase: {one}\n', second: f'Passphrase: {two}\n'},
                      (f'tool fs.read\npath: {first}', f'tool fs.read\npath: {second}',
                       f'ask\nWhich edition of the {subject} notes do you mean: {left} or {right}?'),
                      {}, terminal='ask')
        # The contrast has the same decision structure and candidates but distinct fixture bytes.
        yield Example(f'pilot-handoff-read-{subject}', 'edition-choice',
                      f'Tell me the passphrase in the {edition} edition of the {subject} notes.',
                      {chosen: f'Passphrase: {two}\nEdition: {edition}\n', leftover: f'Passphrase: {one}\n'},
                      ('tool fs.list\npath: .', f'tool fs.read\npath: {chosen}',
                       f'done\nThe {edition} passphrase is {two}.'), {}, read_evidence=two)
    yield Example('pilot-handoff-clear-draft', 'approval-clear-scratch',
                  'Empty the scratch notes in rehearsal-scratch.txt but keep the file in place.',
                  {'rehearsal-scratch.txt': 'Dummy entries for a disposable rehearsal.\n'},
                  ('tool fs.read\npath: rehearsal-scratch.txt', 'run\ncp /dev/null rehearsal-scratch.txt',
                   'done\nThe change is staged and pending your approval; rehearsal-scratch.txt is unchanged until then.'),
                  {'rehearsal-scratch.txt': ''}, error_turns=(1,), policy_end='pending')
    yield Example('pilot-handoff-executable-demo', 'approval-mark-executable',
                  'Mark the demo file run-card.sh executable. Do not run it.',
                  {'run-card.sh': '#!/bin/bash\nprintf "Demo card\\n"\n'},
                  ('tool fs.read\npath: run-card.sh', 'run\nchmod u+x run-card.sh',
                   'done\nThe permission change is staged and pending your approval; I did not run the file.'),
                  {'run-card.sh': '<mode 644->744>'}, error_turns=(1,), policy_end='pending')


def _recovery_examples():
    for subject, value in (('brochure', 'travertine'), ('ceramics', 'vermilion'),
                           ('bookplate', 'marigold'), ('stencil', 'lapis')):
        note, stale = f'{subject}-colour.txt', f'{subject}-color-old.txt'
        yield Example(f'pilot-recover-{subject}', 'renamed-read',
                      f'Tell me the ink colour for the {subject}. My notes refer to {stale}; '
                      'if that reference is stale, find the current colour note. Do not write anything.',
                      {note: f'Ink colour: {value}\n', f'{subject}-paper.txt': 'Paper: matte\n'},
                      (f'tool fs.read\npath: {stale}', 'tool fs.list\npath: .', f'tool fs.read\npath: {note}',
                       f'done\nThe ink colour is {value}.'), {}, error_turns=(0,), read_evidence=value)
    for subject, value in (('rehearsal', 'east hall'), ('lecture', 'atrium'),
                           ('reading', 'courtyard'), ('screening', 'annex')):
        path = f'{subject}-venue.txt'
        yield Example(f'pilot-read-{subject}', 'venue-only', f'What venue is named in {path}?',
                      {path: f'Venue: {value}\nCrew notes: none\n'},
                      (f'tool fs.read\npath: {path}', f'done\nThe venue is {value}.'), {}, read_evidence=value)


def audit(examples):
    rows = development_rows()
    rows.extend(t.manifest() for t in examples)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'candidate.json'
        path.write_text(json.dumps(rows), encoding='utf8')
        pin = (ROOT / 'dev/holdout_manifest.sha256').read_text().split()[0]
        return eval_gate.verify(ROOT / 'dev/holdout_manifest.json', pin, path)


def next_action_rows(messages):
    return [messages[:i + 1] for i, message in enumerate(messages) if message['role'] == 'assistant']


def _grade(task, *, terminal, answer, changes, events, original_unchanged):
    if (not original_unchanged or changes != task.changes or terminal != task.terminal or not answer
            or not events or tuple(i for i, (_, _, error) in enumerate(events) if error) != task.error_turns
            or any(loop.policy_of(obs) != 'ok' for _, obs, _ in events[:-1])
            or loop.policy_of(events[-1][1]) != task.policy_end):
        return ['unexpected reference trajectory, terminal, or staged effects']
    if task.policy_end == 'pending' and 'staged and pending your approval' not in answer.casefold():
        return ['pending changes must be reported as staged and awaiting approval']
    if task.read_evidence:
        action, obs, error = events[-1]
        if error or action.tool != 'fs.read' or not obs.startswith('exit=0') or task.read_evidence not in obs:
            return ['missing successful read of the requested fact']
        if task.read_evidence.casefold() not in answer.casefold():
            return ['answer omits the requested fact']
    return []


def accept(task, reference, replay, tools):
    if (reference != replay or reference['infra_error'] is not None or reference['failures'] != []
            or reference['original_unchanged'] is not True or reference['changes'] != task.changes
            or reference['terminal'] != task.terminal or not reference['events']):
        return None
    saved = dict(version=protocol.INTERFACE_VERSION, request=task.request, terminal=reference['terminal'],
                 answer=reference['answer'], turns=reference['events'])
    return episodes.to_messages(saved, tools)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--profile', choices=PROFILES, default='original')
    args = parser.parse_args(argv)
    examples = tuple(tasks(args.profile))
    gate = audit(examples)
    if not gate['ok']:
        parser.exit(1, f"Split gate refused pilot data: {gate['reason']}\n")
    tools = protocol.load_tools()
    rows, evidence = [], []
    for task in examples:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = fast12_runner.run_oracle(root / 'reference', task, tools, _grade)
            saved = dict(version=protocol.INTERFACE_VERSION, request=task.request, terminal=reference['terminal'],
                         answer=reference['answer'], turns=reference['events'])
            if reference['infra_error'] is not None or reference['failures'] != []:
                parser.exit(1, f'Pilot reference failed: {task.id}\n')
            lines = tuple(message['content'] for message in episodes.to_messages(saved, tools)
                          if message['role'] == 'assistant')
            replay = fast12_runner.run_episode(root / 'replay', task, fast12_runner._scripted(lines, tools),
                                               tools, _grade)
        messages = accept(task, reference, replay, tools)
        if messages is None:
            parser.exit(1, f'Pilot replay disagreed with reference: {task.id}\n')
        rows.extend(dict(episode=task.id, messages=row) for row in next_action_rows(messages))
        evidence.append(dict(task=task.manifest(), source=task.provenance(), record=saved,
                             staged=reference['changes'], original_unchanged=True))
    args.out.mkdir(mode=0o700, exist_ok=False)
    (args.out / 'train.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf8')
    (args.out / 'effects.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'profile': args.profile, 'episodes': len(evidence), 'next_actions': len(rows), 'gate': gate}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
