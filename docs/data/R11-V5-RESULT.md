# Round 11: interface v5 + corpus revision 11 (2026-11-23)

**Question:** do interface v5 and corpus revision 11 fix 2.0's weak spots without costing anything elsewhere?

**Answer:** they fix the weak spots, but they cost the general roster, so r11 is **not a promotion candidate**.

- **Focus set (2.0's weak spots):** from 15/25 to 24/25 and 23/25 at the two seeds. Appending to a file without a final newline went from 0/5 to 5/5 at both seeds.
- **80-task roster:** 49/80 and 48/80, against 54/80 for 2.0 on the same interface. Both seeds lose the same five tasks.
- The v5 interface by itself costs nothing (2.0: 53 on v4, 54 on v5), so the roster losses come from the training data.

Held-out v3 was not run or read.

## Runs

All runs used the RTX 3090, the same code (`7e3562b`, clean), the managed server and the usual controls. There were zero infrastructure failures in every run.

| | roster (80) | focus-r11 (25) | focus-v4 (15) |
|---|---|---|---|
| Stock MiniCPM5-2B, v5 | 19 | — | — |
| 2.0 (r10 s42), v4 | 53 | 15 | — |
| 2.0 (r10 s42), **v5, no retraining** | **54** | **16** | — |
| **r11 s42**, v5 (`pilot-qn939y7n`) | **49** | **24** | 14 |
| **r11 s43**, v5 (`pilot-m4rfzsq1`) | **48** | **23** | 15 |

**Run locations:**
- 2.0 on v4: `fast12-hictavrs` and `broad-n4ye6ya7`.
- 2.0 on v5: `fast12-bazwwl4u` and `broad-t887e76u`.
- Focus-r11 (2.0): `focus-r11-2.0-v{4,5}-*`.
- Focus-r11 (r11): `focus-r11-r11s{42,43}`, and `-v4set` for the v4 focus fixtures.

**Training:** the same cosine recipe as 1.0 and 2.0, 1 epoch. That came to 542 optimizer steps on 8,667 rows from 2,740 episodes, about 56 minutes per seed. Every episode passed both its gold run and its replay.

### Interface v5 alone

| Set | v4 | v5 | Change |
|---|---|---|---|
| Roster | 53 | 54 | gained `compute_inventory_level_over_default`, lost nothing |
| Focus | 15 | 16 | the named-missing script task now asks |

**Missing final newline:** the untrained model saw `(no newline at end of output)` and appended anyway (`betagamma`). The marker needs training, and v5 by itself is safe.

### Focus-r11 groups

| Group | 2.0 v5 | r11 s42 | r11 s43 |
|---|---|---|---|
| quote a value | 4 | 4 | 4 |
| count lines | 3 | 5 | 4 |
| create exact file | 4 | 5 | 5 |
| named file missing | 5 | 5 | 5 |
| append without final newline | 0 | **5** | **5** |

## What revision 11 broke

There are five roster tasks that 2.0 passes on both v4 and v5 and that r11 loses at **both** seeds. Each is listed with the first consequential error at seed 42.

1. **`insert_line_at_changelog_heading`: an append instead of an insert, then a loop.**
   - Asked to add a line under `## Friday`, the model ran `printf '%s\n' '- Verify projector' '## Friday' >> briefing.md`.
   - It saw the duplicated heading and repeated the append until it ran out of turns.
   - 2.0 used a block `fs.edit` under the heading.
   - Revision 11 adds 72 end-of-file appends to r10's 200. This looks like the append habit generalising to "add a line" anywhere.
2. **`summarize_missing_packet_ids`: `done` straight after a failed step.**
   - `comm -23` failed with "not in sorted order", and the model said `done`.
   - This is an honest-terminal regression: lilguy shows the failure, but the question gets no answer.
3. **`count_matching_rows`: `done` on a zero count without looking.**
   - `grep -c 'status: pending'` printed `0` (exit 1) on a CSV, and the model said `done`.
   - 2.0 read the file after the zero and counted with `awk`, getting 2.
   - Possibly the new `read → count → done` questions taught "count, then stop", but their fixtures never produce a zero count.
4. **`no_marker_in_schedule`: `done` after an empty grep.** The final step exited 1 with no output, so there was no answer.
5. **`copy_review_folder_structure`: wrong `cp -r` target, no check.** `cp -r review package/review/` nested the folder as `package/review/review`. The model said `done` without listing the result.

**Common thread:** three of the five end in `done` right after a step that failed or printed nothing useful. Revision 11's new families all end `cmd → read/verify → done`, and none of them shows a step that fails, followed by the model finding out why.

The trace evidence points at that gap and at the append imbalance, but it does not prove either cause. The way to test them is a revision 12 that adds the contrasts below and keeps everything else identical.

## Next (proposal, not started)

**Revision 12 = revision 11 plus contrasts, still on interface v5:**
- **Insert under a heading or in the middle of a file** with a block `fs.edit`, roughly matching the new append count.
- **Question episodes where the first command prints 0 or nothing**, or fails, and the model reads the file and recomputes before `done`. This includes a `comm` on unsorted input fixed with `sort`.
- **Copying a folder's contents,** then listing the result.

Train two seeds again. Promote only if the roster is at least 2.0's 54 on v5 *and* the focus gains hold. Held-out v3 stays untouched until then.
