# Roster batch 7: archives, organise, recovery (2026-11-24)

**Why:** the 80-task roster had 0 archive tasks, 9 organise and 2 recovery. That made those categories' pass rates noise. Two seeds of r13 also differed by more than r13's distance to the bar, so the roster could not rank candidates. Ivy picked three groups from the proposed 150: **archives (A), organise (F), recovery (D)**.

**What was added:** 26 tasks, taking the roster from 80 to **106**.

| Module | Tasks | What they cover |
|---|---|---|
| `dev/dev_archives.py` | 10 | pack with an exclusion, list contents, extract one member, unpack into a new folder, unpack without overwriting, gzip keeping the original, archive selected files, archive then delete the folder (approval), compare a backup to a folder, add a file to an existing tar |
| `dev/dev_organise.py` | 8 | sort by type, file by month in the name, zero-pad names, flatten, merge two folders with prefixes, rename a README (approval), move by a content marker, dashes for spaces |
| `dev/dev_recovery.py` | 8 | named file one folder down, column-aligned edit, destination folder missing, "notes" is a folder, case mismatch in a search, one of three files elsewhere, a Windows path literal, whitespace-only lines |

**Calibration:** every task passes its scripted solution and fails an immediate "done", in the real sandbox (`tests/sandbox/test_dev_{archives,organise,recovery}_live.py`, and under interface v5). The split audit is clean against held-out v2 and v3.

## Grading decisions

- **Archives are graded on contents.** `fast12_runner.describe_archive` reduces a staged tar, tar.gz or gzip file to its sorted members with content hashes, because archive bytes carry timestamps.
  - **One leniency, decided after the first run:** "Pack the old-logs/ folder" may fairly keep or drop the folder name inside the archive. All three models dropped it (`tar -C old-logs .`).
  - The grader now treats a single top folder shared by every member as optional. Mixed layouts still fail.
- **Questions are asked.** On the first run the four new questions were issued as `do`, because they were missing from `dev/oracles_v3.py`. From interface v3 a question is issued with `ask`, and its answer is the output of the last command.
  - Those results were discarded. The tasks are now registered, and a unit test fails if a future question is not.
- **Recovery traps are never required.** The trap is a path one folder off, a literal that differs, or a missing folder. A careful model can avoid it, and only the end state and the answer are graded. A file with the exact requested name found elsewhere is used, never asked about; that matches the focus "named file missing" convention.

## First results (RTX 3090, interface v5, zero infrastructure failures)

| | old 80 | new 26 | archives /10 | organise /8 | recovery /8 | **total /106** |
|---|---|---|---|---|---|---|
| 2.0 | 54 | 10 | 4 | 1 | 5 | **64** |
| r13 s42 | 53 | 15 | 5 | 5 | 5 | **68** |
| r13 s43 | 48 | 11 | 4 | 2 | 5 | **59** |

The old 80 reproduced exactly, at 54, 53 and 48.

**Runs:**
- 2.0: `fast12-fr92t_pi`, `broad-ye96xwno`
- r13 s42: `fast12-d890agok`, `broad-bh8znfpk`
- r13 s43: `fast12-pzxkqu3m`, `broad-vfwgy527`

### What the new tasks show

- **Every model fails 8 of the 26.** I read every failed trace; all are genuine mistakes, not grader artefacts:
  - `diff` run against a `.tar` file instead of its contents;
  - `cat` appended into a tar;
  - extracting into a new folder when told "here";
  - `cp` used where a move was asked;
  - a case-sensitive search that finds nothing, then a stop with no answer;
  - the step budget spent looking without ever answering.
- **Archives are the weakest category (4–5/10 for every model).** Most errors are wrong tar idioms, which makes archives a candidate for a typed archive tool. That is the factory's premise: when a capability fails consistently, consider the interface.
- **Organise separates the models most:**
  - 2.0 scores 1/8; r13 seeds score 5/8 and 2/8.
  - 2.0's misses include moving every ticket instead of the closed ones, and ignoring the "two digits" rule.
- **Recovery is flat at 5/8 for all three.**

### What it means for promotion

- **The bar on 106 tasks is 2.0's 64.**
  - r13 s42 clears it (68), the first candidate to beat 2.0 on the development roster.
  - r13 s43 does not (59).
- **The seed spread grew from 5 tasks to 9.** The new tasks do not shrink it: the two seeds really are different models.
- **The promotion gate (at least the bar at both seeds) is still not met.** Held-out v3 stays unused.
