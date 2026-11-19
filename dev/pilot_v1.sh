#!/usr/bin/env bash
# Offline v1 feasibility job: verify data, train, export a matched Q8_0 pair, score development only.
set -euo pipefail
profile=${1:-original}
if (( $# > 1 )) || [[ "$profile" != original && "$profile" != recovery && "$profile" != handoff ]]; then
    printf '%s\n' 'Usage: bash dev/pilot_v1.sh [original|recovery|handoff]' >&2
    exit 2
fi
cd -- "$(dirname -- "$0")/.."
llama=${LILGUY_LLAMA_CPP:-$HOME/programs/llama.cpp}
trainer=${LILGUY_TRAIN_PYTHON:-$HOME/Work/chrysopoeia/.venv/bin/python}
server="$llama/build/bin/llama-server"
expected_llama=01818e4956858fe225a6875aae88b4cbee0b319e
base="$HOME/.cache/huggingface/hub/models--Qwen--Qwen3.5-0.8B/snapshots/2fc06364715b967f1860aea9cf38778875588b17"
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1
if [[ ! -x "$trainer" || ! -x "$server" || ! -f "$base/config.json" ]] ||
   [[ "$(git -C "$llama" rev-parse HEAD)" != "$expected_llama" ]] ||
   [[ -n "$(git -C "$llama" status --porcelain --untracked-files=no)" ]] ||
   ! printf '%s  %s\n' d07bfc865747c99ab0117049570b84c125a811a65a65f76b9cb8df5b90d4c324 "$server" | sha256sum --check --status; then
    printf '%s\n' 'Pilot requires the pinned local Qwen snapshot, training venv and clean pinned llama.cpp build.' >&2
    exit 1
fi
if (( $(df --output=avail -B1 . | tail -n 1) < 8 * 1024 * 1024 * 1024 )); then
    printf '%s\n' 'Pilot needs at least 8 GiB free on the reports filesystem.' >&2
    exit 1
fi
mkdir -p reports/factory
out=$(mktemp -d "$PWD/reports/factory/pilot-v1-XXXXXX")
printf '%s\n' "$out"
trap 'printf "Pilot failed; see logs in %s\n" "$out" >&2' ERR
site=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
(
    flock -n 9
    .venv/bin/python -m dev.v1_pilot_data "$out/data" --profile "$profile" > "$out/data.log" 2>&1
    "$trainer" -c 'import runpy, sys; sys.path.append(sys.argv.pop(1)); runpy.run_module("dev.v1_pilot_train", run_name="__main__", alter_sys=True)' \
        "$site" "$base" "$out/data" "$out/training" --profile "$profile" > "$out/train.log" 2>&1
) 9>reports/factory/.lock
for side in stock tuned; do
    src="$base"
    if [[ "$side" == tuned ]]; then src="$out/training/merged"; fi
    artifact="$out/$side-q8_0.gguf"
    PYTHONPATH="$llama/gguf-py" "$trainer" "$llama/convert_hf_to_gguf.py" "$src" --no-mtp --outtype q8_0 \
        --outfile "$artifact" > "$out/$side-export.log" 2>&1
    for suite in fast12 broad; do
        log="$out/$side-$suite.log"
        rc=0
        .venv/bin/python -m dev.factory "$suite" --server "$server" --gguf "$artifact" > "$log" 2>&1 || rc=$?
        IFS= read -r folder < "$log"
        # A complete suite may return 1 for model misses; no summary is a job failure.
        test -f "$folder/$suite.json"
        printf '%s\t%s\t%s\t%s\n' "$side" "$suite" "$folder" "$rc" >> "$out/evaluations.tsv"
        if [[ "$suite" == fast12 ]]; then
            if [[ "$side" == stock ]]; then stock="$folder"; else tuned="$folder"; fi
        fi
    done
done
.venv/bin/python -m dev.factory compare --stock "$stock" --candidate "$tuned" | tee "$out/fast12-comparison.json"
.venv/bin/python -m dev.v1_pilot_report "$out/evaluations.tsv" | tee "$out/comparison.json"
