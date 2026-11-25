# Recipe rounds on the r14 corpus (from 2026-11-25)

**Why:** r14's three seeds scored 67, 70 and 59 on the 106-task roster (re-scored on the cleaned archive tasks). Two of them, seeds 42 and 44, fit their training rows identically: 96.5% decision accuracy and 99.44% token accuracy. Neither reached the 99% fit target, because one epoch ran out. Same fit, different habits: the spread comes from where each run generalizes, not how much it learned.

## Step 1: average the three seeds ("model soup"), done

- **Method:** base + the mean over seeds of each module's full LoRA change, `B·A·α/r` (`dev/soup.py`). A single-adapter soup equals PEFT's merge exactly.
- **Rule, declared before scoring:** at least 70 (2.0's 67 + 3).
- **Result:** **66**, using `reports/factory/soup-r14-s42-s43-s44` (`fast12-04m7l1k5`, `broad-mb9ibs6p`), same fingerprint `57bd8839…`. **Fails.**

The soup acts as a majority vote of its seeds:

| Seeds passing a task | Soup passes |
|---|---|
| 3 of 3 | 48 / 48 |
| 2 of 3 | 14 / 20 |
| 1 of 3 | 2 / 12 |
| 0 of 3 | 2 / 26 |

It lands at the seeds' mean (65.3), without s44's low tail and without anything new. The seeds really disagree, rather than scattering around one better model, so averaging alone cannot pass 2.0.

## Step 2: a steadier recipe, declared before training

| | r14 (as trained) | **step 2** |
|---|---|---|
| corpus | `reports/corpus/v6-r14` | same |
| peak learning rate | 2e-4 | **1e-4** |
| epochs | 1 (always ran out) | **up to 2**, stopping at the 99% / 98% training fit |
| schedule | 3% warmup, cosine | same, laid over 2 epochs |
| LoRA, decision weight, batches | r16 α32, 5, 24k tokens | same |
| seeds | 42, 43, 44 | 42, 43, 44 |

Only the learning rate and the epoch cap change.

- **Judged by the three-seed rule** against 2.0 on the same code and GPU, 67 on the current roster: the mean must be above 67, with no seed below 62.
- **Also measured:** the three seeds averaged into one soup, against the same bar of 70 as step 1.
- **Cost:** about 3 hours of GPU per seed.
