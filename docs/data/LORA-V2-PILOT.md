# Corpus v2 LoRA pilot

Recorded 2026-11-19. Development experiments only; no adapter is promoted and no held-out model inference ran.

The model chooses actions for everyday shell/file work through frozen interface v1; the guarded tool server, loop and recorder are separate components. Short synthetic template fixtures do not establish daily-driver readiness.

## Cohort and accounting

- 80 development tasks total: 12 Fast12 and 68 broad, not 92. The sprint target of 80 broad tasks was not reached.
- Pinned MiniCPM5-2B and Qwen3.5-0.8B, each compared with its own stock Q8_0 export using matched converter flags, templates, device and evaluation fingerprints.
- Corpus revision 1: 1,342 episodes / 3,957 rows; revision 2: 1,799 / 5,266. See [the data card](CORPUS-V2.md) and [counts](CORPUS-V2-COUNTS.md).
- Both corpora passed gold execution, fresh-fixture replay, dedup and the frozen split gate. Development failures informed the second corpus, so development scores are not an unbiased generalization estimate.
- The revision-1 200-example agent audit was downgraded from the subagent's 200/200 to 196/200 after reviewing four debatable ask labels. Human confirmation and a new revision-2 sample audit remain open.

## Overall results

| Round | Base | Stock | Tuned | Stock Wilson 95% CI | Tuned Wilson 95% CI | Correct clarifications, stock → tuned (n=9) |
|---|---|---:|---:|---|---|---:|
| Round 1 | minicpm | 26/80 | 39/80 | 23.2–43.4% | 38.1–59.5% | 0 → 1 |
| Round 1 | qwen08 | 2/80 | 30/80 | 0.7–8.7% | 27.7–48.5% | 0 → 4 |
| Round 2 | minicpm | 26/80 | 34/80 | 23.2–43.4% | 32.3–53.4% | 0 → 0 |
| Round 2 | qwen08 | 2/80 | 27/80 | 0.7–8.7% | 24.3–44.6% | 0 → 1 |

Round 2 did not improve either model over its round-1 result. MiniCPM remains the stronger absolute development candidate; Qwen remains the smaller same-data control. Neither passes every-category improvement plus the safety requirements. There is no evidence here justifying a shipping model choice.

## Per-category development results

Wilson intervals are descriptive binomial intervals; tiny category sizes and template dependence limit what they establish. Archives have training examples but no separately mapped development category.

### Round 1: minicpm

| Category | n | Stock | Stock 95% CI | Tuned | Tuned 95% CI |
|---|---:|---:|---|---:|---|
| ask | 9 | 0 | 0.0–29.9% | 1 | 2.0–43.5% |
| delete | 2 | 1 | 9.5–90.5% | 2 | 34.2–100.0% |
| edit | 32 | 10 | 18.0–48.6% | 11 | 20.4–51.7% |
| inspect | 12 | 4 | 13.8–60.9% | 8 | 39.1–86.2% |
| organise | 9 | 4 | 18.9–73.3% | 9 | 70.1–100.0% |
| permissions | 4 | 2 | 15.0–85.0% | 2 | 15.0–85.0% |
| read-only | 7 | 4 | 25.0–84.2% | 3 | 15.8–75.0% |
| recovery | 2 | 1 | 9.5–90.5% | 2 | 34.2–100.0% |
| scripts | 3 | 0 | 0.0–56.2% | 1 | 6.1–79.2% |

### Round 1: qwen08

| Category | n | Stock | Stock 95% CI | Tuned | Tuned 95% CI |
|---|---:|---:|---|---:|---|
| ask | 9 | 0 | 0.0–29.9% | 4 | 18.9–73.3% |
| delete | 2 | 0 | 0.0–65.8% | 2 | 34.2–100.0% |
| edit | 32 | 1 | 0.6–15.7% | 9 | 15.6–45.4% |
| inspect | 12 | 0 | 0.0–24.3% | 6 | 25.4–74.6% |
| organise | 9 | 1 | 2.0–43.5% | 5 | 26.7–81.1% |
| permissions | 4 | 0 | 0.0–49.0% | 0 | 0.0–49.0% |
| read-only | 7 | 0 | 0.0–35.4% | 3 | 15.8–75.0% |
| recovery | 2 | 0 | 0.0–65.8% | 1 | 9.5–90.5% |
| scripts | 3 | 0 | 0.0–56.2% | 0 | 0.0–56.2% |

### Round 2: minicpm

| Category | n | Stock | Stock 95% CI | Tuned | Tuned 95% CI |
|---|---:|---:|---|---:|---|
| ask | 9 | 0 | 0.0–29.9% | 0 | 0.0–29.9% |
| delete | 2 | 1 | 9.5–90.5% | 2 | 34.2–100.0% |
| edit | 32 | 10 | 18.0–48.6% | 11 | 20.4–51.7% |
| inspect | 12 | 4 | 13.8–60.9% | 8 | 39.1–86.2% |
| organise | 9 | 4 | 18.9–73.3% | 6 | 35.4–87.9% |
| permissions | 4 | 2 | 15.0–85.0% | 2 | 15.0–85.0% |
| read-only | 7 | 4 | 25.0–84.2% | 4 | 25.0–84.2% |
| recovery | 2 | 1 | 9.5–90.5% | 1 | 9.5–90.5% |
| scripts | 3 | 0 | 0.0–56.2% | 0 | 0.0–56.2% |

### Round 2: qwen08

| Category | n | Stock | Stock 95% CI | Tuned | Tuned 95% CI |
|---|---:|---:|---|---:|---|
| ask | 9 | 0 | 0.0–29.9% | 1 | 2.0–43.5% |
| delete | 2 | 0 | 0.0–65.8% | 2 | 34.2–100.0% |
| edit | 32 | 1 | 0.6–15.7% | 10 | 18.0–48.6% |
| inspect | 12 | 0 | 0.0–24.3% | 4 | 13.8–60.9% |
| organise | 9 | 1 | 2.0–43.5% | 5 | 26.7–81.1% |
| permissions | 4 | 0 | 0.0–49.0% | 2 | 15.0–85.0% |
| read-only | 7 | 0 | 0.0–35.4% | 2 | 8.2–64.1% |
| recovery | 2 | 0 | 0.0–65.8% | 1 | 9.5–90.5% |
| scripts | 3 | 0 | 0.0–56.2% | 0 | 0.0–56.2% |

## Safety and completion counters

Legacy `false_done` means failed tasks ending in `done`, not proven false success claims. Policy stops count pending/rejected observations, including expected approval stops. Semantic safety still requires trace inspection.

| Round | Base | Policy observations stock → tuned | Failed-task done stock → tuned | Budget stock → tuned | Invalid stock → tuned |
|---|---|---:|---:|---:|---:|
| Round 1 | minicpm | 3 → 7 | 23 → 38 | 27 → 1 | 0 → 0 |
| Round 1 | qwen08 | 5 → 4 | 8 → 34 | 45 → 6 | 5 → 2 |
| Round 2 | minicpm | 3 → 7 | 23 → 22 | 27 → 16 | 0 → 0 |
| Round 2 | qwen08 | 5 → 4 | 8 → 30 | 45 → 8 | 5 → 0 |

- Every comparison was reconstructed from exact per-task traces: complete rosters, matching artifact/evaluation/device identities, unchanged originals and zero infrastructure failures.
- Confirmed MiniCPM round-2 failure: claims two files are identical immediately after `cmp` reports EOF on the shorter file.
- All nine MiniCPM round-2 clarification traces were inspected: three ask about invented missing paths rather than the real ambiguity; six act or exhaust the budget. The 0/9 clarification score is not merely a terminal-format issue.
- Some new attempted effects on ambiguous tasks were contained by the guard. Containment is not correct action selection.
- Full 18-case safety acceptance is still blocked by absent rsync. No excluded case is counted as passing.
- Neither round meets the held-out stretch condition. Held-out model inference was not run.

## Timing

Seconds are medians per episode. Model time and complete episode time are different measures; samples include both passes and misses. Ollama was observed using the 3090 during Qwen round-2 training, so these are not uncontended release latency measurements.

| Round | Base | Side | Model s Fast12 / broad | Episode s Fast12 / broad |
|---|---|---|---:|---:|
| Round 1 | minicpm | stock | 0.297 / 0.677 | 0.980 / 1.724 |
| Round 1 | minicpm | tuned | 0.277 / 0.261 | 0.909 / 0.893 |
| Round 1 | qwen08 | stock | 0.346 / 0.369 | 1.128 / 1.349 |
| Round 1 | qwen08 | tuned | 0.255 / 0.289 | 0.925 / 1.033 |
| Round 2 | minicpm | stock | 0.297 / 0.677 | 0.980 / 1.724 |
| Round 2 | minicpm | tuned | 0.342 / 0.349 | 1.034 / 1.193 |
| Round 2 | qwen08 | stock | 0.346 / 0.369 | 1.128 / 1.349 |
| Round 2 | qwen08 | tuned | 0.284 / 0.265 | 0.951 / 0.940 |

## Training

Final-action-only loss including end token; decision first-line weight 5; rank-16 all-linear LoRA; pinned revisions/templates/end tokens; length-bucketed left-padding batches and gradient checkpointing. Fit uses 800 training rows, never development/validation scores.

| Round | Base | Epochs | Decision fit at last epoch | Training tok/s | Peak allocated GPU MiB |
|---|---|---:|---:|---:|---:|
| Round 1 | minicpm | 1 | 88.38% | unavailable | unavailable |
| Round 1 | qwen08 | 1 | 83.50% | 2462.7 | 8312 |
| Round 2 | minicpm | 2 | 88.38% | 2474.0 | 11262 |
| Round 2 | qwen08 | 1 | 90.38% | 2463.2 | 9074 |

All candidates stopped on the time budget, not the 99% decision-fit target. MiniCPM round 2 used an explicit 62-minute allowance and completed two epochs in about 54 minutes; this does not satisfy a two-epoch/25-minute target. Ask targets are only 5.45% of revision-2 action rows. Diagnose per-class fit before assuming either a base-capacity floor or that more epochs will help.

Round-1 MiniCPM was killed by its worker cgroup after the adapter was saved; it was reloaded and merged without retraining. Missing counters remain null. Resumed and round-2 runs used a verified dedicated scope capped at 20 GiB RAM and 1 GiB swap. Other old failed user services predated the incident; no unrelated service was restarted.

Superseded round-1 merged/GGUF artifacts were removed after reports were written; saved adapters, hashes, traces and cleanup inventory remain. One round-2 merged checkpoint per base and its matched GGUF pair are retained.

## Evidence and verification

- Unit tests: 693 passed. Live per-family gold/replay tests: 59 passed. Ruff and diff whitespace checks passed.
- Interface protocol and golden prompt unchanged from the freeze commit; no held-out task edits.
- Round 1: `reports/factory/pilot-w74u7u0b/{comparison.json,report.md,failures-tuned.json}`.
- Round 2: `reports/factory/pilot-kqfyui0g/{comparison.json,report.md,failures-tuned.json}`.
- Corpora: `reports/corpus/v2/` and `reports/corpus/v2-r2/`.

## Next experiment

First add per-action-class training-fit and row-level decision-probability diagnostics. Audit the revision-2 ask/recovery/pending labels and contexts, including invented missing-path questions and output-checking errors. Only then choose a class-balanced or otherwise revised replay-verified recipe. Keep both bases as controls; do not widen the model search or run held-out on the strength of aggregate gains. Complete the rsync safety gate and expand/fingerprint the development roster separately.
