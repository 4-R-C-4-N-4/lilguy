# Status

Updated 2026-11-19. This is the one place for current state; the plan and its gates are in [plan/ROADMAP.md](plan/ROADMAP.md). Run evidence lives under `reports/` (gitignored, local).

## Summary

| Step | State | Evidence |
|---|---|---|
| 1. Interface v1 frozen | Done | `5392523`; `lilguy/protocol.py`, golden prompt `tests/unit/interface_v1_system_prompt.txt` |
| 2. Guarded tool server | Done, one gap | `d860df5`; `factory check` stage `v1-bypass-corpus` |
| 3. Shared loop and recorder | Done | `292a28b`; `lilguy/loop.py`, `lilguy/do.py`, `tests/sandbox/test_loop_live.py` |
| 4. Protected evaluation | Done for now; development suite at 24 of 150 | `bc1d6a0`; held-out pin `f9d408a4…` |
| 5. Baselines and family choice | Baselines run; **waiting on two decisions** | `reports/factory/baselines-2026-11-19/` |
| 6. Verified training data | Not started (licence audit first) | [data/DATA-SOURCES.md](data/DATA-SOURCES.md) |
| 7. Train, iterate on development failures | Not started | `factory compare` is ready |
| 8. Ship: quantize, held-out once, latency, model card | Not started | |

Step numbers follow the roadmap. The recurring work list numbers them 1–5: tool server = 2, shared loop = 3, evaluation = 4, base choice = 5–6, one-job iteration = 7–8.

## Decisions needed

1. **Latency reference.** "Under 10% of a 30B model's latency" depends on which model:
   - against Nanbeige4.3-33B (dense, Q4_K_M), every small candidate is already under 10%;
   - against Qwen3.6-35B-A3B (MoE, about 3B active), none is (best 27%).

   A dense Qwen3.8-27B at 4-bit and 2-bit is being added for comparison.
2. **Model family to fine-tune.** On Fast12, MiniCPM5-2B passes 6/12 and stock Qwen3.5-0.8B passes 0/12. Twelve tasks give wide intervals, so this is a signal, not a verdict.

## Baselines (Fast12, stock models, RTX 3090, same harness)

| Model | Pass | 95% CI | Median model s/task | vs Qwen3.6-35B-A3B | vs Nanbeige-33B |
|---|---|---|---|---|---|
| Qwen3.5-0.8B Q8_0 | 0/12 | 0–24% | 0.33 | 32% | 4.0% |
| MiniCPM5-2B Q4_K_M | 6/12 | 25–75% | 0.28 | 27% | 3.4% |
| Qwen3-4B-Instruct-2507 Q4_K_M | 3/12 | 9–53% | 0.64 | 60% | 7.6% |
| Qwen3.6-35B-A3B IQ4_XS | 7/12 | 32–81% | 1.06 | 100% | 13% |
| Nanbeige4.3-33B Q4_K_M | 3/12 | 9–53% | 8.36 | 792% | 100% |

Full table with terminals, policy stops and per-task passes: `reports/factory/baselines-2026-11-19/report.md`. Quantization differs between candidates.

Two caveats:

- **Missing candidates.** The roadmap also lists Qwen3.5-2B, a ~1.5B coder model and SmolLM2-1.7B. None is on disk.
- **The reference model's failures.** Qwen3.6-35B-A3B claimed "Deleted report.csv" when the delete was only pending approval. It also edited both files of an ambiguous pair instead of asking. Those are exactly the habits the small model must learn.

## Gaps and known limits

- **Bypass corpus #17** (`rsync --delete`) is unverified on this host because rsync is not installed. It is deselected by name in `factory check`.
- **The development suite** has 24 sandbox-calibrated tasks (Fast12 + `dev/broad_dev.py`). The target is 150.
- **The held-out suite** has 100 tasks from 10 template families. It was re-frozen once on 2026-11-19, before any model ran on it, to fix three grader defects found on development evidence (see roadmap). It has been checked by unit tests only; its first live run is the shipping evaluation.
- **No training has run** for the product. Pilot adapters under `reports/archive/pilots/` predate interface v1.

## Fixes made while running baselines

These changed scores. Every baseline above was run after all of them.

- `fast12_runner.collect_changes` counted model-made directories and mode changes as infrastructure failures. They are now scored as wrong changes.
- Three Fast12 graders rejected correct answers: a literal `retry=2`, a required word "protect", and a recovery task that demanded a mistake. The held-out suite had the same three defects; both are fixed.
- Model jobs ran on the desktop RTX 4070 because of CUDA device order. They now verify the GPU.
