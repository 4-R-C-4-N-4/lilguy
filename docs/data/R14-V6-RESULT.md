# Round 14: interface v6, archive tools and permission words (2026-11-25)

**Question:** with the typed archive tools (v6) and permission requests trained in words and numbers, does a revision beat 2.0 under the [three-seed rule](../plan/ROADMAP.md#2026-11-24--promotion-rule-for-training-rounds-from-r14-on-decided-before-r14)?

**Answer: no.**
- The mean is 64.0 against 2.0's 66, and the lowest seed (58) is below the floor of 61.
- **Not promoted.** Held-out v3 stays unused.

## What was trained

- **Corpus:** `reports/corpus/v6-r14` (revision 14), 3,221 episodes and 10,416 rows. Every episode passed its gold run and replay in the sandbox.
- **Content:** revision 13 recorded on v6. The 45 original archive episodes use `archive.list`/`archive.unpack` instead of `tar`, and three families are added:

  | Family | Episodes |
  |---|---|
  | `archive_tools` | 60 |
  | `archive_compare` | 12 |
  | `permission_words` | 48 |

- **Training:** the same cosine recipe, 1 epoch, at seeds 42, 43 and 44:
  - seed 42: `pilot-jva98lp6`
  - seed 43: `pilot-p9v61cz0`
  - seed 44: `pilot-_e3jrcos`

## Results

RTX 3090, interface v6, 106 roster tasks, zero infrastructure failures. Evaluation fingerprint `46d28bb3…`, the same as the 2.0 reference run (`fast12-zv092wyr`, `broad-flc40862`).

| | total | edit (32) | organise (17) | permissions (4) | archives (10) | recovery (10) |
|---|---|---|---|---|---|---|
| 2.0 on v6 | **66** | 17 | 9 | 3 | 5 | 7 |
| r14 s42 | 66 | 19 | 12 | 2 | 7 | 5 |
| r14 s43 | **68** | 20 | 8 | 2 | 7 | 7 |
| r14 s44 | 58 | 13 | 8 | **4** | 6 | 6 |
| stock MiniCPM | 26 | | | | | |

**The rule's two checks:**
- the mean, 64.0, must be above 66: **fails**;
- the lowest seed, 58, must be at least 61: **fails**.

## What worked, and what did not

- **Archives improved at every seed:** 7, 7 and 6 against 5. This is the targeted gain, the first category to rise at all three seeds of a round.
- **Permissions did not move reliably:** 2, 2 and 4 against 3.
  - `restrict_local_draft_mode` ("owner-readable and owner-writable only") is still lost by s42 and s43, even with 8 owner-only (`600`) examples in the mix.
  - s44 passes all four permission tasks.
- **The seeds are 10 tasks apart (58–68).** That is the largest spread yet; it was 5 for r13 on 80 tasks and 9 for r13 on 106.
  - s44's whole deficit is in edits (13 against 17–20 for the other seeds and 2.0). It loses plain edits the other seeds keep: `diff_two_lists_added`, `find_lines_with_error`, `append_absent_inventory_entry`.
  - This is the variance that motivated the three-seed rule. Under the old two-seed rule, seeds 42 and 43 would have been judged 66 and 68, at and above the bar.
- **Lost by all three seeds:** `copy_three_one_elsewhere`, one of the recovery tasks added in batch 7. The other losses are spread across seeds.

## Not done this round

- **Decision margins** (`dev.factory margins`) were not run. The interpretability lab (`dev/interp/common.py`) still builds prompts for interface v5, so v6 runs need that updated first.

## What this suggests

Targeted data now reliably moves its target (archives), but every round so far lands inside a band of roughly 58–68 around 2.0's 64–66. The gate cannot be passed by adding families, because the seed-to-seed spread is as large as any gain.

The next useful levers are the training recipe, not more data:
- **Stability:** a lower learning rate, more epochs, or averaging the adapters of several seeds, to reduce seed variance.
- **Base model:** a per-base recipe choice for Qwen, which the original task called for.
