# Plan: the model picks the tool, the application owns the answer

Saved 2026-11-20 ~19:30 EST. Ivy's direction: the model just chooses the right tool, and the
effort goes into the application layer so it cannot make the mistake. This extends interface
v2's principle (the trusted executed plan and diff replace the model's change summary) to
answers and to read-only requests.

Do not touch `lilguy/`, `dev/fast12*.py`, `dev/broad_*.py` or `toolset.yaml`/`policy.yaml` until
the seed-43 job (`reports/factory/pilot-xif8k6a9`) finishes. They are inputs to the evaluation
fingerprint, so editing them mid-batch would make the remaining arms incomparable.

## Evidence (19 confirmed wrong answers, MiniCPM + Qwen cosine, revision 6)

| What went wrong | Count | Tasks | What prevents it |
|---|---:|---|---|
| The right fact was in the last output, but the model misread or miscopied it | 6 | latest_iso_timestamp, report_largest_measured_document, summarize_missing_packet_ids, find_todo_comments (Q); utf8_line_count (Q, debatable); detect_absent_final_line_feed (M) | Quoted answers (step 2) |
| Yes/no property judged from raw output: byte direction, execute bit, final LF, same/differ | 6 | copy_mode_without_executable_bit (M, Q), compare_preserved_record_bytes (M, Q), detect_absent_final_line_feed (Q), matching_normalized_addresses (Q) | Fact tools with unambiguous wording (step 3) |
| Claims of effects that never happened | 2 | bump_version_two_files, files_with_dash_prefix (Q) | Already neutralised: the trusted executed plan and diff are the report |
| Wrong or insufficient command; the fact appears nowhere | 5 | aggregate_signed_amounts (Q), reconcile_manifest_versions, summarize_missing_packet_ids, filter_capacity_at_inclusive_limit (M), compute_inventory_level_over_default (Q) | Better tool choice: narrowing-command data (step 2) and fact tools (step 3) |

Read-only writes: both cosine adapters still create new files in tasks that say not to
(MiniCPM `missing.txt`; Qwen two `-trim` copies). That is step 1.

## Steps, by effort and payoff

1. **Read-only mode in the application.** Small effort, no retraining.
   - `lilguy ask "..."` (and an MCP flag) runs a session whose policy rejects every write. A
     question can then never change files, whatever the model does.
   - The user's choice of command replaces the model's guess from request wording ("do not
     modify"). This is the constrained-input idea from earlier.
   - The model only learns that a rejected write in `ask` mode means "use a read tool". The
     rejection observation already exists.
   - Check: replay the 19 read-only development tasks in `ask` mode with the scripted solution
     (must pass) and with the recorded bad traces (writes must be rejected, originals unchanged).
2. **Quoted answers (interface v3).** Medium effort: evaluator change, data change, retraining.
   - On a no-change episode, the answer the user sees is the final successful command and its
     stdout, quoted verbatim from the audit log: "Answer from `LC_ALL=C sort arrivals.tsv |
     tail -n 1`: 2026-08-17T10:24Z sparrow".
   - The model's text becomes an optional unverified note, exactly like the change summary in v2.
   - The model's job becomes "run a command whose output is the answer". Training data teaches
     narrowing commands (`sort | tail -n 1`, `grep -c`, `wc -l <`, `comm -23`, `awk` sums,
     `cmp`/`tail -c 1`) followed by bare `done`.
   - Grading of answer tasks moves to the quoted output, through the same fact regexes on the
     stdout body. This is an evaluation change, so the held-out suite needs re-calibrating (the
     scripted solutions already end with narrowing commands; check each) before any model runs on
     it. Needs Ivy's approval as an interface change.
   - Check: re-grade the recorded seed-42/43 traces under quote grading, as an offline estimate
     only. Then train revision 7 with cosine and compare against revision-6 cosine on the fixed
     roster.
3. **Fact tools with fixed wording.** Larger effort: new typed tools, schemas, policy, data, retraining.
   - `fs.stat PATH` reports size, mode with execute bits spelled out, and the last byte with
     "ends with LF: yes/no".
   - `fs.compare A B` reports same/differ, the first differing line and both sizes with "A is N
     bytes longer than B".
   - Optional: `fs.lookup FILE KEY` for ini/conf values, including the override rule.
   - The app computes these facts, so a 0.8B model never has to infer direction or bit meaning
     from `ls -l` or `od`.
   - Add a tool only where the audit shows repeated misreads. Keep the tool list short.

## Order and gates

1. Finish and report the seed-43 replication first, without editing fingerprinted sources
   mid-batch.
2. Step 1 (read-only mode): implement, test, commit. No model run is needed to prove it.
3. Get Ivy's approval for interface v3 (quoted answers and the grading move). Then do step 2 as
   one controlled data/interface change on the best recipe (cosine), with held-out recalibrated,
   not run.
4. Step 3 only for the property questions that remain wrong after step 2.
