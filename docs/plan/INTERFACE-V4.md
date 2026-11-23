# Interface v4 round: append, ambiguous edits, exact answers

Status: started 2026-11-22, after release 1.1.0. Versioning follows [ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on). A corpus or schedule change alone is not a new interface version. v4 is declared only if the protocol, tools or observations the model sees change.

## Why this round

Training clearly helps. On the 80-task development suite, stock MiniCPM5-2B passes 18/80 and the four r8 runs passed 44–51. General corpus revisions have stopped paying, though: r7→r8 and r8→r9 moved by −3 to +4, which is within seed noise. Held-out 1.0 (74/100) and development agree on three narrow weaknesses:

| Weakness | Held-out 1.0 | Development evidence |
|---|---|---|
| Appending a multi-line block | 0/10 | no development task covers it (all appends are one line) |
| Editing one of two identical lines | 2/10 | `exact_match_required_edit` was the r8/r9 swing task |
| Quoting an exact answer | 4/10 | read-only 4/7; question misses were mostly wrong final commands |

The held-out 1.0 failures are **not** read or analysed. That suite is spent on the 1.0 model, and its traces must not shape the next one. Every diagnosis below uses fresh development fixtures.

## Steps, weighed by effort

| # | Step | Effort | Decides |
|---|---|---|---|
| 1 | Run stock MiniCPM on held-out once, so the training effect is measured on unseen tasks | 10 min GPU | how much training buys on unseen tasks |
| 2 | Write fresh focus fixtures, 4–6 per weakness, with oracle and false-done controls, audited against held-out for overlap. Kept out of the 80-task roster so its fingerprint stays comparable. | ~1.5 h | — |
| 3 | Run r8 (1.0) and stock on the focus set; for each miss, record the first consequential action | 15 min GPU + reading | interface or data |
| 4 | Interface fixes where step 3 points at the interface. Example: an `fs.edit` failure that says how many matches there are and on which lines. Example: an append path that does not need shell quoting. | 1–3 h | v4 declared or not |
| 5 | Re-run r8 on the focus set with the v4 interface and no retraining. If the interface alone fixes a weakness, stop there for that weakness. | 15 min GPU | whether training is needed |
| 6 | Only for what is left: targeted corpus families, then one matched retrain at two seeds | ~3 h GPU | promotion candidate |
| 7 | A new frozen held-out suite (v2) before any new candidate is promoted | ~2 h | — |
