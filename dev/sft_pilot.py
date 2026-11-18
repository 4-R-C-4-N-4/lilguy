"""Bounded supervised LoRA pilot on the verified next-action corpus.

Development only. Runs with a separate training interpreter (torch, transformers, PEFT);
lilguy's runtime never imports this module. Offline by design: the model must already be
a local directory, and the Hub is disabled before transformers is imported.

The base and tuned predictions come from the same loaded weights, prompt rendering and
decoding (the base is the PEFT model with its adapter disabled), so a difference between
them is attributable to the adapter rather than to quantization, templates or runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import sys
import time

IGNORE = -100
# The decision in a next-action target is its leading action name, e.g. {"action": "ask".
DECISION = re.compile(r'\{\s*"action"\s*:\s*"[^"]*"')


def parse_action(text):
    """The assistant's JSON action, or None if it is not one."""
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("action"), str):
        return None
    return value


def load_rows(path):
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf8").splitlines(), 1):
        if not line.strip():
            continue
        where = f"{path}:{number}"
        try:
            messages = json.loads(line)["messages"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{where}: not a chat row") from exc
        if (not isinstance(messages, list) or len(messages) < 2
                or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                       or not isinstance(m["content"], str) for m in messages)):
            raise ValueError(f"{where}: malformed messages")
        if messages[-1]["role"] != "assistant":
            raise ValueError(f"{where}: the last message must be the assistant's answer")
        # Earlier assistant turns are conversation history (prompt), not training targets.
        if parse_action(messages[-1]["content"]) is None:
            raise ValueError(f"{where}: assistant target is not a JSON action")
        rows.append(messages)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return rows


def _input_key(messages):
    return json.dumps(messages[:-1], sort_keys=True, ensure_ascii=False)


def check_disjoint(train_rows, validation_rows):
    overlap = {_input_key(r) for r in train_rows} & {_input_key(r) for r in validation_rows}
    if overlap:
        raise ValueError(f"{len(overlap)} validation input(s) overlap the training split")


def prompt_ids(tokenizer, messages, template_kwargs=None):
    """Token ids of the conversation up to the assistant's turn. Training and generation both
    use this, so the model is trained on exactly the prefix it is later asked to continue."""
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                         **(template_kwargs or {}))
    return tokenizer(text, add_special_tokens=False)["input_ids"]


def encode_example(tokenizer, messages, max_length, template_kwargs=None, decision_weight=1.0):
    """Prompt + answer + end-of-turn, with labels only on the answer.

    `weights` scale each target token's loss. The edit/ask/done decision is one or two tokens
    among dozens of easily copied argument tokens, so a plain token mean can reach ~0 while
    the decision stays wrong; `decision_weight` up-weights the leading action-name span.
    """
    if tokenizer.eos_token_id is None:
        raise ValueError("tokenizer has no end-of-turn token")
    prompt = prompt_ids(tokenizer, messages[:-1], template_kwargs)
    content = messages[-1]["content"]
    encoded = tokenizer(content, add_special_tokens=False, return_offsets_mapping=True)
    target = encoded["input_ids"] + [tokenizer.eos_token_id]
    target_weights = [1.0] * len(target)
    if decision_weight != 1.0:
        match = DECISION.match(content)
        if match is None:
            raise ValueError("decision weighting needs a target that starts with its action")
        for index, (start, _) in enumerate(encoded["offset_mapping"]):
            if start < match.end():
                target_weights[index] = float(decision_weight)
    ids = prompt + target
    if len(ids) > max_length:
        raise ValueError(f"example has {len(ids)} tokens, above max_length={max_length}")
    return {"input_ids": ids, "labels": [IGNORE] * len(prompt) + target,
            "weights": [0.0] * len(prompt) + target_weights}


def weighted_loss(model, ids, labels, weights):
    """Weighted mean next-token cross-entropy; equals the model's own loss when all weights are 1."""
    import torch
    import torch.nn.functional as F

    logits = model(input_ids=ids, attention_mask=torch.ones_like(ids)).logits[:, :-1].float()
    targets, token_weights = labels[:, 1:], weights[:, 1:].to(logits.dtype)
    losses = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1),
                             ignore_index=IGNORE, reduction="none").view(targets.shape)
    return (losses * token_weights).sum() / token_weights.sum()


def score(golds, predictions):
    by_action = {}
    exact = matched = invalid = 0
    for gold_text, predicted_text in zip(golds, predictions, strict=True):
        gold = parse_action(gold_text)
        bucket = by_action.setdefault(gold["action"], {"n": 0, "exact": 0, "action_match": 0})
        bucket["n"] += 1
        predicted = parse_action(predicted_text)
        if predicted is None:
            invalid += 1
            continue
        if predicted["action"] == gold["action"]:
            bucket["action_match"] += 1
            matched += 1
        if predicted == gold:
            bucket["exact"] += 1
            exact += 1
    majority, count = Counter(parse_action(g)["action"] for g in golds).most_common(1)[0]
    return {"n": len(golds), "exact": exact, "action_match": matched, "invalid": invalid,
            "majority_action": majority, "majority_baseline": count,
            "by_gold_action": dict(sorted(by_action.items()))}


def complete(model, tokenizer, messages, *, max_new_tokens, device, template_kwargs=None):
    """Greedy continuation of a conversation, rendered exactly as in training."""
    import torch

    model.eval()
    with torch.no_grad():
        ids = torch.tensor([prompt_ids(tokenizer, messages, template_kwargs)], device=device)
        output = model.generate(
            input_ids=ids, attention_mask=torch.ones_like(ids), max_new_tokens=max_new_tokens,
            do_sample=False, eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None
            else tokenizer.eos_token_id)
    return tokenizer.decode(output[0, ids.shape[1]:], skip_special_tokens=True).strip()


def generate(model, tokenizer, rows, *, max_new_tokens, device, template_kwargs=None):
    return [complete(model, tokenizer, messages[:-1], max_new_tokens=max_new_tokens, device=device,
                     template_kwargs=template_kwargs) for messages in rows]


def _evaluate(model, tokenizer, rows, **kwargs):
    predictions = generate(model, tokenizer, rows, **kwargs)
    return {"score": score([r[-1]["content"] for r in rows], predictions), "predictions": predictions}


def run_pilot(model, tokenizer, train_rows, validation_rows, *, out_dir, steps, lr, rank, target_modules,
              max_length, max_new_tokens, device, seed, alpha=None, accumulation=1, template_kwargs=None,
              gradient_checkpointing=False, decision_weight=1.0, metadata=None):
    import torch
    from peft import LoraConfig, get_peft_model

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    check_disjoint(train_rows, validation_rows)
    random.seed(seed)
    torch.manual_seed(seed)
    examples = [encode_example(tokenizer, r, max_length, template_kwargs, decision_weight)
                for r in train_rows]
    for r in validation_rows:
        encode_example(tokenizer, r, max_length, template_kwargs)  # same length limit, fail early

    model.to(device)
    if gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    lora = LoraConfig(r=rank, lora_alpha=alpha or 2 * rank, lora_dropout=0.0,
                      target_modules=target_modules, task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    trainable, total = model.get_nb_trainable_parameters()
    generation = {"max_new_tokens": max_new_tokens, "device": device, "template_kwargs": template_kwargs}

    with model.disable_adapter():
        base = _evaluate(model, tokenizer, validation_rows, **generation)

    cuda = str(device).startswith("cuda")
    if cuda:
        torch.cuda.reset_peak_memory_stats(device)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    order, losses, tokens = [], [], 0
    started = time.perf_counter()
    model.train()
    for _ in range(steps):
        total_loss = 0.0
        for _ in range(accumulation):
            if not order:
                order = list(range(len(examples)))
                random.shuffle(order)
            example = examples[order.pop()]
            ids = torch.tensor([example["input_ids"]], device=device)
            labels = torch.tensor([example["labels"]], device=device)
            weights = torch.tensor([example["weights"]], device=device)
            loss = weighted_loss(model, ids, labels, weights)
            if not torch.isfinite(loss):
                raise FloatingPointError("non-finite training loss")
            (loss / accumulation).backward()
            total_loss += loss.item() / accumulation
            tokens += ids.shape[1]
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        losses.append(round(total_loss, 6))
    if cuda:
        torch.cuda.synchronize(device)
    seconds = time.perf_counter() - started
    peak = torch.cuda.max_memory_allocated(device) if cuda else None

    tuned = _evaluate(model, tokenizer, validation_rows, **generation)
    tuned_train = _evaluate(model, tokenizer, train_rows, **generation)
    model.save_pretrained(out_dir / "adapter")
    adapter_bytes = sum(p.stat().st_size for p in (out_dir / "adapter").rglob("*") if p.is_file())

    report = {
        "metadata": metadata or {},
        "config": {"steps": steps, "lr": lr, "rank": rank, "alpha": alpha or 2 * rank,
                   "target_modules": target_modules, "accumulation": accumulation, "seed": seed,
                   "max_length": max_length, "max_new_tokens": max_new_tokens, "device": str(device),
                   "template_kwargs": template_kwargs or {}, "gradient_checkpointing": gradient_checkpointing,
                   "decision_weight": decision_weight,
                   "train_rows": len(train_rows), "validation_rows": len(validation_rows),
                   "longest_example_tokens": max(len(e["input_ids"]) for e in examples)},
        "train": {"losses": losses, "tokens": tokens, "seconds": round(seconds, 3),
                  "tokens_per_second": round(tokens / seconds, 1) if seconds else None,
                  "peak_memory_bytes": peak, "trainable_parameters": trainable,
                  "total_parameters": total, "adapter_bytes": adapter_bytes},
        "eval": {"base": base, "tuned": tuned, "tuned_train": tuned_train},
    }
    report = json.loads(json.dumps(report))
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _device(choice):
    import torch

    if choice != "auto":
        return choice
    for index in range(torch.cuda.device_count()):
        if "3090" in torch.cuda.get_device_name(index):
            return f"cuda:{index}"
    raise SystemExit("no RTX 3090 found; pass --device explicitly")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, type=Path, help="local model directory (no downloads)")
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new directory for adapter and report")
    parser.add_argument("--steps", type=int, default=150)
    parser.add_argument("--accumulation", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int)
    parser.add_argument("--target-modules", default="all-linear",
                        help='"all-linear" or a comma-separated list of module names')
    parser.add_argument("--max-length", type=int, default=3072)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--template-kwargs", default='{"enable_thinking": false}')
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", choices=["bfloat16", "float32"], default="bfloat16")
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--decision-weight", type=float, default=1.0,
                        help="loss weight on the leading action-name tokens (1 = plain token mean)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if not args.model.is_dir():
        parser.error("--model must be an existing local directory")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import peft
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = _device(args.device)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True,
                                                 dtype=getattr(torch, args.dtype))
    modules = args.target_modules if args.target_modules == "all-linear" else args.target_modules.split(",")
    metadata = {
        "model_dir": str(args.model.resolve()), "model_class": type(model).__name__,
        "model_config_sha256": _sha256(args.model / "config.json"),
        "train_sha256": _sha256(args.train), "validation_sha256": _sha256(args.validation),
        "dtype": args.dtype, "eos_token": tokenizer.eos_token,
        "gpu": torch.cuda.get_device_name(device) if device.startswith("cuda") else None,
        "versions": {"python": platform.python_version(), "torch": torch.__version__,
                     "transformers": transformers.__version__, "peft": peft.__version__},
    }
    report = run_pilot(model, tokenizer, load_rows(args.train), load_rows(args.validation),
                       out_dir=args.out, steps=args.steps, lr=args.lr, rank=args.rank, alpha=args.alpha,
                       target_modules=modules, accumulation=args.accumulation, max_length=args.max_length,
                       max_new_tokens=args.max_new_tokens, device=device, seed=args.seed,
                       template_kwargs=json.loads(args.template_kwargs),
                       gradient_checkpointing=args.gradient_checkpointing,
                       decision_weight=args.decision_weight, metadata=metadata)
    summary = {name: result["score"] for name, result in report["eval"].items()}
    print(json.dumps({"train": {k: v for k, v in report["train"].items() if k != "losses"},
                      "eval": summary}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
