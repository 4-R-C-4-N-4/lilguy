#!/usr/bin/env bash
# Run the training-pilot tests with the training interpreter (torch/transformers/PEFT).
# pytest comes from the project venv, appended to the END of sys.path so it cannot shadow
# the training environment's packages. Offline: the Hub is disabled.
set -euo pipefail
cd "$(dirname "$0")/.."
TRAIN_PYTHON=${LILGUY_TRAIN_PYTHON:-/home/ivy/Work/chrysopoeia/.venv/bin/python}
site=$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 exec "$TRAIN_PYTHON" -c '
import sys
sys.path.append(sys.argv[1])
import pytest
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/train", *sys.argv[2:]]))
' "$site" "$@"
