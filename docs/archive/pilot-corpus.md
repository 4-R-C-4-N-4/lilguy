# Synthetic next-action corpus data card

This bootstrap corpus is for later supervised tuning and within-corpus
validation. All tasks and two-file fixtures are authored synthetic data produced
by `dev/small_model_corpus.py`. The generator accepts only a seed and has no data
ingestion path. It uses no external datasets, private material, or development
evaluation fixtures or traces. Tests compare against the existing evaluation
fixtures solely to detect overlap.

## Composition

| Split | Template groups | Cases | `fs.edit` | `ask` | `done` | Rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Train | 12 (kiln, press, loom, hive, mill, buoy, forge, orchard, choir, reef, depot, bakery) | 192 | 96 | 48 | 144 | 288 |
| Validation | 4 (dome, lamp, stable, vault) | 64 | 32 | 16 | 48 | 96 |

Four case kinds per family and target position: `act` (the request names
one file), `ask` (the request names neither and both files contain the
setting), `infer` (the *same* ambiguous wording as `ask`, but only one file
contains the setting and the other has a family-specific decoy setting, so the
workspace determines the target and the answer is an edit), and `stop` (the
named file already has the value). `ask`/`infer` pairs differ only in the
workspace, which teaches "is the target unique here?" rather than "is a
path named?". The oracle derives the kind from how many files contain the
setting and refuses a mismatch.

After an edit, the following `done` row continues the conversation in the
evaluator's protocol: the edit as an assistant turn, then the tool's
observation as `Observation:\n…` (`dev.small_model_eval.observation_message`,
shared). Only the final assistant message is a training target. Corpus v3 and
earlier re-read both files in a fresh single turn instead. A model trained that
way repeated its edit in the evaluator instead of stopping (PROGRESS.md,
pilot 4).

Every case appears twice, with the two files read in each order (`Case.order`).
With a single fixed order, a pilot learned "edit if the request names the file
read last": all of its over-asks named the first file read (see PROGRESS.md,
pilot 3). Both orders break that shortcut, and validation then measures
position bias directly.

Each family (`Family` in `dev/small_model_corpus.py`) declares two candidate
paths, a field and a sibling setting, two explicit phrasings, two ambiguous
phrasings and its own already-satisfied phrasing. For each family, the explicit
and ambiguous variants share two open-file observations. Every family names its
target once by full path and once only by the distinguishing directory word
(for example "the glaze gauge"), so "no path in the request" is not a shortcut
for "ask". The oracle enforces the mention rule: an explicit or stop request
identifies exactly one candidate (full path or declared word) and an ambiguous
request identifies none; anything else fails the build. The ambiguous answer
asks which file to change. Each family places the target in both positions,
with different sibling values. Each edit produces a subsequent stop record
after both files are read back. An already-satisfied request also produces a
stop record with zero edits. The wire action for stop is `done`.

Train and validation share no group, path, directory word, setting name or
sentence template, including the already-satisfied phrasing (tested).

Whole families are assigned before variants are generated. The builder checks
split ownership of groups, unordered path/field families and exact fixtures,
and rejects duplicate candidate inputs and duplicate final chat inputs.
Seed 42 is the default. The seed changes values within fixed families. Treat
validation as a small tuning diagnostic. The corpus covers open-file,
single-setting edits and has no discovery, recovery, or multi-file targets.

## Verification and export

The deterministic oracle checks the request against its fixture and intent,
requires the exact action sequence, and computes expected bytes independently
of the literal-edit tool. Each case runs the fixed typed program on a disposable
copy. Every read and edit is checked against expected observations and a full
workspace snapshot of paths, kinds, modes and file bytes. Ask and already
satisfied cases make only read calls. This offline control runs without the
production guard. Malformed labels, unexpected observations, and extra effects
fail the build before an export directory is created.

Each JSONL row contains three chat messages. The system message supplies the
fixed tool schemas and action protocol. The user message contains the request
and observed file text. The only assistant message is the verified next action.
Expected effects, template IDs, split metadata and verification results stay
outside the chat. The separate manifest contains the seed, split counts, group
names and replay coverage. Use the two split files separately during tuning.

From the repository root, run the offline acceptance commands.

```bash
.venv/bin/python -m pytest -q tests/data/test_small_model_corpus.py tests/eval/test_small_model_eval.py tests/eval/test_paired_calibration.py
run_dir=$(mktemp -d)
.venv/bin/python -m dev.small_model_corpus --seed 42 --out "$run_dir/corpus"
```

## Parent host guarded replay

From the repository root on a parent host with working sandbox capabilities and
user systemd cgroup delegation, run the following.

```bash
run_dir=$(mktemp -d)
.venv/bin/python -m lilguy.probe &&
.venv/bin/python -m dev.small_model_corpus --seed 42 --guarded-replay --out "$run_dir/corpus"
```

This adds eight real MCP stdio sessions, one act, ask, stop and infer case per split.
Each act or infer case makes two reads and one staged edit. Each ask or stop case
makes two reads. The guard runs with tool networking off and the default
resource checks. Replay checks per-step audit effects, the complete session
diff, merged bytes and modes, unchanged originals and absence of pending
approval or network requests. It issues no approval or commit. The corpus
export remains based on all 256 offline-verified cases. A successful replay
records its sample size and groups in the manifest. A replay failure aborts
export. No inference service, weights or training are involved.
