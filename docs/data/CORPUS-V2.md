# Corpus v2 data card

Training data for the lilguy small model, in interface v1. Built by `dev/v2_corpus.py`.
Built corpora are local and not committed: `reports/corpus/v2` (revision 1, used by pilot round 1)
and `reports/corpus/v2-r2` (revision 2, used by pilot round 2).

```bash
.venv/bin/python -m dev.v2_corpus reports/corpus/v2-r2 --revision 2 --workers 12   # ~3.5 min
.venv/bin/python -c "from dev import v2_corpus as v; print(len(v.verified_rows('reports/corpus/v2-r2')))"
```

## What an example is

An example is an instance of one of 26 generator groups (36 in revision 2), expanding to 52 / 68
emitted family labels. [Per-family and category counts](CORPUS-V2-COUNTS.md) distinguish those
counts. Each group has parameterized fixture builders and several request phrasings. An example consists of:

- an original fixture workspace;
- a request;
- a scripted oracle in canonical v1 action form;
- the exact expected staged effects, final policy (`ok`, `pending` or `rejected`) and error turns;
- the facts the final answer must state.

Every fact must also appear in the stdout of a successful observation. The `stdout (N lines)`
header does not count as evidence.

## Pipeline and yield

| Stage | Revision 1 | Revision 2 |
|---|---:|---:|
| Generated | 1,379 | 1,867 |
| Exact and near-duplicate removal (within the corpus and against all 80 development tasks) | 1,342 | 1,799 |
| Held-out split gate (`eval_gate.verify` against the frozen pin `f9d408a4…`) | 1,342 (passed) | 1,799 (passed) |
| Gold run meets every declared expectation on a fresh guarded fixture | 1,342 | 1,799 |
| Independent replay produces an identical record on a second fresh fixture | 1,342 | 1,799 |
| **Episodes** | **1,342** | **1,799** |
| Next-action training rows | 3,957 | 5,266 |

The gold stage did reject examples during development of the generator. Those rejections were
real mismatches: a fact stated in the answer but not present in stdout, an answer that omitted a
fact, and a staged change visible only on the `changes:` line. The families were fixed rather than
the checks relaxed. In the final builds, no example failed the gold run or the replay.

Some deliberate slips stay in the history, so that the recovery after them is real, but they are
never training targets (`train_skip`):

- copying into a missing directory before looking;
- `rm` of a file that does not exist, including the first `rm` in a near-miss recovery;
- the `fs.edit` attempted after two identical matches were already visible;
- in revision 2, the first `cut` that kept a CSV header, which the episode then checks and redoes.

This is why there are fewer rows than assistant turns.

## Composition (revision 2)

- **Categories:** ask 496, edit 393, inspect 251, recovery 180, organise 142, delete 102,
  permissions 85, read-only 87, archives 45, scripts 18.
- **Terminals:** done 1,512, ask 287. **Final policy:** ok 1,613, pending 146, rejected 40.
- **tldr-attributed examples:** 810.

Action-row balance matters separately from episode categories: revision 2 has 287 `ask` targets
out of 5,266 rows (5.45%), despite 496 episodes being categorized as clarification/selection
tasks. Revision 1 has 212/3,957 (5.36%). Aggregate teacher-forced accuracy is not evidence that
the model learned to ask; report decision fit by class before choosing more training time.

Revision 1 (1,342 episodes):

- **Categories:** ask 325, edit 273, recovery 180, inspect 144, delete 102, organise 102,
  permissions 85, read-only 60, archives 45, scripts 26.
- **Behaviours:**
  - ask when ambiguous 140, ask for a missing detail 22, act when unambiguous 163;
  - recover after an error 140, honest failure 40;
  - stop on `pending` 146, stop on `rejected` 40;
  - honest `done` 44, verify before `done` 209, look then act 179, factual answer 219.
- **Terminals:** done 1,130, ask 212.
- **Target action kinds (rows):** tool 1,847, run 768, done 1,130, ask 212.

### Contrast pairs

The clarification families are contrast pairs: the same template wording, and only the workspace
decides whether to ask or act. Within a corpus the request texts are distinct, because the split
gate refuses duplicate requests.

| Family | Ask when | Act when |
|---|---|---|
| `ask_target` | two configs match the named target | one config matches |
| `ask_notes` | two notes files match | one notes file |
| `ask_value` | two equally current settings files disagree | one settings file |
| `ask_content` | both candidate files contain the key | only one does |
| `ask_order` | no recorded order | ORDER.txt records it |
| `ask_conflict` (rev 2) | two style guides disagree | one guide sets the rule |
| `ask_collision` (rev 2) | the target exists with different content | the target is free; if it is identical, report and do nothing |
| `ask_after_read` (rev 2) | the file read shows two approved entries | only one entry is approved |

### Revision 2

Revision 2 changes and adds the following. The first part was designed from the stock-model
failure classification and the self-review below. The last three families were added after
classifying the round-1 tuned failures. On both bases, the most common failures were wrong text
transforms on edits, missed clarifications, and answers stated without evidence.

- **Fixes:**
  - `ask_value` no longer pairs `settings.ini` with `settings.backup.ini`; asking there was debatable.
  - `ask_notes` no longer pairs a file with an `old/` copy.
  - Script names now match what the script does.
  - The "into a outpost folder" wording is fixed.
- **New families:**
  - `ask_conflict` and `ask_collision`;
  - `idempotent_edit` (leave a value alone and say so);
  - `conditional_copy` (act only on an exact marker line, and report a non-match);
  - `awk_sum`, `set_diff` (`grep -vxF -f`) and `text_*` (CRLF to LF, `sed -n` ranges, distinct
    values, yes/no "starts with" questions);
  - added after round 1: `ask_after_read`; `inspect_misc` (`cmp`, non-blank line counts, last
    byte, dotfiles); and `verify_fix` (read back the output, notice the kept header, redo it).

## Sources and licences

- **Original fixtures.** Requests, file contents, answers and the multi-turn structure are written
  for this corpus. No personal shell history is used.
- **tldr-pages.** Pinned revision `2d64595223d89a23d249fed57d8f401d95f8ccf9`, CC BY 4.0, credited
  to the tldr-pages team and contributors. The shell usage in 810 revision-2 examples (568 in
  revision 1) is adapted from the `common` pages: sort, uniq, head, tail, cut, tr, paste, grep,
  sed, wc, find, cp, mv, rm, chmod, tar, printf, awk, cmp and od. Each example's `source` field names its
  page and revision. The audit marks tldr-pages "Conditional; recommended starting" (see
  [LICENCE-AUDIT.md](LICENCE-AUDIT.md)).
- **Unresolved sources.** Nothing from a source the audit marks "Unresolved" is used.

## Audit

- **Agent audit, for Ivy to confirm.** A subagent read a stratified 200-episode sample of
  revision 1 (`reports/corpus/v2/audit-sample.md`, seed 7) and judged all 200 correct
  (`audit-verdicts.json`). It gave no notes on any item.
- **Author's own review.** I reviewed one episode per family and judged two families' ask cases
  debatable. Both are fixed in revision 2:
  - `ask_value`: a backup twin is arguably not a real ambiguity.
  - `ask_notes`: a copy under `old/` is arguably not one either.

  These two families made up 4 of the 200 audited items, so the subagent's 100% overstates
  correctness. A fair agent figure is 196/200 (98%) on revision 1. A human audit remains open.

## Limits

- The data is template-generated, with a small artificial vocabulary (places, birds, plants).
  Requests are short and explicit.
- It contains no network tasks, no long-running programs and no interactive tools.
- Archive families only read or extract deterministic ustar fixtures. Creating archives is
  excluded because tar headers embed mtimes.
- The families were designed with the development failure modes in mind, though not by copying
  development tasks. Development scores after training therefore overstate held-out performance
  by an unknown amount. The held-out suite was neither read nor run while building this corpus.
