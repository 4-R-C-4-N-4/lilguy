"""Interpretability lessons 2-4 (docs/plan/INTERPRETABILITY.md). Training Python, RTX 3090, dev traces only.

    $TRAIN_PY -m dev.interp.lessons margins OUT      # lesson 2: coin flips vs habits
    $TRAIN_PY -m dev.interp.lessons patch OUT        # lesson 3: where the append-for-insert habit lives
    $TRAIN_PY -m dev.interp.lessons steer OUT        # lesson 4: can a direction flip it without training?
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev.interp.common import ADAPTERS, Lab, divergence, p, TOOLS, VERSION, verdict

R12 = ('r12_s42', 'r12_s43')
INSERT_TASK, HABIT_MODEL = 'insert_line_at_changelog_heading', 'r11_s42'


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


# --- lesson 3 ------------------------------------------------------------------------------------

def patch(lab, out):
    msgs, mistake, correct, step = divergence(INSERT_TASK, HABIT_MODEL)
    head = lab.head(msgs)
    n = len(head)
    with lab.use('r10_2_0'):
        donor = lab.hidden(head)
        m10 = lab.margin(head, mistake, correct)
    lab.use(HABIT_MODEL)
    m11 = lab.margin(head, mistake, correct)
    names = ['system prompt', 'request', *[f'turn {i}' for i in range(len(msgs) - 2)], 'answer slot']
    spans = lab.spans(msgs) + [(lab.spans(msgs)[-1][1], n)]

    def closed(m):
        return round((m - m11) / (m10 - m11), 3)

    def run(layer, lo, hi):
        def replace(h):
            h = h.clone()
            h[0, lo:hi] = donor[layer][lo:hi].to(h.dtype)
            return h
        with lab.patch(layer, replace):
            return lab.margin(head, mistake, correct)

    result = {'task': INSERT_TASK, 'habit_model': HABIT_MODEL, 'donor': 'r10_2_0', 'mistake': mistake,
              'correct': correct, 'margin_habit_model': round(m11, 2), 'margin_donor': round(m10, 2),
              'all_positions': {}, 'spans': {}}
    print(f'r11 margin {m11:+.2f}  r10 margin {m10:+.2f}  (mistake = {mistake.splitlines()[0]}…)', flush=True)
    for layer in range(len(lab.layers)):
        result['all_positions'][layer] = closed(run(layer, 0, n))
    print('fraction of the gap closed by patching all prompt positions, per layer:')
    print(' '.join(f'{k}:{v:.2f}' for k, v in result['all_positions'].items()), flush=True)
    for layer in range(0, len(lab.layers), 4):
        result['spans'][layer] = {name: closed(run(layer, lo, hi)) for name, (lo, hi) in zip(names, spans)}
        print(f'layer {layer:2}: ' + '  '.join(f'{k}={v:+.2f}' for k, v in result['spans'][layer].items()), flush=True)
    (out / 'patch.json').write_text(json.dumps(result, indent=1) + '\n')


# --- lesson 4 ------------------------------------------------------------------------------------

def contrast_prompts():
    """Synthetic, non-roster pairs: the same file read, then 'insert under a heading' vs 'append at the end'."""
    words = ['amber', 'basil', 'cedar', 'dahlia', 'ember', 'fennel', 'garnet', 'hazel', 'indigo', 'juniper',
             'kestrel', 'lilac', 'maple', 'nutmeg', 'olive', 'pepper', 'quince', 'russet', 'saffron', 'thyme']
    pairs = []
    for i in range(16):
        a, b, c, d, item = (words[(i * 5 + j) % len(words)] for j in range(5))
        path = f'{a}-notes.md'
        text = f'# {a}\n## {b.title()}\n- {c}\n\n## {d.title()}\n- {a}{i}\n'
        obs = p.render_observation(exit_code=0, stdout=text, version=VERSION)
        read = p.render_action(p.Action.call('fs.read', path=path), TOOLS, VERSION)

        def msgs(request):
            return [{'role': 'system', 'content': p.system_prompt(TOOLS, VERSION)},
                    {'role': 'user', 'content': p.user_message(request, 'do', VERSION)},
                    {'role': 'assistant', 'content': read},
                    {'role': 'user', 'content': p.observation_message(obs)}]
        pairs.append((msgs(f'Add "- {item}" directly under the ## {b.title()} heading in {path}.'),
                      msgs(f'Add "- {item}" as the very last line of {path}.'), path, item))
    return pairs


def steer(lab, out):
    torch = lab.torch
    msgs, mistake, correct, _ = divergence(INSERT_TASK, HABIT_MODEL)
    head = lab.head(msgs)
    lab.use(HABIT_MODEL)
    pairs = contrast_prompts()
    states = [(lab.hidden(lab.head(ins)), lab.hidden(lab.head(app))) for ins, app, _, _ in pairs[:12]]
    held = pairs[12:]  # control prompts not used to build the direction
    result = {'task': INSERT_TASK, 'model': HABIT_MODEL, 'base_margin': round(lab.margin(head, mistake, correct), 2),
              'sweep': {}}
    print(f"unsteered margin {result['base_margin']:+.2f}", flush=True)
    best = None
    for layer in (8, 14, 20, 26, 32, 38):
        direction = torch.stack([i[layer][-1] - a[layer][-1] for i, a in states]).float().mean(0)
        scale = float(torch.stack([i[layer][-1] for i, _ in states]).float().norm(dim=-1).mean())
        direction = direction / direction.norm() * scale  # alpha is in units of a typical residual norm
        for alpha in (0.05, 0.1, 0.2, 0.4):
            def replace(h, v=direction * alpha):
                return h + v.to(h.dtype)
            with lab.patch(layer, replace):
                m = lab.margin(head, mistake, correct)
                # control: an append request should stay an append: log P(insert) - log P(append) must stay < 0
                ins, app, path, item = held[0]
                append_cmd = f"run\nprintf '%s\\n' '- {item}' >> {path}"
                text = ins[3]['content']
                heading = [line for line in text.splitlines() if line.startswith('## ')][0]
                first = text.splitlines()[text.splitlines().index(heading) + 1]
                insert_cmd = (f'tool fs.edit\npath: {path}\nold <<<\n{heading}\n{first}\n>>>\n'
                              f'new <<<\n{heading}\n- {item}\n{first}\n>>>')
                control = lab.margin(lab.head(app), insert_cmd, append_cmd)
            result['sweep'][f'{layer}@{alpha}'] = {'margin': round(m, 2), 'append_control': round(control, 2)}
            print(f'layer {layer:2} alpha {alpha:.2f}: margin {m:+.2f}   append control (insert-vs-append) {control:+.2f}',
                  flush=True)
            if m < 0 and control < 0 and (best is None or m < best[2]):
                best = (layer, alpha, m)
    if best:
        layer, alpha, _ = best
        states_dir = torch.stack([i[layer][-1] - a[layer][-1] for i, a in states]).float().mean(0)
        scale = float(torch.stack([i[layer][-1] for i, _ in states]).float().norm(dim=-1).mean())
        v = states_dir / states_dir.norm() * scale * alpha
        with lab.patch(layer, lambda h: h + v.to(h.dtype)):
            result['steered_generation'] = lab.generate(head, 80)
            result['steered_control_generation'] = lab.generate(lab.head(held[0][1]), 60)
        result['best'] = {'layer': layer, 'alpha': alpha}
        print('steered action on the roster prefix:\n' + result['steered_generation'])
        print('steered action on the append control:\n' + result['steered_control_generation'])
    result['unsteered_generation'] = lab.generate(head, 80)
    print('unsteered action:\n' + result['unsteered_generation'])
    (out / 'steer.json').write_text(json.dumps(result, indent=1) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('lesson', choices=('margins', 'patch', 'steer', 'all'))
    ap.add_argument('out', type=Path)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    lab = Lab()
    for name, fn in (('margins', margins), ('patch', patch), ('steer', steer)):
        if args.lesson in (name, 'all'):
            print(f'=== lesson: {name}', flush=True)
            fn(lab, args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
