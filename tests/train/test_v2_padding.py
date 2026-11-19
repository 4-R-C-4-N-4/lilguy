"""Left-padded batches must score each row exactly as it scores alone (hybrid-attention safety)."""
import os
from pathlib import Path

import pytest

torch = pytest.importorskip('torch')
transformers = pytest.importorskip('transformers')

from dev import v2_corpus, v2_train  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / 'reports/corpus/v2'


@pytest.mark.parametrize('key', ['qwen08', 'minicpm'])
def test_left_padding_matches_unpadded_rows(key):
    base = v2_train.BASES[key]
    if not torch.cuda.is_available() or not (base['snapshot'] / 'config.json').is_file() or not DATA.is_dir():
        pytest.skip('needs the GPU, the pinned snapshot and a built corpus v2')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    tokenizer = transformers.AutoTokenizer.from_pretrained(base['snapshot'], local_files_only=True)
    end_id = tokenizer.convert_tokens_to_ids(base['end_token'])
    rows = v2_corpus.verified_rows(DATA)
    picks = [min(rows, key=len), max(rows, key=len), rows[len(rows) // 2]]
    encoded = [v2_train.encode(tokenizer, m, base, end_id, 5.0, 4096) for m in picks]
    model = getattr(transformers, base['model_class']).from_pretrained(
        base['snapshot'], local_files_only=True, dtype=torch.float32).to('cuda').eval()
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else end_id
    with torch.no_grad():
        alone = []
        for row in encoded:
            _, losses = v2_train.forward_targets(model, v2_train.collate([row], pad, torch, 'cuda'), torch)
            alone.append(losses[0][-len(row['target']):])
        _, batched = v2_train.forward_targets(model, v2_train.collate(encoded, pad, torch, 'cuda'), torch)
    for i, row in enumerate(encoded):
        torch.testing.assert_close(batched[i][-len(row['target']):], alone[i], rtol=1e-3, atol=2e-3)
