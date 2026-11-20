# Status

Updated 2026-11-20. This is the one place for current state; the plan and its gates are in [plan/ROADMAP.md](plan/ROADMAP.md). Run evidence lives under `reports/` (gitignored, local).

## Summary

| Step | State | Evidence |
|---|---|---|
| 1. Interface | v2 current (bare `done`, `ask` only when blocked); v1 kept reproducible | `0091f2e`; `lilguy/protocol.py`, golden prompts `tests/unit/interface_v{1,2}_system_prompt.txt` |
| 2. Guarded tool server | Scope fixed; full safety acceptance blocked by missing rsync | `reports/factory/check-4hy_n9nc/result.json`; the gate requires all 18 cases |
| 3. Shared loop and recorder | Done | `292a28b`; `lilguy/loop.py`, `lilguy/do.py`, `tests/sandbox/test_loop_live.py` |
| 4. Protected evaluation | Re-frozen for v2 (pin `e10789bc…`), oracle 100/100, null 0/100; development suite at 80 of 150 | [Roadmap re-freeze note](plan/ROADMAP.md); no model has run on held-out |
| 5. Baselines and family choice | MiniCPM5-2B is the main experimental base, Qwen3.5-0.8B the same-corpus control; no shipping selection | `reports/factory/pilot-w74u7u0b/comparison.json` |
| 6. Verified training data | R3 control: 1,799 episodes / 5,286 rows; R4 treatment: 1,919 / 5,586; replay/split gates passed, human audit open | [Controlled data/result](data/DECISION-CONTROLLED-RESULT.md), [earlier data card](data/CORPUS-V2.md) |
| 7. Train, iterate on development failures | v2 adapters: MiniCPM 43/80, Qwen 36/80 on the v2 roster; missing answers and unsafe input edits remain; no promotion | [v2 result](data/INTERFACE-V2-RESULT.md), [decision sprint](data/DECISION-CONTROLLED-RESULT.md) |
| 8. Ship: quantize, held-out once, latency, model card | Not started | |

Step numbers follow the roadmap. The recurring work list numbers them 1–5: tool server = 2, shared loop = 3, evaluation = 4, base choice = 5–6, one-job iteration = 7–8.

## Decisions needed

1. **Latency reference.** Qwen3.8-27B Q4_K_XL had the highest Fast12 score in this batch (9/12); its IQ2_XXS counterpart was ~20% faster in model time and lost one task (`create_new_file`). Treat that pair as a quantization comparison, not an automatic change to the 30B+ reference requirement. Pick the reference and latency metric before shipping evaluation. No small model was under 10% of either Qwen3.8 quant's median episode time.
2. **Shipping family.** MiniCPM5-2B and Qwen3.5-0.8B now both have v2 LoRAs. MiniCPM leads absolute stock capability, but neither has satisfied the promotion gates. Keep both experimental; do not treat the highest development total as a shipping selection.

## Answer/read-only data and cosine sprint (running)

Shared revision 6: 2,164 real-sandbox-replayed episodes / 6,264 rows, split gate passed;
100-episode agent audit marked correct (not human approval). The scheduler change is committed
as `dbc8264`, not parked in a stash. Both bases are running in one constant-versus-cosine factory
job, one epoch and 50-minute training boxes declared before launch; no further recipes allowed.
The constant arm completed: MiniCPM 20/80 versus revision-5 43/80, Qwen 28/80 versus 36/80.
MiniCPM bare-done question omissions worsen 4→19; Qwen improves 6→0 but has answered failures.
Cosine and semantic review are pending; no candidate selected. Development scores are optimistic
because the development failures shaped these families. No held-out model runs.

[Data yield, audit, settings and interim findings](data/ANSWER-COSINE-RESULT.md).
Evidence: `reports/factory/pilot-zm8ou4p3/`, log `reports/factory/cosine-arms.log`.

## Interface v2 (revision-5 baseline)

Ivy's decision (2026-11-20): the small model does simple, explicit work, not reasoning. Review
happens at the commit stage. `lilguy do | diff | approve | commit` show the executed plan, every
command from the trusted audit log, and the changed lines of each text file. The model's `done`
text is an unverified note. In v2, `done` needs no summary and `ask` is only for a missing input.

On the v2 development roster (12 Fast12 + 68 broad, nine former ambiguity tasks now explicit):

| Base | Stock v2 | v2 adapter | v1 reference (last sprint's best, own interface) |
|---|---:|---:|---:|
| MiniCPM5-2B | 19/80 | 43/80 | 43/80 |
| Qwen3.5-0.8B | 5/80 | 36/80 | 32/80 |

- Matched Q8_0 stock/tuned pairs, same evaluation, RTX 3090; 480/480 originals preserved.
- No change summaries to contradict. New failures:
  - missing answers on question tasks (MiniCPM 4, Qwen 6);
  - staged edits of inputs in read-only tasks (MiniCPM 1, Qwen 4; reference 0 and 1).
- The guard contained all of them, and the review shows them. No promotion.
- These totals are not comparable with the v1-roster numbers below.
- [Full result](data/INTERFACE-V2-RESULT.md).

## Decision-learning sprint: controlled experiment (v1, historical)

The output-orientation intervention improves clarification but does not meet the promotion targets:

| Base | Stock | Control | Treatment | Correct clarification: control → treatment |
|---|---:|---:|---:|---|
| MiniCPM5-2B | 26/80 | 35/80 | 42/80 | 0/9 → 5/9 |
| Qwen3.5-0.8B | 2/80 | 28/80 | 31/80 | 1/9 → 4/9 |

Both run the fixed 12+68 task roster with matched Q8_0 artifacts/device/evaluation fingerprints.
Neither meets the 48/80 or 36/80 target, nor the 6/9 clarification target. Treatment regresses on
MiniCPM editing/organising and Qwen inspection/organising. Qwen makes new unsafe ambiguity choices
(including writing an order where its control correctly asked). Guard containment is not model safety.
No shipping candidate is selected. The recipe limit is reached: no further training in this sprint.

Diagnosis measured per-class teacher-forced/generation fit on verified rows, found a shared
collision-label grounding defect and missing output-orientation contexts. Revision 3 corrects the
label in both arms; revision 4 adds 120 episodes. Both corpora pass replay and split gates. The
200-example revision-2 audit is an agent audit, not human approval, and missed the later defect.
HF/Q8_0 MiniCPM decisions are not identical (108 vs 116/237 correct ask rows; 13/16 sampled
generation agreement), but the runtime difference does not explain away the measured ask underfit.

Evidence: `reports/factory/pilot-_jk0eppk/arms.json`, `arms-report.md`, and
`reports/diagnosis/decision-sprint/`. [Full result](data/DECISION-CONTROLLED-RESULT.md)
records fit, exposure, regressions and remaining gates. Independent semantic review covers 119
failed-done traces, 36 clarification traces and 19 policy events. It finds confirmed false claims
of 27→11 for MiniCPM and 19→20 for Qwen within those changing failed-done cohorts, not full-suite
semantic error rates. New unsafe effects occur in both treatments (including MiniCPM truncating
`schedule.ini`). All original fixtures are preserved; there are no post-policy-stop tool retries.
The parent verified all eight artifact hashes and reproduced both comparisons; the independent
artifact worker was rate-limited. Current verification: 762 unit tests, 87 real sandbox corpus-variant tests, lint clean,
frozen protocol/golden prompt unchanged. The earlier pilot results below are historical context.

Cosine warmup/decay is approved as a separate future experiment, not part of these results. Its
implementation is parked in `stash@{0}`; none of these four runs used it. Keep dropout and other
factors fixed if that experiment is resumed after this sprint.

## Corpus v2 and two-base LoRA pilot (earlier sprint)

The deployed task remains everyday shell/file work through frozen interface v1: `run` plus
`fs.list`, `fs.find`, `fs.read`, `fs.grep`, `fs.edit`. The guarded harness and recorder are separate
from the model learning which action to choose. Training now covers ten roadmap categories,
including clarification, recovery and approval stops, rather than the old 28-episode tracer slice.
The fixtures are still synthetic, short and template-generated; this is not daily-driver evidence.

Current development accounting is **80 total tasks: 12 Fast12 + 68 broad**, not 80 broad plus
Fast12. The sprint wording called for 80 broad tasks; that coverage target was not met, and these
runs must not be reported as a 92-task evaluation. Older tables below use earlier rosters and
quantizations and must not be compared directly.
Both new stock/tuned pairs are matched Q8_0 exports, on the RTX 3090, with matching per-suite
evaluation fingerprints. Development failures shaped revision 2, so these scores are tuning
evidence, not an unbiased estimate of generalization.

| Base | Stock Fast12 / broad | R1 tuned Fast12 / broad | R2 tuned Fast12 / broad |
|---|---|---|---|
| MiniCPM5-2B | 6/12 + 20/68 = 26/80 | 10/12 + 29/68 = 39/80 | 9/12 + 25/68 = 34/80 |
| Qwen3.5-0.8B | 0/12 + 2/68 = 2/80 | 9/12 + 21/68 = 30/80 | 9/12 + 18/68 = 27/80 |

Round 1: `reports/factory/pilot-w74u7u0b/`; round 2: `reports/factory/pilot-kqfyui0g/`.
The per-category Wilson 95% intervals, task gains/regressions, safety counters and median
model/episode times are in each job's `comparison.json` and `report.md`, and the committed
[pilot report](data/LORA-V2-PILOT.md). Both rounds are complete. All compared runs preserved
originals and had zero infrastructure failures; stock-score reuse was fingerprint-checked.
Neither model improved in round 2 relative to its first-round result.

No candidate has earned a held-out run. MiniCPM R2 gets 0/9 required clarifications right and
increases policy-stop observations from 3 to 7. A trace inspection confirms a false answer after
a failed `cmp`: it says two files are identical even though `cmp` reports EOF on the shorter file.
The guarded runs preserve originals, but containment is not correct model behavior.
Qwen R2 gets 1/9 required clarifications right (R1: 4/9), still has no script-category passes,
and increases failed-task `done` endings from stock's 8 to 30. It also fails promotion.
Inspection of all nine MiniCPM R2 clarification traces found three `ask` terminals, but they ask about
invented missing paths rather than the fixture's actual ambiguity; the remaining six act or
exhaust their budgets. The 0/9 score is not simply a refusal to accept otherwise correct questions.

Metric caveat: the legacy `false_done` counter means **failed tasks ending in `done`**, not a
count of proven false-success claims. Policy stops also include expected approval stops.
Do not infer semantic safety from either aggregate alone.

Training uses final-action-only loss, decision-token weight 5, rank 16 all-linear LoRA, pinned
bases/templates/end tokens, length-bucketed batches and training-fit stopping bounded by time.
MiniCPM R2 ran two epochs at 2,474 training tokens/s, with 11,262 MiB peak allocated GPU memory.
Its teacher-forced decision accuracy was 89.1% after epoch 1 and 88.4% after epoch 2 on 800 training
rows: it did not reach the 99% fit threshold. More epochs and the larger corpus did not produce a
monotonic development gain. `ask` is only 287/5,266 target rows (5.45%) in revision 2; the larger
ask/selection episode count does not mean balanced decisions. Per-action-class fit diagnostics
are now complete in the decision-learning sprint; imbalance alone is not a proven root cause.
Qwen R2 completed one epoch at 2,463 training tokens/s, 9,074 MiB peak allocated GPU memory,
and 90.4% teacher-forced decision accuracy; it also stopped on the time budget, not the fit target.

The revision-1 200-example audit is an **agent audit for Ivy to confirm**: the subagent said
200/200; the author's review downgraded four debatable asks to 196/200 (98%). Those two family
ambiguities were corrected in revision 2. Its subsequent 200-example agent audit initially found
no defects, but missed the collision-label grounding defect later corrected in revision 3.

### Host-memory incident

Kernel logs confirm cgroup OOM kills at 18:13 (Baloo extractor started by the cleanup worker),
18:27 (training smoke Python), and 18:53 (first pilot Python). The first pilot's saved adapter
was recovered by reloading and merging, not retraining; unavailable training counters are null
in its report rather than reconstructed. The failed Akonadi/crash-collector services date to
November 15 and the Claimbase evaluation failures to November 17, not this incident.

The resumed pilot and round 2 run in dedicated user scopes with `MemoryMax=20G` and
`MemorySwapMax=1G`; these live limits were verified. No unrelated service was restarted.
An Ollama process appeared on the 3090 during Qwen R2 training; latency measurements from this
session are development observations, not uncontended release benchmarks.

Superseded round-1 merged checkpoints and GGUFs were removed after their reports were written
(12.62 GiB apparent size); adapters, model hashes and scored traces remain, with the removal
inventory in `pilot-w74u7u0b/artifact-cleanup.json`. Round-2 artifacts are retained. The filesystem
had 95 GiB available after that cleanup, above the 30 GiB floor.

### Next work

1. v2 data fixes: every question episode ends with its answer (rebalance against the 2:1 bare
   `done`), and add read-only contrast episodes that inspect without writing.
2. In a separate experiment, test the agreed 3% warmup/cosine schedule against a fixed-data
   constant-rate control. Do not change dropout, base or data simultaneously; preserve a fixed
   training-fit probe when comparing fit across recipes.
3. Install rsync and complete the exact 18-case safety gate before calling the tool server accepted.
4. Expand the shared development roster toward 150, including a distinct archive category, and
   rerun matched stock/tuned comparisons after its fingerprint changes.
5. Choose the shipping reference/latency metric; run held-out only when the promotion gates pass.

### Verification

- `pytest -q tests/unit`: 693 passed.
- `pytest -q tests/sandbox/test_v2_corpus_live.py`: 59 passed through real gold runs and replay.
- `ruff check dev tests/unit tests/sandbox/test_v2_corpus_live.py`: passed.
- Both corpus row verifiers and the frozen split gate passed again after the generator changes.
- `lilguy/protocol.py` and the golden v1 prompt are unchanged from the interface-freeze commit.
- rsync is still absent: full 18-case safety acceptance remains blocked, not passed by omission.

## 0.8B LoRA pilots: not promoted

`bash dev/pilot_v1.sh` ran end to end in `reports/factory/pilot-v1-TqsV2q/`. It replayed 20 training-only episodes in separate guarded fixtures (76 next-action examples) before training. The provenance records credit pinned tldr-pages patterns and mark original clarification fixtures separately. The split check covered the pilot rows, all 32 development tasks and the frozen 100-task holdout.

Both stock and LoRA GGUFs used the same llama.cpp converter with `--no-mtp --outtype q8_0`. Fast12 stayed at 0/12. Broader dev fell from 1/20 to 0/20 (`merge_pages_in_named_order` regressed), with no gains. All 64 model episodes preserved original fixture files and had no infrastructure errors. The pilot was mainly additive file transforms, not production coverage of recovery or approval handling. No held-out model inference ran.

The follow-up `bash dev/pilot_v1.sh recovery` (`reports/factory/pilot-v1-H4n5xk/`) added four failed-read recovery episodes and four factual read-only episodes. All 28 training episodes replayed with matching observations and effects and yielded 100 next-action rows. The job used the same training hyperparameters and matched GGUF export. Relative to stock, Fast12 rose from 0/12 to 1/12 and the broader suite from 1/20 to 5/20. Across both suites it gained six tasks and regressed on `merge_pages_in_named_order`. The tuned model still made one Fast12 `done` claim immediately after an error and asked for clarification on neither suite. No original files changed in the 64 evaluation episodes. The holdout was not run. The larger corpus also increased the number of optimizer steps; this comparison does not isolate data mix from training exposure.

`bash dev/pilot_v1.sh handoff` (`reports/factory/pilot-v1-k0k3fQ/`) replaced eight episodes while keeping 28 episodes, 100 action rows, and the same optimizer settings as `recovery`. It included three ambiguous/explicit request pairs and two real approval stops. Both stops had to reproduce the sandbox's final `pending` observation and the exact staged change on fresh fixtures without applying it. Against stock, the handoff adapter gained `read_only_question` (Fast12 0/12 → 1/12) and `count_lines_total` and `find_todo_comments` (broad 1/32 → 2/32), but lost `merge_pages_in_named_order`. It passed four fewer tasks than the recovery adapter on the same 32-task broad suite, asked no questions, and failed the Fast12 approval-stop task. All 88 stock/tuned evaluation episodes preserved their originals with no infrastructure failures. The holdout was not run.

## Stock small vs. 35B-class reference (RTX 3090, 44 broader tasks)

The `factory screen` job evaluated the same two artifacts on both development suites in one run. MiniCPM5-2B scored 19/56 (6/12 Fast12 and 13/44 broad); Qwen3.6-35B-A3B scored 36/56 (7/12 and 29/44). All 112 original fixtures were preserved, with no infrastructure failures. MiniCPM got none of the seven clarification tasks right, and Qwen got two right. MiniCPM took 64% of Qwen's median Fast12 episode time and 86% of its median broad episode time. These are not release latency results. The verified comparison and named task differences are in `reports/factory/screen-z35__7ab/comparison.json`.

On the same 44-task `broad` roster, stock MiniCPM5-2B Q4_K_M passed 13/44 (1/12 new) and stock Qwen3.6-35B-A3B IQ4_XS passed 29/44 (7/12 new). MiniCPM got no clarification right; Qwen got two right. All 88 episodes preserved the originals, with no infrastructure failures. Median end-to-end episode times were 1.182 s and 1.579 s, respectively. Those medians include misses and are development measurements, not release latency evidence or a choice of reference. See `reports/factory/broad-verify-ORkpeV/comparison.json` for task-level differences and the shared evaluation fingerprint.

## Previous expanded development comparison (RTX 3090, 32 broader tasks)

The 12 new tasks add clarification decisions, structured text processing, and factual read-only checks. All their scripted solutions passed and immediate false completions failed on fresh guarded fixtures. Against the expanded 32-task `broad` suite, stock MiniCPM5-2B passed 12/32 (2/12 new) and the recovery-tuned Qwen3.5-0.8B passed 6/32 (1/12 new). Neither got any of the three new clarification tasks right. Both runs used the same evaluation fingerprint; all 64 model episodes preserved the original fixtures, with no infrastructure failures. See `reports/factory/broad-expansion-g2fyR7/comparison.json`. These are development results on different size and quantization tiers, not a release comparison.

## Original small-family stock screen (RTX 3090, 32 development tasks)

| Model | Fast12 | Broader dev | Combined |
|---|---:|---:|---:|
| MiniCPM5-2B Q4_K_M | 6/12 | 10/20 | 16/32 |
| Qwen3.5-2B Q4_K_M | 2/12 | 3/20 | 5/32 |
| Qwen2.5-Coder-1.5B-Instruct Q4_K_M | 0/12 | 3/20 | 3/32 |
| Qwen3.5-0.8B Q8_0 | 0/12 | 1/20 | 1/32 |
| SmolLM2-1.7B-Instruct Q4_K_M | 0/12 | 0/20 | 0/32 |

Details: `reports/factory/family-screen-yKd2kp/` contains the model revisions and checksums, both run manifests, per-task results via their run directories, and the report. Both development suites ran on the same GPU, each with its own matching evaluation fingerprint. All 160 model episodes in the five-row screen completed without infrastructure failures or changes to original fixtures. Model misses, including early exits, remain in the latency sample.

## Baselines (Fast12, stock models, RTX 3090, same harness)

| Model | Pass | 95% CI | Median model s/task | Median episode s/task |
|---|---|---|---|---|---|
| Qwen3.5-0.8B Q8_0 | 0/12 | 0–24% | 0.33 | 1.300 |
| MiniCPM5-2B Q4_K_M | 6/12 | 25–75% | 0.28 | 0.995 |
| Qwen3-4B-Instruct-2507 Q4_K_M | 4/12 | 14–61% | 0.67 | 1.370 |
| Qwen3.6-35B-A3B IQ4_XS | 8/12 | 39–86% | 1.06 | 1.677 |
| Nanbeige4.3-33B Q4_K_M | 3/12 | 9–53% | 9.71 | 10.873 |
| Qwen3.8-27B UD-Q4_K_XL | 9/12 | 47–91% | 2.45 | 3.143 |
| Qwen3.8-27B UD-IQ2_XXS | 8/12 | 39–86% | 1.96 | 2.611 |

Full table with terminals, policy stops and per-task passes: `reports/factory/baselines-seven-12ae514e319b/report.md`. All runs used the same evaluation fingerprint, had zero infrastructure failures, and preserved the original files in all 84 model episodes. Quantization differs between candidates. These are development timings across passes and misses, not release latency evidence.

**Reference model failures.** Qwen3.6-35B-A3B claimed "Deleted report.csv" when the delete was only pending approval. It also edited both files of an ambiguous pair instead of asking. These are failures the small model must avoid.

## Gaps and known limits

- **Safety corpus #17** is unverified: rsync is absent from the sandbox's executable path. `factory check` now stops at `safety-prerequisites` rather than deselecting the case. The historical 17-case report does not satisfy the full gate.
- **The development suite** has 80 sandbox-calibrated tasks: Fast12 plus six batches registered in `dev/broad_runner.py`. The new text-workflow batch covers script syntax, literal quoting, byte-level comparison, and packaging manifests. Its scripted controls passed and immediate false completions failed on separate guarded fixtures. Fast12 itself is unchanged. The target is 150.
- **The held-out suite** has 100 tasks from 10 template families. It was re-frozen once on 2026-11-19, before any model ran on it, to fix three grader defects found on development evidence (see roadmap). It has been checked by unit tests only; its first live run is the shipping evaluation.
- **No release evaluation has run.** Corpus v2 training and matched deployed-artifact development evaluation have run, but no adapter has qualified for promotion. Earlier adapters under `reports/archive/pilots/` predate interface v1.

## Fixes made while running baselines

These changed scores. Every baseline above was run after all of them.

- `fast12_runner.collect_changes` counted model-made directories and mode changes as infrastructure failures. They are now scored as wrong changes.
- Three Fast12 graders rejected correct answers: a literal `retry=2`, a required word "protect", and a recovery task that demanded a mistake. The held-out suite had the same three defects; both are fixed.
- Model jobs ran on the desktop RTX 4070 because of CUDA device order. They now verify the GPU.
