# Round 13: the training mix only (2026-11-24)

**Question:** interpretability lessons 3–4 found that the append-for-insert habit is an output default the model can be steered out of. If inserts are rebalanced against appends, with nothing else changed, does the habit go and does the roster recover?

**Answer:**
- **The targeted habit is gone at both seeds.** Every r13 run writes a block `fs.edit` under the heading instead of appending.
- **The roster still misses the gate.** r13 scored 53/80 and 48/80, against 54 for 2.0 on v5. The two seeds are 5 tasks apart, the largest seed spread so far.
- **Not promoted.** Held-out v3 is still unused.

## What changed

Revision 13 is revision 12 with `insert_under_heading` raised from 84 to 252 episodes, about as many as the 272 end-of-file appends. The first 84 are revision 12's own episodes, and every other episode is identical (`tests/unit/test_corpus_r12.py`).

| | |
|---|---|
| Corpus | `reports/corpus/v5-r13`: 3,101 episodes, 10,008 rows, all gold- and replay-verified |
| Training | same cosine recipe, 1 epoch |
| Runs | `pilot-dt3a2cu2` (seed 42), `pilot-ujdjz7ql` (seed 43) |

## Results (RTX 3090, interface v5, zero infrastructure failures)

| | roster (80) | focus-r11 (25) | focus-v4 (15) |
|---|---|---|---|
| 2.0 on v5 (the bar) | 54 | 16 | — |
| r12 s42 / s43 | 50 / 51 | 24 / 24 | 14 / 15 |
| **r13 s42** | **53** | 23 | 15 |
| **r13 s43** | **48** | **19** | 14 |

Seed 43's focus drop is almost entirely "named file missing": 1/5, against 4–5/5 for every other v5-trained run.

### Margins (`dev.factory margins`, `reports/factory/margins-4k_ugmi1`)

| Verdict | Count |
|---|---|
| habit | 7 |
| lean | 1 |
| coin flip | 1 |
| not reproduced | 2 |
| harmless first look | 4 |

The only **actionable** loss (a habit at both seeds) is `insert_line_at_changelog_heading`. It is worth reading closely:

- **The request:** *"In briefing.md, add the line - Verify projector directly beneath ## Friday, before existing entries."*
- **What both r13 seeds did:** inserted `- Verify projector directly beneath ## Friday` under `## Friday` with a block `fs.edit`. That is the right tool and the right place.
- **Why it fails:** the grader expects the line `- Verify projector`. The unquoted request leaves the line's end ambiguous. The stock model makes the same reading (+7.0), and r13 reads it so more firmly (+8.1, +14.0).
- **What that means:** the remaining failure is a defensible parse of an unquoted request, not the append habit. The roster is fingerprinted, so the task stays as it is. It goes on record as a roster ambiguity, and as a reason to quote literal lines when asking lilguy to insert them.

The other habits belong to a single seed: an extra written line and a cover replacement at s43, and an inventory append at s42.

## What this round shows

1. **Fixing the mix fixes the mechanism.** The habit that lessons 3–4 located (an output default at the answer slot) disappeared when its training frequency was balanced, with no new families.
2. **Seed variance now dominates the roster.** The same corpus gives 53 and 48. Four rounds in a row (r11–r13) have both seeds inside 48–53, against a bar of 54. The roster can no longer separate these revisions from 2.0 with two seeds.
3. **What would decide it next:**
   - three or more seeds per candidate, or a larger development suite (the plan already lists 150 tasks);
   - or spending held-out v3 on the best candidate *and* 2.0, accepting that one seed is a draw from that spread.
   Neither should be decided by more data rounds.
