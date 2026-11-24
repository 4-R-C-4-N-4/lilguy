"""Shared plumbing for the interpretability lessons (docs/plan/INTERPRETABILITY.md).

Run with the training Python (torch/transformers/peft). Development traces only: every prefix
comes from an 80-task roster run on interface v5, never from a held-out suite.
"""
from __future__ import annotations

import contextlib
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# The roster definitions import the app's own dependencies (mcp, ...). Append the project venv's
# site-packages at the END of sys.path, as dev/train_tests.sh does, so it cannot shadow torch.
sys.path.extend(str(s) for s in (ROOT / '.venv' / 'lib').glob('python*/site-packages'))

from lilguy import protocol as p  # noqa: E402

BASE = Path.home() / '.cache/huggingface/hub/models--openbmb--MiniCPM5-2B/snapshots/42433e90dad95123ab87729fd7011e7110629556'
FACTORY = ROOT / 'reports' / 'factory'
ADAPTERS = {  # label (no dots or spaces: peft module names) -> pilot directory
    'r10_2_0': 'pilot-5bw___5q', 'r11_s42': 'pilot-qn939y7n', 'r11_s43': 'pilot-m4rfzsq1',
    'r12_s42': 'pilot-n8gbd5zn', 'r12_s43': 'pilot-tjwmpsj2',
}
# Roster runs on interface v5, per model: the traces every prefix is taken from.
RUNS = {
    'r10_2_0': ['fast12-bazwwl4u', 'broad-t887e76u'],
    **{label: [f'{pilot}/minicpm/tuned/fast12', f'{pilot}/minicpm/tuned/broad']
       for label, pilot in ADAPTERS.items() if label != 'r10_2_0'},
}
VERSION = 5
TOOLS = p.load_tools()


def verdict(label, task_id):
    for d in RUNS[label]:
        hits = glob.glob(str(FACTORY / d / f'task_{task_id}.json'))
        if hits:
            return json.loads(Path(hits[0]).read_text())
    raise KeyError(f'{task_id} not in {label} runs')


def request_of(task_id):
    from dev import broad_runner, fast12
    for task in (*fast12.TASKS, *(t for t, _ in broad_runner.task_graders())):
        if task.id == task_id:
            return task.request
    raise KeyError(task_id)


def render(event_action):
    return p.render_action(p.Action(**event_action), TOOLS, VERSION)


def prefix_messages(task_id, mode, events):
    msgs = [{'role': 'system', 'content': p.system_prompt(TOOLS, VERSION)},
            {'role': 'user', 'content': p.user_message(request_of(task_id), mode, VERSION)}]
    for e in events:
        msgs.append({'role': 'assistant', 'content': render(e['action'])})
        msgs.append({'role': 'user', 'content': p.observation_message(e['observation'])})
    return msgs


def divergence(task_id, failing, passing='r10_2_0'):
    """First decision where the failing run left the passing run, with the shared history before it.
    Returns (messages, mistake, correct, step) or None when there is nothing to compare."""
    fv, pv = verdict(failing, task_id), verdict(passing, task_id)
    if fv['passed'] or not pv['passed']:
        return None
    fe, pe = fv['model']['events'], pv['model']['events']
    k = 0
    while k < len(fe) and k < len(pe) and fe[k]['action'] == pe[k]['action']:
        k += 1

    def action_at(verdict_, events, i):
        if i < len(events):
            return render(events[i]['action'])
        terminal = verdict_['model']['terminal']
        if terminal in ('done', 'ask'):
            return p.render_action(p.Action(terminal, text=verdict_['model'].get('answer') or ''), TOOLS, VERSION)
        return None  # budget / invalid: no action to score

    mistake, correct = action_at(fv, fe, k), action_at(pv, pe, k)
    if mistake is None or correct is None or mistake == correct:
        return None
    return prefix_messages(task_id, fv['mode'] or 'do', fe[:k]), mistake, correct, k


class Lab:
    """Base MiniCPM5-2B with every adapter loaded; switch with `use(label)` ('stock' = no adapter)."""

    def __init__(self):
        import peft
        import torch
        import transformers
        self.torch = torch
        self.tok = transformers.AutoTokenizer.from_pretrained(BASE, local_files_only=True)
        base = transformers.AutoModelForCausalLM.from_pretrained(BASE, local_files_only=True, dtype=torch.bfloat16)
        labels = list(ADAPTERS)
        model = peft.PeftModel.from_pretrained(base, FACTORY / ADAPTERS[labels[0]] / 'minicpm/training/adapter',
                                               adapter_name=labels[0])
        for label in labels[1:]:
            model.load_adapter(FACTORY / ADAPTERS[label] / 'minicpm/training/adapter', adapter_name=label)
        self.model = model.cuda().eval()
        self.layers = self.model.base_model.model.model.layers
        self.norm = self.model.base_model.model.model.norm
        self.unembed = self.model.base_model.model.lm_head
        self.end = self.tok.convert_tokens_to_ids('<|im_end|>')
        self.labels = labels

    def use(self, label):
        if label == 'stock':
            return self.model.disable_adapter()
        self.model.set_adapter(label)
        return contextlib.nullcontext()

    def head(self, messages):
        text = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        return self.tok(text, add_special_tokens=False)['input_ids']

    def spans(self, messages):
        """Token span [start, end) of each message in the rendered prompt (cumulative re-rendering)."""
        out, prev = [], 0
        for i in range(1, len(messages) + 1):
            text = self.tok.apply_chat_template(messages[:i], tokenize=False, add_generation_prompt=False,
                                                enable_thinking=False)
            n = len(self.tok(text, add_special_tokens=False)['input_ids'])
            out.append((prev, n))
            prev = n
        return out

    def logprob(self, head, completion):
        torch = self.torch
        tail = self.tok(completion, add_special_tokens=False)['input_ids'] + [self.end]
        ids = torch.tensor([head + tail], device='cuda')
        with torch.no_grad():
            logits = self.model(ids).logits[0, len(head) - 1:-1].float().log_softmax(-1)
        return float(logits.gather(1, ids[0, len(head):, None]).sum())

    def margin(self, head, mistake, correct):
        """log P(mistake) - log P(correct), in nats: positive means the mistake is preferred."""
        return self.logprob(head, mistake) - self.logprob(head, correct)

    def hidden(self, head):
        """Residual stream after every decoder layer, for the prompt only: list of [T, d] tensors.
        Captured with hooks: HF's `hidden_states[-1]` has the final norm applied, a layer output does not."""
        torch = self.torch
        captured = []

        def hook(_module, _inputs, output):
            captured.append((output[0] if isinstance(output, tuple) else output)[0].detach())
        handles = [layer.register_forward_hook(hook) for layer in self.layers]
        try:
            with torch.no_grad():
                self.model(torch.tensor([head], device='cuda'))
        finally:
            for handle in handles:
                handle.remove()
        return captured

    @contextlib.contextmanager
    def patch(self, layer, replace):
        """Replace layer `layer`'s output at chosen positions: replace(hidden[1,T,d]) -> hidden."""
        def hook(_module, _inputs, output):
            if isinstance(output, tuple):
                return (replace(output[0]), *output[1:])
            return replace(output)
        handle = self.layers[layer].register_forward_hook(hook)
        try:
            yield
        finally:
            handle.remove()

    def generate(self, head, max_new_tokens=60):
        torch = self.torch
        with torch.no_grad():
            out = self.model.generate(torch.tensor([head], device='cuda'), max_new_tokens=max_new_tokens,
                                      do_sample=False, eos_token_id=self.end)
        return self.tok.decode(out[0, len(head):], skip_special_tokens=True)
