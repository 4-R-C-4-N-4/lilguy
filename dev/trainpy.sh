#!/usr/bin/env bash
# Run a dev module under the training interpreter (torch/transformers/peft) with the project
# venv's packages appended to sys.path, pinned to the RTX 3090 in PCI order.
#   dev/trainpy.sh dev.v2_train minicpm BASE DATA OUT
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
trainer=${LILGUY_TRAIN_PYTHON:-$HOME/Work/chrysopoeia/.venv/bin/python}
site=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0} HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
exec "$trainer" -c 'import runpy, sys; sys.path.append(sys.argv.pop(1)); module = sys.argv.pop(1); runpy.run_module(module, run_name="__main__", alter_sys=True)' "$site" "$@"
