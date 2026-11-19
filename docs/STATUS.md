# Status

Updated 2026-11-19. This is the one place for current state; the plan and its gates are in [plan/ROADMAP.md](plan/ROADMAP.md). Run evidence lives under `reports/` (gitignored, local).

## Summary

| Step | State | Evidence |
|---|---|---|
| 1. Interface v1 frozen | Done | `5392523`; `lilguy/protocol.py`, golden prompt `tests/unit/interface_v1_system_prompt.txt` |
| 2. Guarded tool server | Scope fixed; full safety acceptance blocked by missing rsync | `reports/factory/check-4hy_n9nc/result.json`; the gate requires all 18 cases |
| 3. Shared loop and recorder | Done | `292a28b`; `lilguy/loop.py`, `lilguy/do.py`, `tests/sandbox/test_loop_live.py` |
| 4. Protected evaluation | Split gate passes; development suite at 80 of 150 | Held-out pin `f9d408a4…`; the model runner and training gate share the development roster |
| 5. Baselines and family choice | One-command development screen verified; shipping base and reference not selected | `reports/factory/screen-z35__7ab/comparison.json` |
| 6. Verified training data | Recovery and handoff profiles each have 28 replay-verified episodes; neither is a production corpus | [Licence audit](data/LICENCE-AUDIT.md); pilot `data/effects.json` |
| 7. Train, iterate on development failures | Three 0.8B pilots ran; none promoted | `reports/factory/pilot-v1-k0k3fQ/comparison.json` |
| 8. Ship: quantize, held-out once, latency, model card | Not started | |

Step numbers follow the roadmap. The recurring work list numbers them 1–5: tool server = 2, shared loop = 3, evaluation = 4, base choice = 5–6, one-job iteration = 7–8.

## Decisions needed

1. **Latency reference.** Qwen3.8-27B Q4_K_XL had the highest Fast12 score in this batch (9/12); its IQ2_XXS counterpart was ~20% faster in model time and lost one task (`create_new_file`). Treat that pair as a quantization comparison, not an automatic change to the 30B+ reference requirement. Pick the reference and latency metric before shipping evaluation. No small model was under 10% of either Qwen3.8 quant's median episode time.
2. **Model family to fine-tune.** MiniCPM5-2B led the stock screen, but did not ask for clarification on Fast12. The first 0.8B pilot did not close the gap. MiniCPM is the next challenger, not the selected shipping family.

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
- **No production training or release evaluation has run.** Earlier adapters under `reports/archive/pilots/` predate interface v1. The first v1 pilot above is feasibility evidence only.

## Fixes made while running baselines

These changed scores. Every baseline above was run after all of them.

- `fast12_runner.collect_changes` counted model-made directories and mode changes as infrastructure failures. They are now scored as wrong changes.
- Three Fast12 graders rejected correct answers: a literal `retry=2`, a required word "protect", and a recovery task that demanded a mistake. The held-out suite had the same three defects; both are fixed.
- Model jobs ran on the desktop RTX 4070 because of CUDA device order. They now verify the GPU.
