#!/usr/bin/env bash
# Stock baselines through the same Fast12 loop, one model at a time on the 3090.
# Usage: dev/baselines.sh OUT.tsv  (appends: label, report dir, exit code)
set -u
out=${1:?output tsv}
cd "$(dirname "$0")/.."
while read -r label gguf; do
    [ -z "$label" ] && continue
    case "$label" in \#*) continue ;; esac
    log=$(mktemp)
    CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 timeout 3600 .venv/bin/python -m dev.factory fast12 --gguf "$gguf" > "$log" 2>&1
    rc=$?
    dir=$(head -1 "$log")
    rm -f "$log"
    printf '%s\t%s\t%s\n' "$label" "$dir" "$rc" >> "$out"
done <<EOF
qwen3.5-0.8b-q8_0 ${TMPDIR:-/tmp}/qwen35-0.8b-base-q8_0.gguf
minicpm5-2b-q4_k_m $HOME/programs/openbmb/MiniCPM5-2B/MiniCPM5-2B-Q4_K_M.gguf
qwen3-4b-instruct-2507-q4_k_m $HOME/programs/qwen/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
qwen3.6-35b-a3b-iq4_xs $HOME/programs/qwen/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf
nanbeige4.3-33b-q4_k_m $HOME/programs/nanbeige/Nanbeige_Nanbeige4.3-33B-Q4_K_M.gguf
qwen3.8-27b-ud-q4_k_xl $HOME/programs/qwen/Qwen3.8-27B-UD-Q4_K_XL.gguf
qwen3.8-27b-ud-iq2_xxs $HOME/programs/qwen/Qwen3.8-27B-UD-IQ2_XXS.gguf
EOF
