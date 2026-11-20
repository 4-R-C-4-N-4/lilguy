"""Training-only decision diagnostics: teacher forcing vs bounded unconstrained generation.

Run with dev/trainpy.sh under a memory-bounded user scope. Never runs generated actions and
never reads the development or held-out tasks. All inputs pass the corpus evidence verifier.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import gc
import hashlib
import json
import os
from pathlib import Path
import random
import time

from dev import v2_train


def generated_class(text):
    from dev.decision_metrics import action_class
    return action_class(text)


def teacher_record(expected, target_ids, decision, predicted_ids, token_logprobs, decode):
    if not len(target_ids) == len(decision) == len(predicted_ids) == len(token_logprobs) or not any(decision):
        raise ValueError('aligned nonempty decision spans required')
    predicted = [p for p, take in zip(predicted_ids, decision) if take]
    correct = all(t == p for t, p, take in zip(target_ids, predicted_ids, decision) if take)
    return {'class': expected, 'teacher_prediction': generated_class(decode(predicted)),
            'teacher_correct': correct, 'decision_logprob': sum(p for p, take in zip(token_logprobs, decision) if take),
            'decision_tokens': sum(decision), 'teacher_text': decode(predicted), 'generated': None}


def decode_suffix(sequence, prompt_length, decode):
    if not 0 <= prompt_length <= len(sequence):
        raise ValueError('invalid prompt length')
    return decode(sequence[prompt_length:])


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def messages_digest(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verified_inputs(data):
    from dev.v2_corpus import verified_rows
    data = Path(data)
    messages = verified_rows(data)
    saved = [json.loads(line) for line in (data / 'train.jsonl').read_text().splitlines()]
    if [r['messages'] for r in saved] != messages:
        raise ValueError('rows changed after verification')
    evidence = {e['task']['id']: e for e in json.loads((data / 'effects.json').read_text())}
    return [{**r, 'row': i, 'expected': generated_class(m[-1]['content']),
             'family': evidence[r['episode']]['family'], 'behaviour': evidence[r['episode']]['behaviour'],
             'category': evidence[r['episode']]['category']} for i, (r, m) in enumerate(zip(saved, messages))]


def select_rows(rows, per_class, seed):
    from dev.decision_metrics import stratified_indices
    return [rows[i] for i in stratified_indices([r['expected'] for r in rows], per_class, seed)]


LOOK = ('tool fs.list', 'tool fs.find', 'tool fs.read', 'tool fs.grep')
CONTRAST = ('ask-ambiguous', 'ask-missing-detail', 'act-unambiguous')


def contrast_decision_points(rows):
    """Rows where an ask/act episode first commits after only looking: ask, act or answer."""
    picks = []
    for i, row in enumerate(rows):
        actions = [m['content'].split('\n', 1)[0] for m in row['messages'] if m['role'] == 'assistant']
        if row['behaviour'] in CONTRAST and actions[-1] not in LOOK and all(a in LOOK for a in actions[:-1]):
            picks.append(i)
    return picks


def diagnose(model, tokenizer, base, selected, *, generate_per_class, max_new_tokens, seed):
    import torch
    from dev import decision_metrics
    end_id = tokenizer.convert_tokens_to_ids(base['end_token'])
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else end_id
    encoded = [v2_train.encode(tokenizer, r['messages'], base, end_id, 5.0, 4096) for r in selected]
    lengths = [len(r['prompt']) + len(r['target']) for r in encoded]
    batches = v2_train.make_batches(lengths, 24576, 16, random.Random(0))
    results: list[dict | None] = [None] * len(selected)
    decode = lambda ids: tokenizer.decode(ids, skip_special_tokens=True)  # noqa: E731
    model.eval()
    start = time.monotonic()
    with torch.inference_mode():
        for batch_ids in batches:
            batch = v2_train.collate([encoded[i] for i in batch_ids], pad_id, torch, 'cuda')
            logits, _ = v2_train.forward_targets(model, batch, torch)
            labels, decision = batch[3], batch[5]
            logps = logits.log_softmax(-1).gather(-1, labels.clamp(min=0).unsqueeze(-1)).squeeze(-1)
            predicted = logits.argmax(-1).cpu().tolist()
            targets, masks, probs = labels.cpu().tolist(), decision.cpu().tolist(), logps.cpu().tolist()
            for k, idx in enumerate(batch_ids):
                source = selected[idx]
                record = teacher_record(source['expected'], targets[k], masks[k], predicted[k], probs[k], decode)
                results[idx] = {**record, **{key: source[key] for key in ('row', 'episode', 'family',
                                                                         'behaviour', 'category')},
                                'target': source['messages'][-1]['content']}
    teacher_seconds = time.monotonic() - start
    generate_ids = decision_metrics.stratified_indices([r['expected'] for r in selected], generate_per_class, seed + 1)
    start = time.monotonic()
    with torch.inference_mode():
        for idx in generate_ids:
            prompt = encoded[idx]['prompt']
            ids = torch.tensor([prompt], dtype=torch.long, device='cuda')
            output = model.generate(input_ids=ids, attention_mask=torch.ones_like(ids), do_sample=False,
                                    max_new_tokens=max_new_tokens, eos_token_id=end_id, pad_token_id=pad_id,
                                    use_cache=True)
            full = output[0].tolist()
            text = decode_suffix(full, len(prompt), decode)
            results[idx]['generated'] = generated_class(text)
            results[idx]['generated_text'] = text
            results[idx]['generation_tokens'] = len(full) - len(prompt)
            results[idx]['generation_hit_limit'] = len(full) - len(prompt) == max_new_tokens and full[-1] != end_id
    return {'summary': decision_metrics.summarize(results), 'rows': results,
            'teacher_seconds': round(teacher_seconds, 3), 'generation_seconds': round(time.monotonic() - start, 3),
            'generation_max_new_tokens': max_new_tokens, 'generation_rows': len(generate_ids)}


def load_model(key, adapters):
    import peft
    import torch
    import transformers
    if {'torch': torch.__version__, 'transformers': transformers.__version__, 'peft': peft.__version__} != v2_train.VERSIONS:
        raise ValueError('training dependency versions changed')
    if torch.cuda.device_count() != 1 or 'RTX 3090' not in torch.cuda.get_device_name(0):
        raise ValueError('exactly one visible RTX 3090 required')
    base = v2_train.BASES[key]
    v2_train.check_base(key, base['snapshot'])
    model, info = getattr(transformers, base['model_class']).from_pretrained(
        base['snapshot'], local_files_only=True, dtype=torch.bfloat16, output_loading_info=True)
    if any(info.get(k) for k in ('missing_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError(f'pinned base loading failed: {info}')
    model.to('cuda')
    tokenizer = transformers.AutoTokenizer.from_pretrained(base['snapshot'], local_files_only=True)
    for n, (label, directory) in enumerate(adapters.items()):
        cfg = json.loads((directory / 'adapter_config.json').read_text())
        if Path(cfg['base_model_name_or_path']).resolve() != base['snapshot'].resolve():
            raise ValueError(f'adapter is not pinned to this base: {directory}')
        if n == 0:
            model = peft.PeftModel.from_pretrained(model, directory, adapter_name=label)
        else:
            model.load_adapter(directory, adapter_name=label)
    return model.eval(), tokenizer


def run(args):
    import torch
    from dev import decision_metrics
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    rows = verified_inputs(args.data)
    r1_rows = verified_inputs(args.r1_data)
    r1_members = {messages_digest(r['messages']) for r in r1_rows}
    selected = ([rows[i] for i in contrast_decision_points(rows)] if args.contrast
                else select_rows(rows, args.per_class, args.seed))
    args.out.mkdir(parents=True, exist_ok=True)
    corpus_digest = digest(args.data / 'train.jsonl')
    manifest = {'data': str(args.data.resolve()), 'data_sha256': corpus_digest, 'source_rows': len(rows),
                'sample_rows': [r['row'] for r in selected], 'seed': args.seed, 'per_class': args.per_class,
                'selection': 'contrast decision points' if args.contrast else 'stratified by class',
                'generate_per_class': args.generate_per_class, 'max_new_tokens': args.max_new_tokens,
                'source_class_counts': {c: sum(r['expected'] == c for r in rows) for c in decision_metrics.ACTION_CLASSES},
                'models': {}}
    for key in args.base:
        adapters = {label: root / key / 'training/adapter' for label, root in (('r1', args.r1), ('r2', args.r2))}
        model, tokenizer = load_model(key, adapters)
        base = v2_train.BASES[key]
        for label in ('stock', 'r1', 'r2'):
            if label != 'stock':
                model.set_adapter(label)
            context = model.disable_adapter() if label == 'stock' else nullcontext()
            with context:
                result = diagnose(model, tokenizer, base, selected, generate_per_class=args.generate_per_class,
                                  max_new_tokens=args.max_new_tokens, seed=args.seed)
            if label != 'stock':
                source = args.r1_data if label == 'r1' else args.data
                original = args.r1 if label == 'r1' else args.r2
                train_report = json.loads((original / key / 'training/train-report.json').read_text())
                if train_report['training_sha256'] != digest(source / 'train.jsonl'):
                    raise ValueError('diagnostic corpus does not match recorded adapter training source')
            for sample, record in zip(selected, result['rows']):
                record['seen_in_checkpoint_training'] = (messages_digest(sample['messages']) in r1_members
                                                         if label == 'r1' else True if label == 'r2' else None)
            result['in_sample_summary'] = decision_metrics.summarize(
                [r for r in result['rows'] if r['seen_in_checkpoint_training'] is True])
            result['new_context_summary'] = decision_metrics.summarize(
                [r for r in result['rows'] if r['seen_in_checkpoint_training'] is False])
            result['identity'] = {'base': key, 'label': label, 'revision': base['revision'],
                                  'device': torch.cuda.get_device_name(0), 'dtype': 'bfloat16',
                                  'template_kwargs': base['template_kwargs'], 'data_sha256': corpus_digest,
                                  'versions': v2_train.VERSIONS,
                                  'adapter_sha256': digest(adapters[label] / 'adapter_model.safetensors')
                                  if label != 'stock' else None}
            folder = args.out / key
            folder.mkdir(exist_ok=True)
            (folder / f'{label}.json').write_text(json.dumps(result, indent=2) + '\n')
            manifest['models'][key + '/' + label] = {'summary': result['summary'], 'path': str(folder / f'{label}.json')}
            (args.out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            print(key, label, json.dumps(result['summary']), flush=True)
        del model, tokenizer
        gc.collect()
        torch.cuda.empty_cache()
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--base', action='append', choices=tuple(v2_train.BASES), required=True)
    parser.add_argument('--r1', type=Path, default=Path('reports/factory/pilot-w74u7u0b'))
    parser.add_argument('--r2', type=Path, default=Path('reports/factory/pilot-kqfyui0g'))
    parser.add_argument('--r1-data', type=Path, default=Path('reports/corpus/v2'))
    parser.add_argument('--per-class', type=int, default=64)
    parser.add_argument('--generate-per-class', type=int, default=8)
    parser.add_argument('--max-new-tokens', type=int, default=96)
    parser.add_argument('--seed', type=int, default=29)
    parser.add_argument('--contrast', action='store_true',
                        help='all first commit points of ask/act contrast episodes instead of a class sample')
    args = parser.parse_args(argv)
    if min(args.per_class, args.generate_per_class, args.max_new_tokens) <= 0 or args.generate_per_class > args.per_class:
        parser.error('positive limits required; generation subset cannot exceed teacher subset')
    run(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
