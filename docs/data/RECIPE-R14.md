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

## Step 2 result (2026-11-26): passes

The three seeds are `pilot-uggk13x0` (42), `pilot-1gr1c1k2` (43) and `pilot-8cyzimdv` (44); the soup is `soup-r14-lr1e4` (`fast12-16u06a17`, `broad-img3dkd_`). All were scored on the RTX 3090 with evaluation fingerprint `57bd8839…`, the same as 2.0's reference (`fast12-5ows29ac`, `broad-jn1p83mj`). There were zero infrastructure failures.

| | total /106 | edit | organise | archives | recovery | training fit (decision) |
|---|---|---|---|---|---|---|
| 2.0 on v6 | 67 | 17 | 9 | 6 | 7 | — |
| r14, lr 2e-4, 1 epoch: s42 / s43 / s44 | 67 / 70 / 59 | 19 / 20 / 13 | 12 / 8 / 8 | 8 / 9 / 7 | 5 / 7 / 6 | 0.965 / 0.959 / 0.965 |
| **lr 1e-4, 2 epochs: s42 / s43 / s44** | **65 / 70 / 68** | 19 / 19 / 22 | 8 / 10 / 7 | 8 / 9 / 7 | 5 / 6 / 6 | 0.986 / 0.989 / 0.989 |
| **soup of the three** | **73** | 22 | 10 | 9 | 6 | — |

**The rule as declared:**
- **Mean above 67:** the mean is **67.67**. Passes, narrowly.
- **No seed below 62:** the lowest seed is **65**. Passes.
- **Soup at least 70:** the soup scores **73**. Passes.

**Spread:**
- The seeds now span 5 tasks (65–70), against 11 before (59–70).
- All three seeds agree on **85/106** tasks, against 74 with the old recipe.
- s44 no longer collapses in edits (22 against 13).

The slower, longer recipe reduced seed variance, which is what it was meant to do.

**None of the three seeds reached the 99% training fit.** After 2 epochs they ended at 98.6–98.9%, so the epoch cap, not the fit stop, ended each run.

**Held-out decision (Ivy).** The roadmap rule declared before r14 names **seed 42** (65 here) as the candidate that goes to held-out. The soup (73) was declared as a measurement with its own bar, not as the held-out candidate. Sending the soup instead is defensible, because it depends on all three seeds and so picks none of them. It is still a change to the declared rule, so it needs Ivy's call before held-out v3 is spent.

**Decided (Ivy, 2026-11-26): the soup goes to held-out v3**, instead of the seed 42 named in the roadmap rule. This is a recorded deviation, for three reasons:
- the soup was declared before training, with its own bar (70), and it passed that bar;
- it is a fixed function of all three seeds, so choosing it picks no seed;
- held-out v3 gives an unbiased score of this exact file, whatever role development selection played.

What this costs: development selection among four artifacts may flatter the soup's 73, so the held-out score is the claim and the development score is not.

Before any model saw the suite, the held-out v3 controls passed under v6: oracle 100/100 and false-done 0/100 (`tests/sandbox/test_holdout_suite_v3_v6_live.py`). Held-out v3 runs once on the soup (v6) and once on 2.0 (v4), as INTERFACE-V6 step 5 planned.
