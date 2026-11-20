# Answer-complete/read-only data and constant vs cosine: controlled result

Sprint of 2026-11-20 (about 09:50-12:55 EST), finished at the recipe limit: two new recipes per
base. **No candidate is promoted and nothing ran on held-out.** Development failures shaped the
revision-6 families, so every development score here is optimistic, not a generalisation estimate.

## Verdict

- **Cosine versus constant (the controlled factor): positive on both bases.** On identical rows,
  seed, steps and fit probe, cosine fits better (MiniCPM decision fit 82.5% -> 98.1%, Qwen
  88.8% -> 96.8%) and scores higher (MiniCPM 20 -> 50/80, Qwen 28 -> 34/80).
- **MiniCPM cosine meets** the score target (50/80 >= 48), zero missing answers, no existing-input
  edits, better fit and no category regression against its control. It does **not** meet the
  read-only intent: in one "do not create" task it wrote `missing.txt`. The semantic audit also
  confirms 6 wrong answers. It loses 7 tasks the revision-5 adapter passed.
- **Qwen cosine misses**: 34/80 < 40, 3 missing answers, organise regresses 6 -> 5 against its
  control, and it writes in one "do not modify" task (two `-trim` copies). The audit confirms 13
  wrong answers, one of them debatable.
- **The data fix alone, under the constant schedule, is negative.** Re-scored in the same job,
  revision 5 beats revision 6 constant on both bases (MiniCPM 43 vs 20, Qwen 36 vs 28). Constant
  MiniCPM stops answering: 23 missing answers, 19 of them bare `done`, although answered endings
  are 42% of revision-6 `done` targets. MiniCPM cosine's gain over revision 5 (43 -> 50)
  therefore combines two factors (data and schedule) and is not attributed to either.
- **One seed per arm.** Run-to-run variance is unmeasured, and the size of the constant-MiniCPM
  collapse makes this the main caveat. A rerun with a second seed would settle whether constant
  revision 6 is unstable or just unlucky.

## Targets

| Target | MiniCPM cosine | Qwen cosine |
|---|---|---|
| Zero missing answers | met (0) | missed (3: two bare `done`, one budget) |
| Input edits <= revision 5 (1 / 4) | met (0) | met (2) |
| No input edits in do-not-modify tasks | met for existing inputs; but created a forbidden output file | met for existing inputs; but created two files in a do-not-modify task |
| Score (48 / 40) | met (50) | missed (34) |
| Cosine fit >= constant | met | met |
| No category regression against control | met | missed (organise 6 -> 5) |

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

The job is `reports/factory/pilot-zm8ou4p3`, launched at 10:15 EST as one factory command:
`--arm control=reports/corpus/v2-r6@constant --arm treatment=reports/corpus/v2-r6@cosine`, both
bases, `--max-epochs 1`, 50-minute training boxes, with the revision-5 v2 adapters re-scored in
the control arm (`--previous ...@2`).

I declared the cap before launch from training-only evidence and the GPU budget. The earlier
revision-5 run showed incomplete fit after one epoch, but four two-epoch runs plus eight scored
sides could not fit in five hours. One epoch is therefore a feasibility choice, not convergence.
Every run stopped on `max_epochs` (392 of 392 planned steps), well inside the time box.

Settings identical in both arms: seed 42, rank 16 / alpha 32, dropout 0, peak LR 2e-4, decision
weight 5, max batch 16 with a 24,576-token budget, max length 4,096, gradient checkpointing, the
same revision-6 training file (sha256 `06380bec...`), RTX 3090 (PCI GPU 0), and a 20 GiB / 1 GiB
swap scope. The treatment warms up linearly over 3% of steps, then decays by cosine to zero.

Fit is measured on the same 800 verified training rows in all four runs (index digest
`04c47d0f...`, checked in every report and recomputed independently). It is teacher-forced, not
end-to-end behaviour.

| Base | Schedule | Steps | Decision fit | Token fit | Weighted loss | Final LR |
|---|---|---:|---:|---:|---:|---:|
| minicpm | constant | 392 | 82.50% | 94.89% | 0.1894 | 2.0e-04 |
| minicpm | cosine | 392 | 98.12% | 98.98% | 0.0317 | 3.4e-09 |
| qwen08 | constant | 392 | 88.75% | 97.58% | 0.1290 | 2.0e-04 |
| qwen08 | cosine | 392 | 96.75% | 98.64% | 0.0535 | 3.4e-09 |

## Verification

I re-verified these independently from the run directories with a separate script; the output is
`reports/factory/pilot-zm8ou4p3/verification.json`.

- **Trainings:** all 4 reports; the arm pairs differ only in `lr_schedule`.
- **Scored sides:** all 10, each with exactly the fixed 80-task roster (12 Fast12 + 68 broad).
- **Artifacts and fingerprints:**
  - each of the 10 Q8_0 GGUF hashes matches its identity file;
  - one evaluation fingerprint per suite, matching the current source and `llama-server` bytes
    (`fast12 62f5a607...`, `broad 479eb67a...`);
  - interface v2, golden prompt unchanged.
- **Device:** all runs on the RTX 3090.
- **Run hygiene:** zero infrastructure failures, all fixture originals preserved. Untuned scores
  were reused from the revision-5 job after the same identity check.

The log's "FAILED" lines are normal task-miss exits.

## Development scores per category

| Category | n | MiniCPM R5 | MiniCPM constant | MiniCPM cosine | Qwen R5 | Qwen constant | Qwen cosine |
|---|---:|---:|---:|---:|---:|---:|---:|
| delete | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| edit | 32 | 12 | 8 | 15 | 11 | 7 | 10 |
| explicit | 9 | 7 | 4 | 7 | 7 | 5 | 5 |
| inspect | 12 | 8 | 0 | 9 | 4 | 5 | 5 |
| organise | 9 | 6 | 4 | 7 | 6 | 6 | 5 |
| permissions | 4 | 2 | 1 | 4 | 2 | 1 | 2 |
| read-only | 7 | 4 | 0 | 4 | 3 | 1 | 3 |
| recovery | 2 | 1 | 1 | 2 | 1 | 1 | 2 |
| scripts | 3 | 1 | 0 | 0 | 0 | 0 | 0 |

Cosine against constant:
- MiniCPM gains 31 tasks and loses move_print_spool_within_build.
- Qwen gains 13 and loses 7: combine_lectures_b_then_a, copy_review_folder_structure, latest_iso_timestamp, leave_matching_output_style, merge_pages_in_named_order, preserve_dotfile_during_backup, summarize_missing_packet_ids.

The full table with confidence intervals and gate flags is in `reports/factory/pilot-zm8ou4p3/arms-report.md`.

## Behaviour from the traces

| Base | Side | Score | Missing answers (all terminals) | of which bare done | Existing-input edits | ...in do-not-modify tasks | Any write on answer-only tasks | ...in do-not-modify tasks | Unexpected policy stops | Confirmed wrong answers (agent audit) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MiniCPM | revision 5 | 43/80 | 5 | 4 | 1 | 1 | 2 | 1 | 0 | 2 |
| MiniCPM | R6 constant | 20/80 | 23 | 19 | 1 | 0 | 1 | 1 | 5 | 0 |
| MiniCPM | R6 cosine | 50/80 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 6 |
| Qwen | revision 5 | 36/80 | 7 | 6 | 4 | 2 | 4 | 3 | 2 | 9 |
| Qwen | R6 constant | 28/80 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 16 (1 debatable) |
| Qwen | R6 cosine | 34/80 | 3 | 2 | 2 | 0 | 3 | 1 | 0 | 13 (1 debatable) |

How the columns are counted:
- **Missing answers** cover every question/no-op task, whatever the terminal: bare `done`, budget
  or invalid stops.
- **Existing-input edits** are final staged changes to fixture files that the scripted solution
  leaves alone.
- **Any write on answer-only tasks** also counts newly created files, so it catches writes that
  the input-edit count misses.
- **Unexpected policy stops** are pending or rejected observations in tasks whose scripted
  solution has none.

These counts come from `dev/v2_behaviour.py` and change no grading.

Confirmed wrong answers come from agent semantic audits for Ivy to confirm (Codex `gpt-6.2-sol`,
medium reasoning). They cover every non-empty answer plus every unexpected effect: 78 control and
revision-5 traces, 27 MiniCPM-cosine traces, 29 Qwen-cosine traces, plus a 2-item parent
supplement for read-only writes outside the first cohort. I validated every cohort key, copied
answer and evidence quote against the raw traces in code.

The counts come from changing cohorts, not full-suite error rates. Constant MiniCPM has 0 wrong
answers because it almost never answers. The two debatable Qwen items answer `utf8_line_count` with the
correct number (3) but describe the criterion as "no spaces"; the request asked for non-empty lines.

Several answers that **passed** the frozen graders are semantically false, for example a reversed
byte-length direction or reversed set membership. The graders are unchanged; these answers are
reported here and in the audit files rather than rescored. Representative cosine errors:
- MiniCPM: a final LF where the last byte is `Z`; an execute bit that is absent; "no missing
  packets" when `q709` and `q101` are missing.
- Qwen: finch instead of sparrow as latest; a net sum of 0 instead of 11; claims a version bump
  and a copy that never happened.

Per-example evidence:
- `ANSWER-COSINE-CONTROL-SEMANTIC-AUDIT.json`;
- `ANSWER-COSINE-MINICPM-COSINE-SEMANTIC-AUDIT.json`;
- `ANSWER-COSINE-QWEN-COSINE-SEMANTIC-AUDIT.json`;
- `ANSWER-COSINE-READONLY-SUPPLEMENT.json`.

## What this does and does not show

- **Shown:**
  - with data and every other setting fixed, warmup plus cosine to zero gives better training
    fit and better development behaviour than a constant rate, on both bases;
  - the fit gain explains the direction of the score gain, so the aggregate gain is not
    unexplained;
  - cosine also removes MiniCPM's bare-`done` collapse.
- **Not shown:**
  - that revision 6 is better data than revision 5: under the constant schedule it is worse;
  - that the cosine gain is larger than seed noise;
  - anything about held-out generalisation.
- **Still open:**
  - wrong answers remain the main failure mode (6 and 13 confirmed);
  - read-only writes are rarer but not gone;
  - the full 18-case safety acceptance is still blocked by missing `rsync`;
  - the human review of the data audit is still open.

## Next decisions for Ivy

1. Whether to run a second seed of revision-6 constant and cosine (two more recipes per base)
   before trusting the schedule effect.
2. Whether MiniCPM cosine should become the shipping candidate for the one-time held-out run.
   I recommend not yet: it makes 6 confirmed wrong answers and a forbidden write, and the seed
   variance is unknown.
3. Whether to approve a harness or grader change for false-but-passing answers. Graders and the
   bare-`done` rule are untouched; that change needs your approval.

## Resources

- **Disk:** 64 GiB free at the end.
- **Memory:** the job scope peaked at 15.5 GB under its 20 GiB limit.
- **Adapters:** all earlier adapters kept; the deleted superseded merged checkpoints and GGUFs
  are listed in `reports/factory/artifact-cleanup-2026-11-20.json`.
