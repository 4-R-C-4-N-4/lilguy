"""Train the pinned, text-only Qwen3.5-0.8B v1 pilot; not a release recipe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

from dev import episodes, sft_pilot, v1_pilot_data
from lilguy import protocol

BASE_REVISION = '2fc06364715b967f1860aea9cf38778875588b17'
PARAMS = {'seed': 42, 'epochs': 2, 'lr': 2e-4, 'rank': 16, 'alpha': 32, 'max_length': 2048}
VERSIONS = {'torch': '2.11.0+cu128', 'transformers': '5.15.0', 'peft': '0.20.0'}


def check_base(path):
    if path.name != BASE_REVISION or not (path / 'config.json').is_file():
        raise ValueError(f'expected local Qwen3.5-0.8B revision {BASE_REVISION}')


def verified_rows(path, profile='original'):
    try:
        evidence = json.loads((path / 'effects.json').read_text())
    except FileNotFoundError as exc:
        raise ValueError('missing sandbox effect evidence') from exc
    examples = tuple(v1_pilot_data.tasks(profile))
    gate = v1_pilot_data.audit(examples)
    if not gate['ok']:
        raise ValueError(f"split audit failed: {gate['reason']}")
    tools = protocol.load_tools()
    expected = []
    for example, entry in zip(examples, evidence, strict=True):
        record = entry['record']
        if (entry['task'] != example.manifest() or entry['source'] != example.provenance()
                or entry['staged'] != example.changes or entry['original_unchanged'] is not True
                or record['request'] != example.request or record['terminal'] != example.terminal):
            raise ValueError(f'effect evidence mismatch: {example.id}')
        events = [(protocol.Action(**turn['action']), turn['observation'], turn['is_error'])
                  for turn in record['turns']]
        if v1_pilot_data._grade(example, terminal=record['terminal'], answer=record['answer'],
                                changes=entry['staged'], events=events,
                                original_unchanged=entry['original_unchanged']):
            raise ValueError(f'effect evidence observation mismatch: {example.id}')
        messages = episodes.to_messages(record, tools)
        if tuple(m['content'] for m in messages if m['role'] == 'assistant') != example.oracle:
            raise ValueError(f'effect evidence action mismatch: {example.id}')
        expected.extend(dict(episode=example.id, messages=row) for row in v1_pilot_data.next_action_rows(messages))
    actual = [json.loads(line) for line in (path / 'train.jsonl').read_text().splitlines()]
    if actual != expected:
        raise ValueError('training rows do not match sandbox effect evidence')
    return [row['messages'] for row in actual]


def train(base, data, out, profile='original'):
    check_base(base)
    rows = verified_rows(data, profile)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import peft
    import torch
    import transformers
    from transformers import AutoTokenizer, Qwen3_5ForCausalLM

    versions = {'torch': torch.__version__, 'transformers': transformers.__version__, 'peft': peft.__version__}
    if versions != VERSIONS:
        raise ValueError(f'training dependency mismatch: {versions}')
    if torch.cuda.device_count() != 1 or 'RTX 3090' not in torch.cuda.get_device_name(0):
        raise ValueError('pilot requires exactly one visible RTX 3090')
    torch.manual_seed(PARAMS['seed'])
    rng = random.Random(PARAMS['seed'])
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    if tokenizer.eos_token != '<|im_end|>':
        raise ValueError('unexpected chat end token')
    tokenized = [sft_pilot.encode_example(tokenizer, m, PARAMS['max_length'], {'enable_thinking': False})
                 for m in rows]
    model, loaded = Qwen3_5ForCausalLM.from_pretrained(base, local_files_only=True, dtype=torch.bfloat16,
                                                       output_loading_info=True)
    if any(loaded.get(k) for k in ('missing_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError('could not load every pinned text weight')
    model.to('cuda')
    model = peft.get_peft_model(model, peft.LoraConfig(r=PARAMS['rank'], lora_alpha=PARAMS['alpha'],
                                                     target_modules='all-linear', task_type='CAUSAL_LM'))
    model.train()
    adam = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=PARAMS['lr'])
    witness = next(p for name, p in model.named_parameters() if p.requires_grad and 'lora_B' in name)
    initial = witness.detach().clone()
    epoch_losses = []
    start = time.monotonic()
    for _ in range(PARAMS['epochs']):
        rng.shuffle(tokenized)
        losses = []
        for row in tokenized:
            ids = torch.tensor([row['input_ids']], device='cuda')
            target = torch.tensor([x for x in row['labels'] if x != sft_pilot.IGNORE], device='cuda')
            logits = model(input_ids=ids, logits_to_keep=target.numel() + 1, use_cache=False).logits
            loss = torch.nn.functional.cross_entropy(logits[0, :-1].float(), target)
            if not torch.isfinite(loss):
                raise ValueError('non-finite pilot loss')
            adam.zero_grad(set_to_none=True)
            loss.backward()
            adam.step()
            losses.append(loss.item())
        epoch_losses.append(sum(losses) / len(losses))
    if torch.equal(initial, witness.detach()) or not torch.isfinite(witness).all():
        raise ValueError('pilot did not produce a finite adapter update')
    out.mkdir(mode=0o700, exist_ok=False)
    model.save_pretrained(out / 'adapter')
    merged = model.merge_and_unload()
    merged.save_pretrained(out / 'merged')
    tokenizer.save_pretrained(out / 'merged')
    report = {'base_revision': BASE_REVISION, 'profile': profile, 'params': PARAMS,
              'versions': VERSIONS, 'rows': len(rows),
              'training_sha256': hashlib.sha256((data / 'train.jsonl').read_bytes()).hexdigest(),
              'epoch_mean_loss': epoch_losses, 'peak_gpu_mib': round(torch.cuda.max_memory_allocated() / 1024**2),
              'seconds': round(time.monotonic() - start, 2), 'device': torch.cuda.get_device_name(0)}
    (out / 'train-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('data', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--profile', choices=v1_pilot_data.PROFILES, default='original')
    args = parser.parse_args()
    train(args.base, args.data, args.out, args.profile)


if __name__ == '__main__':
    main()
