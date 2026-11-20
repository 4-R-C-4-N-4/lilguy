# Decision-learning diagnosis (2026-11-19)

Development evidence only. The held-out suite was neither inspected nor run. Artifacts are local
under `reports/diagnosis/decision-sprint/` (gitignored).

## Question

Why do the v2 adapters still clarify poorly and stop dishonestly? The pilot showed:

- MiniCPM5-2B passed 26 / 39 / 34 of 80 development tasks (stock / round 1 / round 2).
- Qwen3.5-0.8B passed 2 / 30 / 27.
- Only 287 of 5,266 revision-2 target rows (5.45%) are `ask`.

Three explanations were tested: poor fit, a label or context shortcut, and a runtime mismatch.

## Instruments

- `dev/decision_metrics.py` gives per-class counts for `ask`, `done`, `run` and each typed tool,
  with:
  - whole decision-span accuracy;
  - mean summed log-probability and mean probability;
  - teacher-forced and generated confusion.
- `dev/decision_diagnose.py` runs teacher forcing and bounded greedy generation (96 tokens,
  unconstrained HF) on verified training rows. It covers the stock base and both adapters in one
  pinned runtime: BF16 on the RTX 3090, the same template kwargs, and adapter hashes recorded. It
  also marks whether each row was in that adapter's own training set.
- `dev/runtime_parity.py` sends the same verified prompts through the evaluator's exact path:
  - llama-server with the matched Q8_0 GGUF;
  - the v1 grammar, greedy decoding, seed 42 and 256 tokens.

## Results

### Per-class fit on 512 stratified training rows (64 per class)

Each cell is teacher-forced decision-span accuracy / greedy-generation accuracy (generation on 12
rows per class).

| Base | Model | ask | done | run | fs.list | fs.find | fs.read | fs.grep | fs.edit |
|---|---|---|---|---|---|---|---|---|---|
| minicpm | stock | 0% / 0% | 77% / 67% | 58% / 58% | 0% / 0% | 11% / 0% | 16% / 17% | 0% / 0% | 75% / 67% |
| minicpm | r1 | 86% / 92% | 100% / 100% | 86% / 75% | 31% / 17% | 58% / 50% | 88% / 92% | 75% / 83% | 81% / 83% |
| minicpm | r2 | 45% / 42% | 97% / 100% | 95% / 92% | 94% / 100% | 98% / 100% | 91% / 83% | 83% / 75% | 100% / 100% |
| qwen08 | stock | 0% / 0% | 2% / 8% | 19% / 17% | 2% / 0% | 0% / 0% | 38% / 33% | 0% / 0% | 97% / 100% |
| qwen08 | r1 | 97% / 100% | 81% / 75% | 86% / 75% | 100% / 100% | 39% / 33% | 88% / 83% | 2% / 8% | 98% / 100% |
| qwen08 | r2 | 97% / 100% | 100% / 100% | 89% / 75% | 84% / 92% | 100% / 100% | 83% / 100% | 100% / 100% | 73% / 67% |

Every row was in the round-2 adapters' training data. For round 1, 141 of the 512 rows were
outside its revision-1 data.

### All 477 ask/act decision points

These are the rows where an ask/act episode first commits after only looking.

| Base | Model | ask correct (237) | act correct (240) |
|---|---|---:|---:|
| minicpm | stock | 0 | 86 |
| minicpm | r1 | 215 | 236 |
| minicpm | r2 | 116 | 240 |
| qwen08 | stock | 0 | 73 |
| qwen08 | r1 | 217 | 224 |
| qwen08 | r2 | 217 | 219 |

### Runtime parity on the same 477 prompts

The deployed path reproduces the training-runtime decisions:

- MiniCPM R2 Q8_0 asks correctly on 108 of 237 ask rows; HF teacher forcing gets 116. It agrees
  with HF generation on 13 of 16 sampled ask rows.
- Qwen R2 Q8_0 gets 217 of 237, identical to HF, and agrees with HF generation on all 16
  sampled ask rows.
- Both are 100% correct on the `done`, `run` and `fs.edit` decision points, except Qwen `run`
  at 113/135.

## Findings

1. **No runtime mismatch.** The grammar-constrained Q8_0 llama-server path makes the same
   training-row decisions as the HF runtime.
2. **Poor fit is real only for MiniCPM round 2, and it is a regression.**
   - R2 asks correctly on 116 of 237 decision points; R1 got 215, despite never training on the
     revision-2 ask families.
   - Every revision-2 family except `ask_collision` went 0 or nearly 0 for R2: `ask_after_read`
     0/25, `ask_order` 0/22, `ask_conflict` 2/30. On each, R2 acts instead of asking.
   - Training-only evidence suggests the second epoch hurt rather than helped: fit decision
     accuracy fell from 89.1% to 88.4%, and weighted fit loss rose from 0.095 to 0.110.
   - Qwen fits `ask` at 97% in both rounds.
3. **One label defect.** In the revision-2 `ask_collision` ask episodes, the target asks after
   listing and reading only the existing destination file. It never compares that file with the
   source, yet it claims "different content". The same sequence ends in an "identical" report in
   the same family. Every tuned model fails all 20 of these rows. The 200-episode agent audit
   marked every item correct and missed this; I found it from the 0/20 diagnostic.
4. **The dominant development failure is a context shortcut, not fit.**
   - Qwen R2 fits training asks at 91–97% but clarified 1/9 development tasks.
   - Development traces show both bases entering states the corpus never contains:
     - probing the output path the request names (for example `count.txt` or
       `print-welcome.txt`) before it exists;
     - deriving find globs from request words;
     - then following the only not-found continuation in training. All 150 such rows go to
       `fs.find` or `fs.list`, and recover_absent ends with "X does not exist… should I…?".
   - Of 1,799 revision-2 requests, 528 name a not-yet-existing output, but no trajectory ever
     probes it.
   - MiniCPM R2 asked three questions about invented missing paths. Qwen R2 ended eight of nine
     clarification tasks with `ask`, but only one (the recording-order question) passed the
     grader; two of those asks came without any inspection.

## Intervention chosen

The single treatment variable is training-data coverage of the observed off-distribution state.

- **Control:** revision 3 = revision 2 plus the `ask_collision` correction, which now runs `cmp`
  before claiming a difference.
- **Treatment:** revision 4 = revision 3 plus 120 `orient_output` episodes:
  - the request names an output that does not exist yet;
  - the agent lists the inputs, then acts on the only candidate or asks which of two candidates
    to use;
  - half of these episodes start with a masked slip that probes the output path, so the recovery
    state is trained without teaching the probe or an "X does not exist" question.
  - Asks and acts are balanced, and every episode is replay-verified.

Class-balanced sampling was rejected as the main lever. Qwen and MiniCPM R1 already fit ask at
91%+ and still clarified poorly on the development tasks. Its only measured benefit would be the
MiniCPM R2 regression, which the training-fit evidence attributes to its second epoch.

Recipe held equal across arms: final-action loss, decision weight 5, rank 16, learning rate 2e-4,
seed 42, and the same batching. Training exposure is declared before the run:

- at most one epoch, justified by the training-fit evidence in finding 2;
- time boxes of 35 minutes for MiniCPM and 30 for Qwen.

Development scores were not used to choose exposure.
