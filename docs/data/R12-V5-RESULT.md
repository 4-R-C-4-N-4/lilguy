# Round 12: revision 11 plus contrasts, interface v5 (2026-11-23)

**Question:** do contrast families for revision 11's roster losses bring the roster back to 2.0's level and keep the focus gains?

**Answer:** no. r12 holds the focus gains and recovers part of the roster, but not enough to pass the promotion bar. The predeclared gate was a roster score of at least 54/80, which is 2.0 on v5.

- **Roster:** 50/80 and 51/80 (r11 scored 49 and 48).
- **Focus-r11:** 24/25 at both seeds.
- **Verdict:** not promoted. 2.0 stays the release. Held-out v3 is still unused.

## Runs

RTX 3090, same code (`e65d98f`), corpus `reports/corpus/v5-r12`. That corpus has 2,933 episodes and 9,336 rows; all passed gold and replay. Training used the cosine recipe for 1 epoch: 584 steps, about 60 minutes. There were zero infrastructure failures.

| | roster (80) | focus-r11 (25) | focus-v4 (15) |
|---|---|---|---|
| 2.0, v5 (the bar) | 54 | 16 | — |
| r11 s42 / s43 | 49 / 48 | 24 / 23 | 14 / 15 |
| **r12 s42** (`pilot-n8gbd5zn`) | **50** | **24** | 14 |
| **r12 s43** (`pilot-tjwmpsj2`) | **51** | **24** | 15 |

### What the contrasts fixed

Three of r11's five shared losses now pass at seed 42. In each, the model now investigates the failure before `done`:
- `count_matching_rows` (a zero count),
- `no_marker_in_schedule` (an empty grep),
- `summarize_missing_packet_ids` (a failed `comm`).

`insert_line_at_changelog_heading` now uses the right move, a block `fs.edit` under the heading. At seed 42 it then copied request words into the inserted line.

### Shared losses against 2.0 on v5 (both seeds)

First consequential error, seed 43:

1. **`aggregate_signed_amounts`: two different failures, and not a leaked habit.**
   - At seed 43 the model summed with `awk 'NR>1 …'` over a headerless list and got `-7` instead of `11`. At seed 42 it skipped the read and repeated a broken `awk -F'[:+]='` pipeline.
   - *Correction (interpretability lesson 1, [plan](../plan/INTERPRETABILITY.md)):* this was first blamed on revision 11's header-skipping counts. That is wrong. Both r11 seeds **pass** this task.
   - The probe shows that the **unmodified base already prefers `NR>1`** here (+0.71 nats). Every tuned model prefers the correct sum, and r12 seed 43 only barely (−0.43): a near coin-flip that the Q8_0 server tipped the wrong way.
2. **`copy_review_folder_structure`: the folder was nested again.**
   - It ran `mkdir -p package/review && cp -r review package/review/`.
   - Revision 12 taught copying a folder's *contents* (`src/.`). This task wants the folder itself copied into a parent, a variant the family does not include.
3. **`executable_tools_group_pending`: `chmod g+s` where `g+x` was meant.** The change was staged for review, not applied. This is the long-standing permission-wording weakness, not new.
4. **`generate_tuple_named_notes`: a redirect to a literal glob** (`> queue/*.tsv`), followed by an attempt to delete the readme, which went to approval.
5. **`matching_normalized_addresses`: the same broken `diff` pipeline repeated until the turn budget ran out.**

Four tasks gained at both seeds: `export_codes_with_print_separator`, `preserve_dotfile_during_backup`, `merge_pages_in_named_order`, `guide_selected_input`.

## What these two rounds show

- **Every targeted family fixes its focus task and leaves a habit behind.**
  - r11's end-of-file appends turned into appending where an insert was asked for.
  - (The header-skipping on headerless files first listed here was not caused by r11; lesson 1 traced it to the base model's own prior.)
  - r12's fixes for those then exposed the next variant (folder versus folder contents).
- **The roster is no longer a clean judge.** It has been read across rounds 7–12, and two more rounds of patching its misses would be tuning to it. Held-out v3 is the unbiased measure, and it should be spent only on a candidate that clears the roster first.
- **The weak spots are real and trainable.** All four tuned runs scored 23–24/25 on focus-r11, against 15–16 for 2.0. The cost lies in the balance of the corpus, not in the interface. v5 by itself costs nothing (2.0: 54 on v5).

## Options

1. **Keep 2.0. Pause the data rounds on this base** until there is a better way to stop new families leaking habits. Two such ways:
   - near-miss contrasts written *with* each family: a headerless sum next to every header skip, the folder itself next to every folder-contents copy, an insert next to every append;
   - mixing in a replay of r10's episodes at full weight.
2. **One more round, r13, built as above:** for every r11/r12 family, add its near-miss twin. Then two seeds, and the same ≥ 54 gate. About 3 hours.
3. **Weight-space checks, about 1 hour.** Average the r12 seeds, or scale r12's update down. This is cheap, but it only trades focus against roster; it fixes neither.
