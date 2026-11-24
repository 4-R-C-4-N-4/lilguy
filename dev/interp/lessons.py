"""Interpretability lessons 2-4 (docs/plan/INTERPRETABILITY.md). Training Python, RTX 3090, dev traces only.

    $TRAIN_PY -m dev.interp.lessons margins OUT      # lesson 2: coin flips vs habits
    $TRAIN_PY -m dev.interp.lessons patch OUT [--case insert|chmod]   # lessons 3, 7: where a habit lives
    $TRAIN_PY -m dev.interp.lessons steer OUT [--case insert|chmod]   # lessons 4, 7: flip it without training?
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev.interp.common import ADAPTERS, Lab, divergence, p, TOOLS, VERSION, verdict

R12 = ('r12_s42', 'r12_s43')


# --- lesson 2 ------------------------------------------------------------------------------------

def lost_tasks():
    from dev.interp.common import RUNS, FACTORY
    ids = sorted({Path(f).name[5:-5] for d in RUNS['r10_2_0'] for f in (FACTORY / d).glob('task_*.json')})
    return [t for t in ids if verdict('r10_2_0', t)['passed'] and any(not verdict(s, t)['passed'] for s in R12)]


def margins(lab, out):
    rows = []
    for task in lost_tasks():
        for seed in R12:
            found = divergence(task, seed)
            if found is None:
                continue
            msgs, mistake, correct, step = found
            head = lab.head(msgs)
            row = {'task': task, 'failing': seed, 'step': step, 'mistake': mistake, 'correct': correct, 'margin': {}}
            for label in ['stock', *ADAPTERS]:
                with lab.use(label):
                    row['margin'][label] = round(lab.margin(head, mistake, correct), 2)
            m = row['margin'][seed]
            # >= 2: a real preference for the mistake; |m| < 1: a coin flip; <= -2: in bf16 the failing
            # model prefers the correct action, so its miss came from greedy decoding on the Q8_0 server
            row['verdict'] = ('habit' if m >= 2 else 'coin flip' if abs(m) < 1 else
                              'not reproduced' if m <= -2 else 'lean')
            rows.append(row)
            print(f"{task:38} {seed} step {step} {row['verdict']:9} " +
                  ' '.join(f'{k}={v:+.1f}' for k, v in row['margin'].items()), flush=True)
    (out / 'margins.json').write_text(json.dumps(rows, indent=1) + '\n')


# --- cases: a habit, a model that has it, a donor that does not, and contrast prompts --------------

WORDS = ['amber', 'basil', 'cedar', 'dahlia', 'ember', 'fennel', 'garnet', 'hazel', 'indigo', 'juniper',
         'kestrel', 'lilac', 'maple', 'nutmeg', 'olive', 'pepper', 'quince', 'russet', 'saffron', 'thyme']


def _episode(request, look, stdout):
    obs = p.render_observation(exit_code=0, stdout=stdout, version=VERSION)
    return [{'role': 'system', 'content': p.system_prompt(TOOLS, VERSION)},
            {'role': 'user', 'content': p.user_message(request, 'do', VERSION)},
            {'role': 'assistant', 'content': p.render_action(look, TOOLS, VERSION)},
            {'role': 'user', 'content': p.observation_message(obs)}]


def insert_pairs():
    """Synthetic, non-roster pairs: the same file read, then 'insert under a heading' vs 'append at the end'.
    Each entry: (toward-correct prompt, away prompt, control (wrong, right) actions for the away prompt)."""
    pairs = []
    for i in range(16):
        a, b, c, d, item = (WORDS[(i * 5 + j) % len(WORDS)] for j in range(5))
        path = f'{a}-notes.md'
        text = f'# {a}\n## {b.title()}\n- {c}\n\n## {d.title()}\n- {a}{i}\n'
        look = p.Action.call('fs.read', path=path)
        insert_cmd = (f'tool fs.edit\npath: {path}\nold <<<\n## {b.title()}\n- {c}\n>>>\n'
                      f'new <<<\n## {b.title()}\n- {item}\n- {c}\n>>>')
        append_cmd = f"run\nprintf '%s\\n' '- {item}' >> {path}"
        pairs.append((_episode(f'Add "- {item}" directly under the ## {b.title()} heading in {path}.', look, text),
                      _episode(f'Add "- {item}" as the very last line of {path}.', look, text),
                      (insert_cmd, append_cmd)))
    return pairs


def chmod_pairs():
    """Synthetic, non-roster pairs: the same folder listed, then 'let the group execute' vs 'let the group write'.
    The away prompt's control: g+x (wrong there) vs g+w (right there)."""
    pairs = []
    for i in range(16):
        a, b, c = (WORDS[(i * 3 + j) % len(WORDS)] for j in range(3))
        folder = f'{a}-bin'
        listing = f'f         20 {folder}/{b}.sh\nf         22 {folder}/{c}.sh\n'
        look = p.Action.call('fs.list', path=folder)
        verb_x = ('executable for their group', 'runnable by members of their group',
                  'executable by the group')[i % 3]
        verb_w = ('writable for their group', 'editable by members of their group', 'writable by the group')[i % 3]
        pairs.append((_episode(f'Make the scripts in {folder} {verb_x}.', look, listing),
                      _episode(f'Make the scripts in {folder} {verb_w}.', look, listing),
                      (f'run\nchmod g+x {folder}/*.sh', f'run\nchmod g+w {folder}/*.sh')))
    return pairs


CASES = {
    'insert': dict(task='insert_line_at_changelog_heading', habit='r11_s42', donor='r10_2_0', pairs=insert_pairs,
                   toward='insert under a heading', away='append at the end'),
    'chmod': dict(task='executable_tools_group_pending', habit='r12_s42', donor='r10_2_0', pairs=chmod_pairs,
                  toward='let the group execute', away='let the group write'),
}


# --- lesson 3 (and 7): activation patching ------------------------------------------------------------

def patch(lab, out, name='insert'):
    case = CASES[name]
    msgs, mistake, correct, step = divergence(case['task'], case['habit'])
    head = lab.head(msgs)
    n = len(head)
    with lab.use(case['donor']):
        donor = lab.hidden(head)
        m_donor = lab.margin(head, mistake, correct)
    lab.use(case['habit'])
    m_habit = lab.margin(head, mistake, correct)
    names = ['system prompt', 'request', *[f'turn {i}' for i in range(len(msgs) - 2)], 'answer slot']
    spans = lab.spans(msgs) + [(lab.spans(msgs)[-1][1], n)]

    def closed(m):
        return round((m - m_habit) / (m_donor - m_habit), 3)

    def run(layer, lo, hi):
        def replace(h):
            h = h.clone()
            h[0, lo:hi] = donor[layer][lo:hi].to(h.dtype)
            return h
        with lab.patch(layer, replace):
            return lab.margin(head, mistake, correct)

    result = {'case': name, 'task': case['task'], 'habit_model': case['habit'], 'donor': case['donor'],
              'step': step, 'mistake': mistake, 'correct': correct, 'margin_habit_model': round(m_habit, 2),
              'margin_donor': round(m_donor, 2), 'all_positions': {}, 'spans': {}}
    print(f"[{name}] {case['habit']} margin {m_habit:+.2f}  {case['donor']} margin {m_donor:+.2f}  "
          f"(mistake = {mistake.splitlines()[-1][:60]})", flush=True)
    for layer in range(len(lab.layers)):
        result['all_positions'][layer] = closed(run(layer, 0, n))
    print('fraction of the gap closed by patching all prompt positions, per layer:')
    print(' '.join(f'{k}:{v:.2f}' for k, v in result['all_positions'].items()), flush=True)
    for layer in range(0, len(lab.layers), 4):
        result['spans'][layer] = {nm: closed(run(layer, lo, hi)) for nm, (lo, hi) in zip(names, spans)}
        print(f'layer {layer:2}: ' + '  '.join(f'{k}={v:+.2f}' for k, v in result['spans'][layer].items()), flush=True)
    (out / f'patch-{name}.json').write_text(json.dumps(result, indent=1) + '\n')


# --- lesson 4 (and 7): steering --------------------------------------------------------------------

def steer(lab, out, name='insert'):
    torch = lab.torch
    case = CASES[name]
    msgs, mistake, correct, _ = divergence(case['task'], case['habit'])
    head = lab.head(msgs)
    lab.use(case['habit'])
    pairs = case['pairs']()
    states = [(lab.hidden(lab.head(t)), lab.hidden(lab.head(a))) for t, a, _ in pairs[:12]]
    _, away, (control_wrong, control_right) = pairs[12]  # held back: not used to build the direction
    control_head = lab.head(away)
    result = {'case': name, 'task': case['task'], 'model': case['habit'],
              'direction': f"{case['toward']} minus {case['away']}",
              'base_margin': round(lab.margin(head, mistake, correct), 2),
              'base_control': round(lab.margin(control_head, control_wrong, control_right), 2), 'sweep': {}}
    print(f"[{name}] unsteered margin {result['base_margin']:+.2f}, control {result['base_control']:+.2f}", flush=True)

    def vector(layer, alpha):
        d = torch.stack([t[layer][-1] - a[layer][-1] for t, a in states]).float().mean(0)
        scale = float(torch.stack([t[layer][-1] for t, _ in states]).float().norm(dim=-1).mean())
        return d / d.norm() * scale * alpha  # alpha is in units of a typical residual norm

    best = None
    for layer in (8, 14, 20, 26, 32, 38):
        for alpha in (0.05, 0.1, 0.2, 0.4):
            v = vector(layer, alpha)
            with lab.patch(layer, lambda h, v=v: h + v.to(h.dtype)):
                m = lab.margin(head, mistake, correct)
                control = lab.margin(control_head, control_wrong, control_right)  # must stay < 0
            result['sweep'][f'{layer}@{alpha}'] = {'margin': round(m, 2), 'control': round(control, 2)}
            print(f'layer {layer:2} alpha {alpha:.2f}: margin {m:+.2f}   control {control:+.2f}', flush=True)
            if m < 0 and control < 0 and (best is None or m < best[2]):
                best = (layer, alpha, m)
    result['unsteered_generation'] = lab.generate(head, 80)
    print('unsteered action:\n' + result['unsteered_generation'])
    if best:
        layer, alpha, _ = best
        v = vector(layer, alpha)
        with lab.patch(layer, lambda h: h + v.to(h.dtype)):
            result['steered_generation'] = lab.generate(head, 80)
            result['steered_control_generation'] = lab.generate(control_head, 60)
        result['best'] = {'layer': layer, 'alpha': alpha}
        print(f'steered (layer {layer}, alpha {alpha}) action on the roster prefix:\n' + result['steered_generation'])
        print('steered action on the control:\n' + result['steered_control_generation'])
    (out / f'steer-{name}.json').write_text(json.dumps(result, indent=1) + '\n')

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('lesson', choices=('margins', 'patch', 'steer', 'all'))
    ap.add_argument('out', type=Path)
    ap.add_argument('--case', choices=tuple(CASES), default='insert', help='patch/steer: which habit')
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    lab = Lab()
    if args.lesson in ('margins', 'all'):
        print('=== lesson: margins', flush=True)
        margins(lab, args.out)
    for name, fn in (('patch', patch), ('steer', steer)):
        if args.lesson in (name, 'all'):
            print(f'=== lesson: {name} ({args.case})', flush=True)
            fn(lab, args.out, args.case)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
