"""Trainer v2: base-agnostic LoRA SFT on replay-verified interface-v1 next-action rows.

Recipe (roadmap step 7, "What the pilot taught"):
  * loss on the final assistant action only (prompt masked), plus the end-of-turn token;
  * decision-token weighting: tokens overlapping the action's first line (`run`, `tool fs.read`,
    `ask`, `done`) weigh `decision_weight`, the rest 1.0;
  * left-padded, length-bucketed batches under a token budget, so a 2.5B base fits a time box;
  * training length from training-split fit, never validation: stop once greedy decision accuracy
    and target-token accuracy on the training rows reach the fit thresholds, at `max_epochs`, or
    when the next epoch would overrun `max_minutes`.

Rows come only through a verifier callable (default `dev.v2_corpus:verified_rows`) that
re-checks the sandbox effect evidence. The prompt is rendered by the base's own chat template
with the same kwargs llama-server is sent at inference (`enable_thinking: false`).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import random
import time

HF = Path.home() / '.cache/huggingface/hub'
BASES = {
    'qwen08': {
        'repo': 'Qwen/Qwen3.5-0.8B', 'revision': '2fc06364715b967f1860aea9cf38778875588b17',
        'snapshot': HF / 'models--Qwen--Qwen3.5-0.8B/snapshots/2fc06364715b967f1860aea9cf38778875588b17',
        'model_class': 'Qwen3_5ForCausalLM', 'end_token': '<|im_end|>', 'licence': 'apache-2.0',
        'template_kwargs': {'enable_thinking': False}, 'convert_args': ['--no-mtp'],
    },
    'minicpm': {
        'repo': 'openbmb/MiniCPM5-2B', 'revision': '42433e90dad95123ab87729fd7011e7110629556',
        'snapshot': HF / 'models--openbmb--MiniCPM5-2B/snapshots/42433e90dad95123ab87729fd7011e7110629556',
        'model_class': 'LlamaForCausalLM', 'end_token': '<|im_end|>', 'licence': 'apache-2.0',
        'template_kwargs': {'enable_thinking': False}, 'convert_args': [],
    },
}
PARAMS = {'seed': 42, 'lr': 2e-4, 'rank': 16, 'alpha': 32, 'dropout': 0.0, 'max_length': 4096,
          'decision_weight': 5.0, 'token_budget': 24576, 'max_batch': 16, 'max_epochs': 6,
          'fit_decision': 0.99, 'fit_token': 0.98, 'max_minutes': 25.0, 'fit_rows': 800, 'max_rows': None,
          'gradient_checkpointing': True}
VERSIONS = {'torch': '2.11.0+cu128', 'transformers': '5.15.0', 'peft': '0.20.0'}
IGNORE = -100


# --- pure helpers (unit-tested without torch) ----------------------------------------------------

def check_base(key, path):
    if key not in BASES:
        raise ValueError(f'unknown base {key!r}; expected one of {sorted(BASES)}')
    base = BASES[key]
    path = Path(path)
    if path.name != base['revision'] or not (path / 'config.json').is_file():
        raise ValueError(f"expected local {base['repo']} snapshot at revision {base['revision']}")
    return base


def decision_chars(content):
    """Characters of the action's first line: the decision the model must get right."""
    return len(content.split('\n', 1)[0])


def token_weights(offsets, decision_end, weight):
    """Weight per target token from its (start, end) character span; the end token gets 1.0."""
    return [float(weight) if start < decision_end else 1.0 for start, _ in offsets]


def make_batches(lengths, token_budget, max_batch, rng):
    """Length-sorted batches whose padded size (rows x longest) stays under the token budget."""
    order = sorted(range(len(lengths)), key=lambda i: (lengths[i], i))
    batches, current = [], []
    for i in order:
        longest = max([lengths[j] for j in current] + [lengths[i]])
        if current and (len(current) + 1 > max_batch or longest * (len(current) + 1) > token_budget):
            batches.append(current)
            current = []
        current.append(i)
    if current:
        batches.append(current)
    rng.shuffle(batches)
    return batches


def stop_reason(history, *, max_epochs, fit_decision, fit_token, elapsed, max_seconds):
    """Why training ends after the epochs in `history`, or None to train another epoch."""
    last = history[-1]
    if last['decision_accuracy'] >= fit_decision and last['token_accuracy'] >= fit_token:
        return 'fit'
    if len(history) >= max_epochs:
        return 'max_epochs'
    epoch_seconds = max(h['seconds'] for h in history)
    if elapsed + epoch_seconds > max_seconds:
        return 'time_budget'
    return None


def load_verifier(spec):
    module, _, name = spec.partition(':')
    if not module or not name:
        raise ValueError('--verifier must be MODULE:FUNCTION')
    return getattr(importlib.import_module(module), name)


# --- torch side -----------------------------------------------------------------------------

def render_prompt(tokenizer, messages, base):
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                         **base['template_kwargs'])


def encode(tokenizer, messages, base, end_id, decision_weight, max_length):
    if messages[-1]['role'] != 'assistant':
        raise ValueError('the last message must be the assistant target')
    prompt = tokenizer(render_prompt(tokenizer, messages[:-1], base), add_special_tokens=False)['input_ids']
    content = messages[-1]['content']
    target = tokenizer(content, add_special_tokens=False, return_offsets_mapping=True)
    ids = list(target['input_ids']) + [end_id]
    weights = token_weights(target['offset_mapping'], decision_chars(content), decision_weight) + [1.0]
    decision = [start < decision_chars(content) for start, _ in target['offset_mapping']] + [False]
    if len(prompt) + len(ids) > max_length:
        raise ValueError(f'row has {len(prompt) + len(ids)} tokens, above max_length={max_length}')
    return {'prompt': prompt, 'target': ids, 'weights': weights, 'decision': decision}


def collate(rows, pad_id, torch, device):
    """Left-pad so every target ends at the last position; returns tensors plus the target width."""
    width = max(len(r['prompt']) + len(r['target']) for r in rows)
    tail = max(len(r['target']) for r in rows)
    ids, mask, labels, weights, decision = [], [], [], [], []
    for r in rows:
        seq = r['prompt'] + r['target']
        pad = width - len(seq)
        ids.append([pad_id] * pad + seq)
        mask.append([0] * pad + [1] * len(seq))
        lead = tail - len(r['target'])
        labels.append([IGNORE] * lead + r['target'])
        weights.append([0.0] * lead + r['weights'])
        decision.append([False] * lead + r['decision'])
    t = lambda x, dtype: torch.tensor(x, dtype=dtype, device=device)  # noqa: E731
    mask_t = t(mask, torch.long)
    positions = (mask_t.cumsum(-1) - 1).clamp(min=0)
    return (t(ids, torch.long), mask_t, positions, t(labels, torch.long), t(weights, torch.float32),
            t(decision, torch.bool), tail)


def forward_targets(model, batch, torch):
    ids, mask, positions, labels, weights, decision, tail = batch
    logits = model(input_ids=ids, attention_mask=mask, position_ids=positions, use_cache=False,
                   logits_to_keep=tail + 1).logits[:, :-1].float()
    losses = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), labels.reshape(-1),
                                               ignore_index=IGNORE, reduction='none').view(labels.shape)
    return logits, losses


def fit_metrics(model, encoded, batches, pad_id, torch):
    """Greedy agreement on the training rows: whole decision span and every target token."""
    model.eval()
    rows_ok = tokens_ok = tokens = 0
    loss_sum = weight_sum = 0.0
    with torch.no_grad():
        for batch_ids in batches:
            batch = collate([encoded[i] for i in batch_ids], pad_id, torch, 'cuda')
            logits, losses = forward_targets(model, batch, torch)
            labels, weights, decision = batch[3], batch[4], batch[5]
            valid = labels != IGNORE
            correct = (logits.argmax(-1) == labels) & valid
            tokens_ok += int(correct.sum())
            tokens += int(valid.sum())
            rows_ok += int(((correct | ~decision).all(-1)).sum())
            loss_sum += float((losses * weights).sum())
            weight_sum += float(weights.sum())
    model.train()
    return {'decision_accuracy': rows_ok / len(encoded), 'token_accuracy': tokens_ok / tokens,
            'weighted_loss': loss_sum / weight_sum}


def train(key, base_dir, data, out, *, verifier='dev.v2_corpus:verified_rows', params=None, model_override=None):
    params = {**PARAMS, **(params or {})}
    base = check_base(key, base_dir)
    rows = load_verifier(verifier)(data)
    if not rows:
        raise ValueError('verifier returned no training rows')
    verified_count = len(rows)
    if params['max_rows'] and params['max_rows'] < len(rows):  # throughput smoke runs only
        rows = random.Random(params['seed']).sample(rows, params['max_rows'])
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import peft
    import torch
    import transformers

    versions = {'torch': torch.__version__, 'transformers': transformers.__version__, 'peft': peft.__version__}
    if versions != VERSIONS:
        raise ValueError(f'training dependency mismatch: {versions}')
    if torch.cuda.device_count() != 1 or 'RTX 3090' not in torch.cuda.get_device_name(0):
        raise ValueError('trainer requires exactly one visible RTX 3090')
    out = Path(out)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    torch.manual_seed(params['seed'])
    rng = random.Random(params['seed'])
    tokenizer = transformers.AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    end_id = tokenizer.convert_tokens_to_ids(base['end_token'])
    if end_id is None or end_id == tokenizer.unk_token_id:
        raise ValueError(f"tokenizer has no {base['end_token']} token")
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else end_id
    encoded = [encode(tokenizer, m, base, end_id, params['decision_weight'], params['max_length']) for m in rows]
    lengths = [len(r['prompt']) + len(r['target']) for r in encoded]
    model_class = getattr(transformers, model_override or base['model_class'])
    model, loaded = model_class.from_pretrained(base_dir, local_files_only=True, dtype=torch.bfloat16,
                                                output_loading_info=True)
    if any(loaded.get(k) for k in ('missing_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError(f'could not load every pinned weight: {loaded}')
    model.to('cuda')
    if params['gradient_checkpointing']:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
        model.enable_input_require_grads()
    model = peft.get_peft_model(model, peft.LoraConfig(r=params['rank'], lora_alpha=params['alpha'],
                                                     lora_dropout=params['dropout'],
                                                     target_modules='all-linear', task_type='CAUSAL_LM'))
    model.train()
    adam = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=params['lr'])
    # Training-split fit is measured on a fixed random subset of the training rows (never validation).
    fit_ids = sorted(random.Random(1).sample(range(len(encoded)), min(params['fit_rows'], len(encoded))))
    fit_rows = [encoded[i] for i in fit_ids]
    eval_batches = make_batches([lengths[i] for i in fit_ids], params['token_budget'] * 2, params['max_batch'] * 2,
                                random.Random(0))
    history, start = [], time.monotonic()
    max_seconds = params['max_minutes'] * 60
    reason, steps, train_tokens = None, 0, 0
    while reason is None:
        epoch_start = time.monotonic()
        losses = []
        for batch_ids in make_batches(lengths, params['token_budget'], params['max_batch'], rng):
            batch = collate([encoded[i] for i in batch_ids], pad_id, torch, 'cuda')
            _, token_losses = forward_targets(model, batch, torch)
            weights = batch[4]
            loss = (token_losses * weights).sum() / weights.sum()
            if not torch.isfinite(loss):
                raise ValueError('non-finite training loss')
            adam.zero_grad(set_to_none=True)
            loss.backward()
            adam.step()
            losses.append(loss.item())
            steps += 1
            train_tokens += int(batch[1].sum())
        train_seconds = time.monotonic() - epoch_start
        metrics = fit_metrics(model, fit_rows, eval_batches, pad_id, torch)
        history.append({'epoch': len(history) + 1, 'mean_batch_loss': sum(losses) / len(losses),
                        'train_seconds': round(train_seconds, 1),
                        'seconds': round(time.monotonic() - epoch_start, 1), **metrics})
        print(json.dumps(history[-1]), flush=True)
        reason = stop_reason(history, max_epochs=params['max_epochs'], fit_decision=params['fit_decision'],
                             fit_token=params['fit_token'], elapsed=time.monotonic() - start, max_seconds=max_seconds)
    model.save_pretrained(out / 'adapter')
    merged = model.merge_and_unload()
    merged.save_pretrained(out / 'merged')
    tokenizer.save_pretrained(out / 'merged')
    seconds = time.monotonic() - start
    data_path = Path(data) / 'train.jsonl'
    report = {'base': key, 'repo': base['repo'], 'revision': base['revision'], 'licence': base['licence'],
              'params': params, 'versions': versions, 'verifier': verifier, 'rows': len(rows),
              'verified_rows': verified_count, 'fit_rows': len(fit_rows),
              'row_tokens': {'mean': sum(lengths) / len(lengths), 'max': max(lengths)},
              'training_sha256': hashlib.sha256(data_path.read_bytes()).hexdigest() if data_path.is_file() else None,
              'epochs': history, 'stop_reason': reason, 'optimizer_steps': steps,
              'train_tokens_per_second': round(train_tokens / sum(h['train_seconds'] for h in history), 1),
              'peak_gpu_mib': round(torch.cuda.max_memory_allocated() / 1024**2), 'seconds': round(seconds, 1),
              'device': torch.cuda.get_device_name(0)}
    (out / 'train-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('base', 'rows', 'stop_reason', 'optimizer_steps', 'seconds',
                                             'train_tokens_per_second', 'peak_gpu_mib')}), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('base_key', choices=sorted(BASES))
    parser.add_argument('base_dir', type=Path)
    parser.add_argument('data', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--verifier', default='dev.v2_corpus:verified_rows')
    parser.add_argument('--max-minutes', type=float, default=PARAMS['max_minutes'])
    parser.add_argument('--max-epochs', type=int, default=PARAMS['max_epochs'])
    parser.add_argument('--decision-weight', type=float, default=PARAMS['decision_weight'])
    parser.add_argument('--seed', type=int, default=PARAMS['seed'])
    parser.add_argument('--max-rows', type=int, help='random subset of rows (throughput smoke only)')
    parser.add_argument('--no-gradient-checkpointing', action='store_true')
    args = parser.parse_args(argv)
    train(args.base_key, args.base_dir, args.data, args.out, verifier=args.verifier,
          params={'max_minutes': args.max_minutes, 'max_epochs': args.max_epochs,
                  'decision_weight': args.decision_weight, 'seed': args.seed, 'max_rows': args.max_rows,
                  'gradient_checkpointing': not args.no_gradient_checkpointing})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
