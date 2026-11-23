# Focus round 11: where 2.0's weak spots come from (2026-11-23)

**Question:** 2.0's model card names five weak spots: quoting a value, counting lines, creating an exact file, noticing that a named file is missing, and appending to a file without a final newline. For each one, is it a training gap or a burden the interface could remove?

**Answer:**

| Weak spot | Cause | Fix |
|---|---|---|
| Missing final newline | Interface: `fs.read` hides it | v5 marker |
| Named file missing | Mostly data, plus a misleading error | v5 error text, then r11 examples |
| Counting | Data: imprecise commands | r11 examples |
| Blank lines in a created file | Interface: invisible whitespace | v5 marker |
| Quoting, section-scoped | Shell quoting and turn budget | Watch |

These are development fixtures. No held-out suite was read or run: v2's traces are spent, and v3 is untouched.

## Setup

**Fixtures:** `dev/focus_r11.py` has 25 new tasks in five groups of five.
- They were written from the weakness names only.
- They were audited against held-out v1, v2 and v3, the 80-task roster and the v4 focus set (`tests/unit/test_focus_r11.py`).
- Controls (`tests/sandbox/test_focus_r11_live.py`): on both interface v3 and v4, the oracle passes 25/25 and an immediate `done` passes 0/25.

**Run:** `reports/factory/focus-r11-20261123-1238`, on the RTX 3090, using the same managed server and controls as every development suite. There were zero infrastructure failures.

| Group | 2.0 (r10 s42, v4) | r10 s43 (v4) | 1.0 (r8 s43, v3) | stock (v4) |
|---|---|---|---|---|
| quote a value | 4/5 | 5/5 | 4/5 | 1/5 |
| count lines | 3/5 | 4/5 | 4/5 | 1/5 |
| create exact file | 4/5 | 5/5 | 4/5 | 0/5 |
| named file missing | 4/5 | 1/5 | 1/5 | 1/5 |
| append, no final newline | **0/5** | **0/5** | **0/5** | 0/5 |
| **total** | **15/25** | **15/25** | **13/25** | **3/25** |

## First consequential errors

1. **Missing final newline (0/20 across the tuned runs). The interface hides it.**
   - **2.0 on `names.txt` (`alpha\nbeta`):** `fs.read` showed `<<<` / `alpha` / `beta` / `>>>`, which is identical to a file that ends in a newline. The model appended with `printf '%s\n' gamma`, leaving `alpha\nbetagamma\n`, and said done without reading the file again.
   - **r10 s43 on `limits.conf`:** it did read again and saw `disk=50Gcpu=4`. It then repeated the same append twice more.
   - **The cause is in what the model is shown.** A training example cannot teach the model to see a byte the observation removes.
   - **Fix (interface):** mark a missing final newline in read output, as `diff` does with `\ No newline at end of file`. Then add examples that recover from a joined line.

2. **Named file missing (2.0 4/5; r10 s43, r8 1/5). The model searches correctly, then substitutes a file.**
   - In all three r10 s43 misses, the model tried `fs.read`, then `fs.find` (no output), then `fs.list`. Each time it then edited a look-alike file: `settings.ini` instead of `settings.local.ini`, and `restore.sh` instead of `backup.sh`. Once, it copied `expenses-2026.txt` to create `expenses-2027.txt`.
   - **Part interface.** For a path that does not exist, `fs.read` and `fs.edit` say `Expected a regular file`. That wording reads like a type problem, not "this file does not exist".
   - **Fix:** in v5, say `no such file: settings.local.ini`. Then add revision-11 examples that end in `ask` once a listing confirms the file is absent.
   - The seeds disagree (4/5 against 1/5), so this decision is unstable. It is not absent.

3. **Counting (3–4/5). Data: the right file, an imprecise command.**
   - `grep -c -- 'no'` counts `nope` and `not sure` too, giving 5 instead of 3. Exact-line counts need `-x`.
   - `wc -l < members.csv` includes the header, giving 4 instead of 3.
   - The answer is quoted faithfully; the command is wrong. This is a data gap: `grep -cx`, header-excluding counts, and word-boundary patterns.

4. **Create exact file (4–5/5). A blank line was written as three spaces.**
   - 2.0 wrote `'   '` for the empty line. The check read-back showed what looked like an empty line, so it could not see the mistake.
   - **This is the same kind of interface defect as the missing newline:** whitespace-only content is invisible.
   - **Fix:** v5 could mark lines that contain only spaces, or trailing whitespace. It is a single case, so this is low priority.

5. **Quoting (4–5/5). One run ran out of turns.**
   - On the section-scoped value, 2.0 needed six steps. It fought shell escaping and finally printed `volume=55` with `awk`, but had no turn left to finish.
   - **Fix:** none needed yet. Watch whether this recurs.

## Proposal (weighed by effort)

| Step | What | Effort | Expected effect |
|---|---|---|---|
| **Interface v5** | Read output marks `(no newline at end of file)`. Missing paths say `no such file: PATH`. Optionally mark whitespace-only lines. New golden prompt; v4 kept reproducible; the app records the interface per model as in 2.0. | ~half a day of code and tests | Makes the no-EOL case solvable; clarifies "missing" |
| **Interface-only check** | Run 2.0 unchanged on v5 against this focus set and the 80-task roster | ~30 min of GPU | Separates what the interface alone fixes from what needs data |
| **Corpus r11** | r10 re-recorded on v5, plus four families: append after a no-EOL marker (and recovery from a joined line), ask after a confirmed-absent listing, exact and header-excluding counts, exact blank lines in created files. Rebuild the dedup and gate against focus-r11 and held-out v3. | ~half a day | Teaches the remaining skills |
| **Train and assess** | Two seeds, same cosine recipe; roster and focus at each seed | ~2 h of GPU | Development evidence |
| **Promotion** | Held-out v3 once on the chosen candidate, and once on 2.0 | ~30 min of GPU | Unbiased same-suite comparison |
