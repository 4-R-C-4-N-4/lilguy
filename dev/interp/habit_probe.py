"""Why does a tuned lilguy model choose an action? Probe one decision point, inside the model.

    LILGUY_TRAIN_PYTHON -m dev.interp.habit_probe OUT [--case header_skip]

Lesson 1 of docs/plan/INTERPRETABILITY.md. Development data only (an 80-task roster prefix and
its counterfactual twin); never a held-out task. No sandbox, no server: one forward pass per
question on the RTX 3090, base weights plus each LoRA adapter, all at bfloat16.

Three instruments, each answering a different question:

1. **Preference** (behaviour): log P(habit) - log P(correct) for two complete candidate actions
   at the same prefix. Positive means the model prefers the habit. Run on the real fixture and
   on a counterfactual where the habit would be right (e.g. the file *has* a header): if the
   preference does not move between the two, the model is not reading the file for this choice.
2. **Layer ablation** (where): switch the adapter's update off in one band of layers at a time
   and re-measure. A band whose removal kills the habit is where the fine-tune put it.
3. **Logit lens** (when): decode each layer's residual stream at the decision token through the
   final norm and unembedding, and watch the habit token's probability rise layer by layer.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lilguy import protocol as p  # noqa: E402

BASE = Path.home() / '.cache/huggingface/hub/models--openbmb--MiniCPM5-2B/snapshots/42433e90dad95123ab87729fd7011e7110629556'
FACTORY = ROOT / 'reports' / 'factory'
ADAPTERS = {  # label (no dots or spaces: peft module names) -> pilot directory (96 MB adapters only)
    'r10_2_0': 'pilot-5bw___5q', 'r11_s42': 'pilot-qn939y7n', 'r11_s43': 'pilot-m4rfzsq1',
    'r12_s42': 'pilot-n8gbd5zn', 'r12_s43': 'pilot-tjwmpsj2',
}
VERSION = 5

# One decision, a counterfactual twin, two candidate actions, and the token where they diverge.
CASES = {
    'header_skip': dict(
        request='What is the net total of the signed adjustments in adjustments.txt? Do not modify it.',
        mode='ask', path='adjustments.txt',
        files={'real (no header)': '18\n-5\n2\n-4\n', 'twin (has header)': 'amount\n18\n-5\n2\n-4\n'},
        habit="run\nawk 'NR>1 {s+=$0} END {print s}' adjustments.txt",
        correct="run\nawk '{s+=$0} END {print s}' adjustments.txt",
        diverge="run\nawk '",  # the lens reads the next token here: 'NR' (habit) vs '{' (correct)
    ),
}


def messages(case, content):
    tools = p.load_tools()
    read = p.Action.call('fs.read', path=case['path'])
    observation = p.render_observation(exit_code=0, stdout=content, version=VERSION)
    return [{'role': 'system', 'content': p.system_prompt(tools, VERSION)},
            {'role': 'user', 'content': p.user_message(case['request'], case['mode'], VERSION)},
            {'role': 'assistant', 'content': p.render_action(read, tools, VERSION)},
            {'role': 'user', 'content': p.observation_message(observation)}]


def main(argv=None):
    import peft
    import torch
    import transformers

    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out', type=Path)
    ap.add_argument('--case', choices=tuple(CASES), default='header_skip')
    ap.add_argument('--bands', type=int, default=6, help='layer bands for the ablation')
    args = ap.parse_args(argv)
    case = CASES[args.case]
    args.out.mkdir(parents=True, exist_ok=True)

    tok = transformers.AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    base = transformers.AutoModelForCausalLM.from_pretrained(BASE, local_files_only=True, dtype=torch.bfloat16)
    labels = list(ADAPTERS)
    model = peft.PeftModel.from_pretrained(base, FACTORY / ADAPTERS[labels[0]] / 'minicpm/training/adapter',
                                           adapter_name=labels[0])
    for label in labels[1:]:
        model.load_adapter(FACTORY / ADAPTERS[label] / 'minicpm/training/adapter', adapter_name=label)
    model = model.cuda().eval()
    n_layers = model.config.num_hidden_layers
    end = tok.convert_tokens_to_ids('<|im_end|>')

    def prompt_ids(content):
        text = tok.apply_chat_template(messages(case, content), tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False)
        return tok(text, add_special_tokens=False)['input_ids']

    @torch.no_grad()
    def logprob(content, completion):
        """Sum of log P over the completion's tokens (and the end token) given the prefix."""
        head = prompt_ids(content)
        tail = tok(completion, add_special_tokens=False)['input_ids'] + [end]
        ids = torch.tensor([head + tail], device='cuda')
        logits = model(ids).logits[0, len(head) - 1:-1].float().log_softmax(-1)
        return float(logits.gather(1, ids[0, len(head):, None]).sum())

    def preference(content):
        return logprob(content, case['habit']) - logprob(content, case['correct'])

    def use(label):
        if label == 'stock':
            return model.disable_adapter()
        model.set_adapter(label)
        import contextlib
        return contextlib.nullcontext()

    results = {'case': args.case, 'candidates': {'habit': case['habit'], 'correct': case['correct']},
               'preference': {}, 'ablation': {}, 'lens': {}}

    # 1. Preference on the real fixture and its counterfactual twin.
    for label in ['stock', *labels]:
        with use(label):
            results['preference'][label] = {name: round(preference(c), 2) for name, c in case['files'].items()}

    # 2. Layer-band ablation of each adapter's update, on the real fixture.
    real = case['files'][next(iter(case['files']))]
    bands = [(i * n_layers // args.bands, (i + 1) * n_layers // args.bands) for i in range(args.bands)]

    def set_scale(label, lo, hi, factor):
        for name, module in model.named_modules():
            if hasattr(module, 'scaling') and isinstance(module.scaling, dict) and label in module.scaling:
                layer = int(name.split('layers.')[1].split('.')[0])
                if lo <= layer < hi:
                    module.scaling[label] = module._lilguy_scale[label] * factor

    for name, module in model.named_modules():
        if hasattr(module, 'scaling') and isinstance(module.scaling, dict):
            module._lilguy_scale = dict(module.scaling)
    for label in labels:
        model.set_adapter(label)
        row = {'all layers on': round(preference(real), 2)}
        for lo, hi in bands:
            set_scale(label, lo, hi, 0.0)
            row[f'off {lo}-{hi - 1}'] = round(preference(real), 2)
            set_scale(label, lo, hi, 1.0)
        for lo, hi in bands:  # the converse: the update only in this band
            set_scale(label, 0, n_layers, 0.0)
            set_scale(label, lo, hi, 1.0)
            row[f'only {lo}-{hi - 1}'] = round(preference(real), 2)
            set_scale(label, 0, n_layers, 1.0)
        results['ablation'][label] = row

    # 3. Logit lens at the divergence token.
    habit_tok = tok(case['habit'], add_special_tokens=False)['input_ids']
    correct_tok = tok(case['correct'], add_special_tokens=False)['input_ids']
    k = next(i for i, (a, b) in enumerate(zip(habit_tok, correct_tok)) if a != b)
    pair = {'habit': tok.decode([habit_tok[k]]), 'correct': tok.decode([correct_tok[k]])}
    results['lens_tokens'] = pair
    norm, unembed = model.base_model.model.model.norm, model.base_model.model.lm_head
    for label in ['stock', *labels]:
        with use(label), torch.no_grad():
            for fname, content in case['files'].items():
                ids = torch.tensor([prompt_ids(content) + habit_tok[:k]], device='cuda')
                hidden = model(ids, output_hidden_states=True).hidden_states
                curve = []
                for h in hidden[1:]:
                    probs = unembed(norm(h[0, -1])).float().softmax(-1)
                    curve.append([round(float(probs[habit_tok[k]]), 4), round(float(probs[correct_tok[k]]), 4)])
                results['lens'].setdefault(label, {})[fname] = curve

    (args.out / 'probe.json').write_text(json.dumps(results, indent=1) + '\n')
    print(json.dumps({k: v for k, v in results.items() if k != 'lens'}, indent=1))
    print('lens tokens', pair)
    for label, by_file in results['lens'].items():
        for fname, curve in by_file.items():
            marks = ' '.join(f'{h:.2f}/{c:.2f}' for h, c in curve[::6] + [curve[-1]])
            print(f'lens {label:10} {fname:18} habit/correct every 6 layers: {marks}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
