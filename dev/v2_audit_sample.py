"""Render a stratified, seeded sample of corpus v2 episodes for a human or agent audit."""
import argparse
import json
from pathlib import Path
import random


def render(entry):
    task, record = entry['task'], entry['record']
    out = [f"## {task['id']}  (family {entry['family']}, category {entry['category']}, behaviour {entry['behaviour']})",
           '', f"Request: {task['request']}", '', 'Workspace before:']
    for path, text in sorted(task['files'].items()):
        shown = text if len(text) < 400 and '\x00' not in text else f'<{len(text)} chars{", tar archive" if chr(0) in text else ""}>'
        out.append(f'  {path}: {shown!r}')
    out.append('')
    for n, turn in enumerate(record['turns']):
        action = turn['action']
        body = action['text'] if action['kind'] == 'run' else json.dumps(action['args'])
        out.append(f"[{n}] {action['kind']} {action['tool'] or ''} {body}")
        out.extend('      ' + line for line in turn['observation'].splitlines())
    out.append(f"[{len(record['turns'])}] {record['terminal']}: {record['answer']}")
    out.append(f"Staged effect: {json.dumps(entry['staged'])[:600]}")
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--n', type=int, default=200)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args()
    evidence = json.loads((args.corpus / 'effects.json').read_text())
    by_family = {}
    for entry in evidence:
        by_family.setdefault(entry['family'], []).append(entry)
    rng = random.Random(args.seed)
    picks = []
    # Proportional allocation with at least two per family.
    for family, entries in sorted(by_family.items()):
        k = max(2, round(args.n * len(entries) / len(evidence)))
        picks.extend(rng.sample(entries, min(k, len(entries))))
    rng.shuffle(picks)
    picks = picks[:args.n]
    text = '\n\n'.join(render(e) for e in picks)
    (args.corpus / 'audit-sample.md').write_text(f'# Corpus v2 audit sample ({len(picks)} episodes, seed {args.seed})\n\n'
                                                 + text + '\n')
    print(len(picks))


if __name__ == '__main__':
    main()
