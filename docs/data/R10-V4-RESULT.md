# Round report: corpus r10 on interface v4 (2026-11-23)

**Question:** do training examples for multi-line edits and appends (r10), together with the framed, specific-refusal interface (v4), fix the weaknesses found in 1.0? And do they do it without costing the rest?

**Answer:** yes on the focus set: 7/15 → 14/15 and 13/15. The 80-task roster is flat to slightly up: 51 → 53 and 52. Both seeds agree. Both results are development numbers, and no held-out suite has been run on r10.

## Setup

- **Base:** MiniCPM5-2B, same recipe as 1.0: cosine schedule, 1 epoch, at most 50 minutes. One run at train seed 42 and one at seed 43, on the RTX 3090.
- **Data:** `reports/corpus/v4-r10`, 2,484 episodes and 7,745 rows, all replayed in the sandbox.
  - Revision 8 re-recorded under v4.
  - Plus 320 new episodes in four families: block-edit-repeated, multiline-append, append-after-missing-newline and indented-append.
  - Deduplicated against the 80-task roster and the focus fixtures, and gated against the held-out suite.
- **Runs:** `pilot-5bw___5q` (seed 42) and `pilot-64ln7bik` (seed 43).
- **Baseline:** the 1.0 model (r8) on the same code under v3 (`v4-interface-only-20261123-0752/v3`).
- **Infrastructure failures:** zero, across all runs.

## Results

| | Stock (v4) | 1.0 r8 (v3) | 1.0 r8 on v4, no retraining | r10 seed 42 | r10 seed 43 |
|---|---|---|---|---|---|
| 80-task roster | 19 | 51 | 47 | **53** | **52** |
| Focus: multi-line append | 1/5* | 2/5 | 3/5 | 4/5 | 4/5 |
| Focus: line occurs twice | 0/5* | 0/5 | 0/5 | **5/5** | **5/5** |
| Focus: exact answer | 2/5* | 5/5 | 5/5 | 5/5 | 4/5 |
| Said "done" on a wrong result (80 tasks) | — | 12 | — | 23 | 17 |

\*Stock was run on the focus set under v3.

Roster tasks gained by **both** seeds over r8:
- `exact_match_required_edit`
- `insert_line_at_changelog_heading`
- `update_only_section_match`
- `repair_unclosed_shell_branch`
- `recover_export_owner_lookup`
- `matching_normalized_addresses`

Roster tasks lost by **both** seeds:
- `emit_literal_print_script`: it nested single quotes, then fell back to double quotes, so `$STAGE` would expand.
- `merge_pages_in_named_order`: it ran out of turns after a correct `cat`.
- `preserve_dotfile_during_backup`: it copied the one file `fs.list` showed instead of the whole folder.
- `sum_inventory_per_bin`: it counted rows instead of summing them.

None of the four losses involves the new families. They look like ordinary run-to-run variation, of the size r8 showed across seeds.

## What this says

- **The interface alone did not fix the weaknesses; the training examples did.** On v4 without retraining, the 1.0 model ignored the new refusal and kept typing `\n`. After 120 block-edit episodes, both seeds got every repeated-text edit right.
- **Files without a final newline are still not solved.** Both seeds missed this task. `fs.read` cannot show whether a file ends in a newline, so the model only notices after appending. Neither seed used the idiom r10 teaches when the file looked normal. A small interface addition would remove the guessing: `(no newline at end of file)`, as `diff` prints it. It would have to be a new interface version, because r10 was recorded on v4 as it stands.
- **Saying "done" on a wrong result went up.** This needs watching before promotion. The rate rose from 12 to 23 and 17. The model is attempting and finishing more tasks, which is part of it, but it still means more confident wrong results. lilguy's review step covers this, and the held-out "done" rate will show whether it carries over.

## Caveats

- **The focus set is not independent of r10.** It was written to measure exactly what r10 trains. It is deduplicated from the corpus, but the task shapes match. Read 14/15 as "the examples took", not as general skill.
- **Promotion needs a new frozen held-out suite.** Held-out v1 is spent on 1.0. v2 must include multi-line appends and repeated-text edits, and must be written before any r10 model runs on it.

## Next

1. Write and freeze held-out v2: 100 new tasks, including the new skills, checked with oracle and false-done controls.
2. Run it once on the seed-42 candidate (53/80, 14/15).
3. If it beats 1.0's 74/100 standard and keeps zero unreviewed changes, ship it as 2.0. lilguy then needs to start the model on the interface it was trained for: v4 for 2.0, v3 for 1.x.
