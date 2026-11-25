"""Average several LoRA fine-tunes of one base into one model ("model soup"), then export Q8_0.

    $TRAIN_PY -m dev.soup OUT PILOT [PILOT ...]

Each pilot's adapter contributes its full weight change per module, ΔW = B @ A * (alpha / r). The
soup is base + mean(ΔW). LoRA factors are not averaged: A and B of different seeds live in
unrelated bases, so only their products are comparable. The result goes through the same
convert_hf_to_gguf Q8_0 export as a pilot (dev.factory_pilot.export), into OUT/minicpm/tuned-q8_0.gguf,
with OUT/plan.json recording the adapters and checksums. The merged fp16 weights are removed after
export (regenerable from the adapters), as for pilots.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / 'reports' / 'factory'
# As dev.LLAMA (not imported: it pulls in the evaluation runner, absent from the training venv).
LLAMA = Path(os.environ.get('LILGUY_LLAMA_CPP', Path.home() / 'programs/llama.cpp'))


def lora_delta_keys(keys):
    """Map adapter tensor names to (base weight name, A name, B name) per adapted module."""
    out = {}
    for key in keys:
        if key.endswith('.lora_A.weight'):
            stem = key[:-len('.lora_A.weight')]
            weight = stem.removeprefix('base_model.model.') + '.weight'
            out[weight] = (key, stem + '.lora_B.weight')
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('out', type=Path)
    ap.add_argument('pilots', nargs='+')
    args = ap.parse_args(argv)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    import transformers
    from safetensors import safe_open

    from dev import v2_train

    base = v2_train.BASES['minicpm']
    plans = [json.loads((FACTORY / p / 'plan.json').read_text()) for p in args.pilots]
    if len({(pl['data']['path'], pl['interface'], pl['lr_schedule']) for pl in plans}) != 1:
        raise SystemExit('soup ingredients must share corpus, interface and recipe')
    out = args.out / 'minicpm'
    out.mkdir(parents=True, exist_ok=True)

    model = transformers.LlamaForCausalLM.from_pretrained(base['snapshot'], dtype=torch.float32, local_files_only=True)
    state = model.state_dict()
    deltas, scales = {}, []
    for pilot in args.pilots:
        adapter = FACTORY / pilot / 'minicpm' / 'training' / 'adapter'
        config = json.loads((adapter / 'adapter_config.json').read_text())
        scale = config['lora_alpha'] / config['r']
        scales.append(scale)
        with safe_open(adapter / 'adapter_model.safetensors', 'pt') as f:
            for weight, (a_key, b_key) in lora_delta_keys(f.keys()).items():
                if weight not in state:
                    raise SystemExit(f'adapter module {weight} not in the base model')
                delta = (f.get_tensor(b_key).float() @ f.get_tensor(a_key).float()) * scale
                deltas[weight] = deltas.get(weight, 0) + delta / len(args.pilots)
    with torch.no_grad():
        for weight, delta in deltas.items():
            state[weight].add_(delta.to(state[weight].dtype))
    model.load_state_dict(state)
    merged = out / 'merged'
    model.to(torch.bfloat16).save_pretrained(merged)
    transformers.AutoTokenizer.from_pretrained(base['snapshot'], local_files_only=True).save_pretrained(merged)

    gguf = out / 'tuned-q8_0.gguf'
    env = {**os.environ, 'PYTHONPATH': str(LLAMA / 'gguf-py')}
    subprocess.run([sys.executable, LLAMA / 'convert_hf_to_gguf.py', merged, *base['convert_args'],
                    '--outtype', 'q8_0', '--outfile', gguf], check=True, env=env,
                   stdout=(out / 'export.log').open('w'), stderr=subprocess.STDOUT)
    shutil.rmtree(merged)
    plan = {'job': 'soup', 'base': 'minicpm', 'ingredients': args.pilots, 'modules': len(deltas),
            'scales': scales, 'data': plans[0]['data'], 'interface': plans[0]['interface'],
            'lr_schedule': plans[0]['lr_schedule'], 'tuned_q8_0_sha256': sha256(gguf),
            'method': 'base + mean over ingredients of B@A*alpha/r, fp32, saved bf16, Q8_0'}
    (args.out / 'plan.json').write_text(json.dumps(plan, indent=1) + '\n')
    print(json.dumps({k: plan[k] for k in ('ingredients', 'modules', 'tuned_q8_0_sha256')}))


if __name__ == '__main__':
    main()
