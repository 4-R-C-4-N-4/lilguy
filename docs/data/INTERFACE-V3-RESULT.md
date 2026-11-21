# Interface v3: first training result

Status: declared before launch (2026-11-20, ~22:45 EST). The results section is filled in after
the jobs finish. Development failures shaped both v3 and revision 7, so every development score
here is optimistic. Nothing runs on held-out: it has not been recalibrated for v3 yet, and is
reserved for a shipping candidate.

## What changed (interface v3, [plan](../plan/INTERFACE-V3.md))

- **Question mode.** lilguy rejects and rolls back any write. The model is told the mode
  (`Question:` or `Request:`) instead of guessing it from the wording.
- **`done` takes no text.** The answer to a question is the output of the model's last command,
  quoted from what ran. A literal `echo`, or a dump of a whole multi-line input file, counts as
  no answer.
- **Evaluation.**
  - The same fixed 80 development tasks; 21 of them run as questions.
  - Questions are graded with the existing graders on the quoted output.
  - 18 questions received v3 oracles that end on an answering command.
  - All 80 oracles pass and all 80 null controls fail
    (`tests/sandbox/test_dev_v3_live.py`).

## Data: corpus revision 7 (`reports/corpus/v3-r7`)

Revision 7 contains the revision-6 episodes, re-expressed for v3; nothing new is generated:

- every `done` is bare;
- answer-only episodes become questions (`ask` mode), except four "nothing needed doing" change
  families, which stay `do`;
- 324 answer episodes whose last step was a full read or prose now end on a command that prints
  the answer (for example `grep '^key=' file`, `cmp -s a b && echo identical || echo differ`).

Every episode is replayed in the real sandbox in its own mode, with the same dedup and split gate.
A question episode that writes would be rejected and fail replay. Yield is reported below.

Offline estimate, for orientation only: regrading the existing v2 cosine traces under v3 quoting,
only 5–8 of the 23 answer tasks would pass, because v2 models do not end on an answering command.
v3 therefore needs v3 training; v2 adapters are not expected to do well under v3.

### Amendment before first use (2026-11-20 ~23:05 EST)

The first revision-7 build went to a 100-episode agent audit (Codex `gpt-6.2-sol`, for Ivy to
confirm): 95 correct, 1 debatable, 4 incorrect. The 4 incorrect episodes left the answer implicit.
The last output was a sorted size list ending in `total`, a file list the reader had to count, an
`od` byte dump, or a matching line instead of yes/no.

Those are family-wide patterns, so I stopped job `pilot-s8njviu0` 10 minutes into MiniCPM
training, before any score existed. I then amended revision 7 (`4e2efa1`) so these families
compute the answer outright:

- `wc -c dir/* | grep -v ' total$' | sort -n | tail -n 1`;
- `find dir -type f -name '*.csv' | wc -l`;
- `... | sort -u | wc -l`;
- a yes/no test of the last byte;
- `grep -n '^W' f && echo yes || echo 'no line starts with W'`;
- one `&& echo same || echo differ` idiom for both outcomes of `diff` and `cmp`.

The aborted job's artifacts are not used.

**Re-audit of the rebuilt corpus.** A fresh sample of 100 episodes (seed 72; 72 change requests,
28 questions) gave 95 correct, 4 debatable and 1 incorrect; the per-episode verdicts are in
`INTERFACE-V3-DATA-AUDIT.json`. Every remaining finding is again an answer that is true but
implicit or loosely conditioned:

- *incorrect:* `idempotent_edit` "tell me whether you changed it" quotes `theme=sage` without
  saying "unchanged";
- *debatable:*
  - `ro_check` shows the value without a yes/no;
  - `ask_collision` says `identical` without "not copied";
  - the `recover_absent` fallback tests for any `.bak` file;
  - the empty-substitution last-byte test would say "yes" for an empty file.

None of these is wrong on its fixture, and training had started, so this run proceeds on this
data. The patterns are queued for the next revision. This is an agent audit, not a human review.

## Declared runs (fixed before launch)

- **Recipe:** unchanged from the adopted default — 3% warmup then cosine to zero, one epoch, a
  50-minute box per base, seed 42, rank 16 / alpha 32, dropout 0, decision weight 5, the same
  batching. The epoch cap and box are the ones already declared for revision 6 (from training fit
  and GPU budget), and revision 7 has fewer rows, so it fits.
- **Fixed probe:** the same 800-row fit probe (`Random(1)` indices over revision-7 rows).
- **Job 1 (seed 42), both bases in one factory command:**
  - untuned models scored under v3;
  - the seed-43 v2 cosine adapters re-scored in the same job under v2, with the same code, roster
    and GPU. This is a cross-version reference, not a matched comparison.
- **Job 2 (seed 43):** the same recipe again, to measure seed spread, as for revision 6.
- **Hardware:** RTX 3090 only, 20 GiB memory scope, keeping 30 GiB of disk free. Merged bf16
  checkpoints are deleted after their GGUFs are exported and hashed.

## Targets (declared)

- **Score:**
  - MiniCPM: at least 48/80 under v3 on both seeds;
  - Qwen: at least 40/80.
- **Questions:**
  - zero writes staged during questions (by construction; attempted writes are counted);
  - zero literal-echo answers;
  - quoted answers that fail grading are reported per task, with the trace.
- **Change tasks:** no category regression against the v2 cosine reference in the categories with
  no question tasks (edit, organise, delete, permissions, scripts, recovery, explicit). This is
  cross-version, so it is reported as a reference, not a gate.
- **Honesty:** report regressions and missed targets. A negative result is acceptable.


## Result 1: revision 7, seed 42 (`reports/factory/pilot-i99_qvnk`)

Verified for every side:
- matched Q8_0 hashes in the identity files;
- the RTX 3090, with zero infrastructure failures and originals preserved;
- v3 evaluation fingerprint `fast12 569d124c...`, `broad 3862acf9...`;
- v2 references scored with the same code under v2 (`1d7ec067...`, `7466398d...`).

Training: 391 steps, stopped by the epoch cap. Fit-probe digest `da7e5bbe...`; this is a new probe
because revision 7 has different rows.

| Base | Untuned v3 | v3 adapter | v2 cosine reference (seed 43, own interface) | Decision fit |
|---|---:|---:|---:|---:|
| MiniCPM | 18/80 | 46/80 | 53/80 | 91.3% |
| Qwen | 3/80 | 34/80 | 36/80 | 92.8% |

| Category (n) | MiniCPM v3 | MiniCPM v2 ref | Qwen v3 | Qwen v2 ref |
|---|---:|---:|---:|---:|
| delete (2) | 2 | 2 | 2 | 2 |
| edit (32) | 15 | 14 | 11 | 12 |
| explicit (9) | 7 | 9 | 8 | 6 |
| inspect (12) | 7 | 10 | 3 | 5 |
| organise (9) | 8 | 9 | 5 | 6 |
| permissions (4) | 3 | 3 | 2 | 2 |
| read-only (7) | 2 | 4 | 2 | 1 |
| recovery (2) | 1 | 2 | 1 | 2 |
| scripts (3) | 1 | 0 | 0 | 0 |

Behaviour, from the traces:
- **No writes during questions.** Neither adapter staged anything in a question, and neither
  echoed literal text as an answer.
- **Change tasks** are about level with the v2 reference.
- **Questions are worse.** MiniCPM passes 10 of 23 answer tasks, Qwen 5. Failure types for
  MiniCPM / Qwen:
  - the last output did not contain the answer: 8 / 12;
  - no output: 1 / 5;
  - a whole-file dump: 2 / 0;
  - ran out of turns: 2 / 0;
  - question mode refused a write, which then ended the episode: 0 / 1.

**Diagnosis.** The traces show both adapters guessing the format before looking. They grep
`^theme=` in a `theme: juniper` file, grep `^stockroom=` for `stockroom_colour`, or cut the
timestamps and drop the station name. Revision 7 removed the read before the narrowing grep and
used only `key=value` files, so the training data taught the guess. The v3 harness behaved as
designed; the data is the defect.

**Not met:**
- MiniCPM 46 < 48;
- Qwen 34 < 40;
- question categories regress against the v2 reference.

This is a single seed. Following the calibration rule (assess with specific tasks, refine where
they fail), the planned seed-43 replication of revision 7 is replaced by the controlled data
comparison below.

## Declared (2026-11-21 ~00:05 EST): revision 8 versus revision 7

Revision 8 (`0445f04`, `reports/corpus/v3-r8`) changes only the answer-only episodes of a few
families:
- **Look before narrowing.** Keep the `fs.read` before the narrowing grep.
- **Varied setting format.** Each config file uses `k=v`, `k: v` or `k = v`, chosen by a hash of
  the episode id, and the grep matches the format seen.
- **Stated verdicts:**
  - "already ...; unchanged";
  - `yes, k=v` / `no, k=actual`;
  - "identical; ... not copied";
  - an empty-file-safe last-byte test;
  - an exact-name check for a missing `.bak`.

Yield: 2,164/2,164 replayed, split gate passed, 6,465 rows. That is +220 rows (+3.5% exposure)
from the kept reads.

Runs, both bases, same recipe (cosine, one epoch, 50-minute box), evaluation code unchanged:
- **A:** revision 8 at seed 42, compared with Result 1 (revision 7, seed 42);
- **B:** one factory command, `control=v3-r7@cosine`, `treatment=v3-r8@cosine`, at seed 43.

Revision 8 counts as better for a base only if it beats revision 7 on answer tasks on both seeds
without losing change-task categories. Targets as declared above.
