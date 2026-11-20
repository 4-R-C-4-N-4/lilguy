# Answer-complete/read-only data and constant vs cosine (in progress)

No candidate selected. The constant arm has completed; the cosine arm is running. Do not interpret this interim report as a completed controlled result.

Development failures shaped revision 6. All development scores below are optimistic, not held-out generalization. No model has run on held-out in this sprint.

## Shared data

Corpus `reports/corpus/v2-r6`, seed 20261119, interface v2. Sources remain the original synthetic fixtures and pinned tldr-pages with per-episode attribution. The v2 protocol and golden prompt remain frozen; no bare-done rejection was added to grading.

| Stage | Count |
|---|---:|
| generated | 2286 |
| dedup | 2164 |
| leakage_gate | 2164 |
| gold_ok | 2164 |
| replay_match | 2164 |
| episodes | 2164 |
| next_action_rows | 6264 |

Exact duplicates removed: 122. Infrastructure/gold/replay failures: {'infra': 0, 'gold': 0, 'replay': 0}. All accepted episodes were replayed in the real sandbox and passed the split gate against the full development roster and pinned held-out manifest.

| Family | Generated | Accepted |
|---|---:|---:|
| append_line | 30 | 30 |
| ask_after_read | 30 | 29 |
| ask_collision | 40 | 40 |
| ask_conflict | 30 | 30 |
| ask_content | 30 | 30 |
| ask_notes | 35 | 35 |
| ask_order | 25 | 23 |
| ask_target | 45 | 45 |
| ask_value | 30 | 30 |
| awk_sum | 60 | 50 |
| chmod_exec_pending | 30 | 30 |
| chmod_private_pending | 15 | 15 |
| conditional_copy | 40 | 40 |
| copy_existing_dir | 20 | 20 |
| copy_glob | 20 | 20 |
| copy_new_dir | 20 | 19 |
| count_files | 60 | 50 |
| count_lines | 60 | 60 |
| count_matches | 60 | 59 |
| delete_build_ok | 22 | 22 |
| delete_by_size_pending | 22 | 20 |
| delete_pending | 22 | 22 |
| delete_tmp_ok | 22 | 22 |
| edit_value | 60 | 60 |
| grep_find | 80 | 80 |
| idempotent_edit | 40 | 40 |
| inspect_cmp | 32 | 25 |
| inspect_hidden | 32 | 18 |
| inspect_lastbyte | 32 | 28 |
| inspect_nonblank | 32 | 23 |
| largest_file | 60 | 27 |
| move_glob_pending | 25 | 18 |
| orient_output | 60 | 60 |
| pipe_cut | 11 | 11 |
| pipe_grep_i | 11 | 11 |
| pipe_grep_v | 11 | 11 |
| pipe_head | 11 | 11 |
| pipe_paste | 11 | 11 |
| pipe_sort | 11 | 11 |
| pipe_sort_n | 11 | 11 |
| pipe_sort_r | 11 | 11 |
| pipe_sort_u | 11 | 11 |
| pipe_tail | 11 | 11 |
| pipe_tr_lower | 11 | 11 |
| pipe_tr_upper | 11 | 11 |
| pipe_uniq_c | 11 | 11 |
| read_value | 120 | 120 |
| recover_absent | 40 | 40 |
| recover_edit | 40 | 40 |
| recover_missing_dir | 30 | 30 |
| recover_read | 40 | 40 |
| rejected_protected | 40 | 40 |
| rename_pending | 25 | 25 |
| replace_all | 40 | 40 |
| ro_check | 80 | 80 |
| ro_compare | 80 | 78 |
| ro_count | 80 | 80 |
| ro_exists | 80 | 79 |
| script_0 | 8 | 6 |
| script_1 | 8 | 4 |
| script_2 | 8 | 5 |
| script_3 | 8 | 3 |
| set_diff | 40 | 40 |
| tar_extract | 15 | 15 |
| tar_extract_one | 15 | 15 |
| tar_list | 15 | 15 |
| text_crlf | 16 | 14 |
| text_distinct | 16 | 15 |
| text_range | 16 | 16 |
| text_starts | 16 | 15 |
| truncate_pending | 16 | 16 |
| verify_fix | 30 | 30 |

Accepted endings: 915 answered done, 1,229 bare done, 20 missing-input asks. Revision 5 had 503 answered done; the corpus expansion changes exposure as well as content relative to revision 5. Both new scheduler arms use exactly the same revision-6 rows.

Four paired request families cover compare, check/tell-me-whether, count-without-writing, and existence-without-creation. Their write variants synchronize, edit, save filtered output, or create an empty file. The family yield is 317/320 after deduplication.

Agent audit (for Ivy to confirm): 100 stratified new/changed episodes, seed 61; 100 correct, 0 debatable, 0 incorrect. Per-example verdicts and reasons are committed in `ANSWER-COSINE-DATA-AUDIT.json`. This is not human approval or evidence of perfect labels; the previous agent audit missed a defect. IDs/count were checked against the sample.

## Declared experiment

Job: `reports/factory/pilot-zm8ou4p3`; launched 2026-11-20 10:15 EST. One factory invocation, both MiniCPM5-2B and Qwen3.5-0.8B; constant control versus 3% linear warmup then cosine-to-zero treatment. No other recipe changes.

Before launch: one epoch and 50-minute training boxes for each base/arm. One epoch was chosen to fit all four runs plus evaluation inside the five-hour budget; earlier training-only evidence showed incomplete fit, so this cap is a feasibility compromise, not evidence of convergence. No development score was used to choose the cap.

Seed 42, rank 16/alpha 32, dropout 0, peak LR 2e-4, decision weight 5, max batch 16/token budget 24,576, max length 4,096, gradient checkpointing. RTX 3090 only, PCI-order GPU 0, 20 GiB RAM/1 GiB swap scope. At the interim check, 79 GiB disk remained free and observed scope peak was under 20 GiB. Earlier adapters remain present.

Fit: 800 fixed verified training-row indices sampled with Random(1), shared across bases and arms; expected index digest `04c47d0f4428208a9b467e04220adf1e064806e70f075b348c034f4f8ec5727c`. Both completed control reports match this digest. Treatment verification remains pending. Training decision fit is teacher-forced, not end-to-end behavior.

## Interim control findings (not the scheduler result)

| Base | Revision 5 re-scored | Revision 6 constant | Bare-done question omissions (R5 -> constant) | Input edits (R5 -> constant) | Do-not-modify edits (R5 -> constant) | Unexpected stops (R5 -> constant) |
|---|---:|---:|---:|---:|---:|---:|
| MiniCPM | 43/80 | 20/80 | 4 -> 19 | 1 -> 1 | 1 -> 0 | 0 -> 5 |
| Qwen | 36/80 | 28/80 | 6 -> 0 | 4 -> 0 | 2 -> 0 | 2 -> 1 |

Both control models miss the score targets (48/80 and 40/80). MiniCPM regresses sharply on answering; Qwen eliminates bare-done omissions but still has answered failures requiring semantic review. Neither is a promotion candidate on this evidence.

Each side completed exactly 12 Fast12 + 68 broad tasks, with zero infrastructure failures and preserved originals. Log messages reading FAILED are normal task-miss exits, not missing evaluation results. The revision-5 references use the same evaluation fingerprints/device and matched Q8_0 files.

Counters come from `dev/v2_behaviour.py`: omissions currently mean a question/no-op oracle with no changes/no policy stop, followed by model bare done. Other terminals are recorded separately; a model can fail to deliver an answer without ending bare done. Input edits are final staged changes of existing fixture files that the oracle leaves alone, not all transient write attempts. Unexpected stops count observations, not unique tasks. Wrong answers require per-example semantic confirmation; failed-answer counts are not automatically confirmed false claims.

## MiniCPM cosine and semantic review (Qwen cosine pending)

MiniCPM cosine scores 50/80 versus constant 20/80 and revision 5 at 43/80. Fit on the same
800 rows is 98.125% decision / 98.981% token versus constant 82.5% / 94.885%; weighted loss
0.03169 versus 0.18938. Both use 392 steps and match the fixed probe digest. No category-score
regression against constant, but `move_print_spool_within_build` regresses individually.

All question/no-op tasks receive an answer with MiniCPM cosine, and it edits no existing input
files. However, `summarize_missing_packet_ids` creates `missing.txt` despite the no-output-file
instruction and falsely says every requested ID was received. Therefore its read-only target
is not satisfied; a zero existing-input-edit counter does not establish no writes.

Agent semantic audits (Codex gpt-6.2-sol, medium reasoning, for Ivy to confirm) cover every
nonempty answer plus unintended existing-input edits and unexpected policy stops: 78 control/
reference traces and 27 MiniCPM cosine traces. Every cohort key, copied answer and evidence
quotation was validated against the source packets. Committed per-example files:
`ANSWER-COSINE-CONTROL-SEMANTIC-AUDIT.json` and
`ANSWER-COSINE-MINICPM-COSINE-SEMANTIC-AUDIT.json`.

| Base | Side | Confirmed wrong answers | Supported | Honest incomplete | No answer in audit cohort | Uncertain |
|---|---|---:|---:|---:|---:|---:|
| MiniCPM | revision 5 | 2 | 13 | 2 | 1 | 1 |
| MiniCPM | constant | 0 | 4 | 0 | 1 | 0 |
| MiniCPM | cosine | 6 | 17 | 4 | 0 | 0 |
| Qwen | revision 5 | 9 | 8 | 1 | 2 | 0 |
| Qwen | constant | 16 | 10 | 8 | 0 | 0 |

These are changing semantic-review cohorts, not independent full-suite error rates. Constant
MiniCPM has fewer false answers because it omits nearly all answers, not because it is safer.
Cosine MiniCPM reverses byte-length direction, claims an execute bit that is absent, reports a
final LF where the last byte is `Z`, supplies the wrong filter order/format, substitutes directory
names for manifest release labels, and falsely reports no missing packet IDs. Four control/
reference answers passed graders despite false details; graders remain frozen, and those false
claims are explicitly reported rather than retroactively changing scores.

Metric clarification: earlier interim text used "omissions" to mean only bare `done`. Across
all terminals the missing-answer totals are MiniCPM revision 5 **5**, constant **23**, cosine
**0**; Qwen revision 5 **7**, constant **0**. The extra omissions are budget/invalid stops.
`dev/v2_behaviour.py` now reports these separately and counts any staged read-only effect,
including newly created output files, without changing evaluation grading.

## Remaining acceptance work

Finish cosine evaluation without new recipes; verify identical fit rows/settings, model/evaluation fingerprints/device, report all category regressions, review semantic answers and policy stops for every side, and publish a final controlled conclusion with updated STATUS.md. Held-out remains reserved for an eventual shipping candidate.
