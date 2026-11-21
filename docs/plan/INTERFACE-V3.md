# Interface v3: the model picks the tool, lilguy owns the answer

Status: approved by Ivy, 2026-11-20. Implementation starts after the seed-43 replication
(`reports/factory/pilot-xif8k6a9`) is reported, because the files changed here are inputs to the
evaluation fingerprint. This follows the versioning rules in
[ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on).

## Why (task evidence)

Under v2, both revision-6 cosine adapters made 19 answers that the agent semantic audits confirm
as wrong (MiniCPM 6, Qwen 13). Some of them passed the frozen graders. See
[the result](../data/ANSWER-COSINE-RESULT.md).

| What went wrong | Count | Fixed by |
|---|---:|---|
| The right fact was in the last output, but the model miscopied it (e.g. "finch" where the sorted output ends with sparrow) | 6 | quoted answers |
| Yes/no judged from raw output (which file is longer, execute bit, final LF, same/differ) | 6 | fact tools (after quoting) |
| Claimed effects that never ran | 2 | already handled by v2's trusted plan and diff |
| Wrong or insufficient command | 5 | training on narrowing commands; fact tools |

Both adapters also wrote files in tasks that said not to modify anything, because the model has
to infer "read-only" from the wording.

## v3 changes

1. **Read-only is the user's choice, enforced by lilguy.**
   - `lilguy ask "..."` (and an MCP flag) runs a session whose policy rejects every write.
   - Questions use `ask` mode; `do` keeps the v2 behaviour.
   - The model never has to recognise "do not modify".
2. **The answer is quoted, not written.**
   - On an episode that changes nothing, lilguy shows the final successful command and its stdout
     verbatim from the trusted audit log, e.g. "Answer from `LC_ALL=C sort arrivals.tsv | tail
     -n 1`: 2026-08-17T10:24Z sparrow".
   - Any text after `done` becomes an unverified note, as change summaries already are in v2.
   - The model's task is to run a command whose output is the answer.
3. **Grading follows what the user sees.**
   - A question task is graded on the quoted stdout body, using the existing fact regexes.
   - Change tasks keep v2 effect grading.
4. **Fact tools, only if needed.**
   - Candidates: `fs.stat` (size, mode with execute bits spelled out, last byte, "ends with LF:
     yes/no") and `fs.compare` (same/differ, first differing line, "A is N bytes longer than B").
   - Add them only for property questions that still fail after 1–3.
5. **Version bump.**
   - `INTERFACE_VERSION = 3` and a v3 golden prompt.
   - v1 and v2 prompts, grammars, graders and corpora stay reproducible.
   - Records refuse mismatched versions.

## Consequences

| Area | Work | Effort |
|---|---|---|
| `ask` mode | Write-reject policy profile; CLI `ask`; MCP flag; tests; replay the recorded bad read-only traces to show writes are rejected and originals kept | ~1 h |
| Protocol and prompt | v3 prompt (no answer wording; "end with the command whose output answers the question"); grammar; golden prompt; unit tests | ~1 h |
| Quoted answer display | `do`/`ask` render the last successful command and stdout from the audit log; model note labelled unverified | ~1 h |
| Evaluator | v3 grading of question tasks on the quoted stdout; v1/v2 grading unchanged; oracle 100% and null control 0% recalibration on development | ~1.5 h |
| Held-out | v3 oracle/null recalibration and re-pin (authorised here); no model runs | ~0.5 h |
| Corpus revision 7 | Question episodes end with a narrowing command and bare `done`; write requests run in `do` mode, questions in `ask` mode; replay, dedup, split gate; agent audit | ~1.5 h |
| Controlled run | Both bases, cosine (the best recipe), v3 revision 7. Report the v2 revision-6 cosine scores as a cross-version reference, not a matched gate | ~2.5 h GPU |

Before any GPU time, the recorded seed-42/43 traces will be regraded offline under v3 quoting.
That gives a rough estimate of the effect, with no claim attached.

## Specification (as implemented)

- **Protocol** (`lilguy/protocol.py`):
  - `INTERFACE_VERSION = 3`; versions 1, 2 and 3 are supported. The v3 golden prompt is
    `tests/unit/interface_v3_system_prompt.txt`.
  - `done` takes no text: the grammar is `done ::= "done"` and the parser rejects any text after
    it. `ask` is unchanged.
  - The first user message is `Request: ...` (`do`) or `Question: ...` (`ask`) (`user_message`).
    Earlier versions keep the raw request.
  - `quoted_answer(turns)` takes the last executed step, if its policy is `ok`, and returns its
    command, exit code and digested stdout. It marks a command as `literal` when it only prints
    text the model typed (`echo`/`printf` with no substitution, pipe, redirect or condition).
- **Question mode:**
  - `Policy(read_only=True)` rejects any staged change (rule `read_only`) and rolls the step back.
    The model sees `policy: rejected (read-only question: PATH)`. A workspace `policy.yaml` cannot
    set it.
  - The MCP server takes `--read-only`. `lilguy ask` uses it and prints the quoted answer; a
    literal echo is reported as no answer.
- **Records** carry `mode` from v3 on; v1 and v2 record shapes are unchanged.
- **Evaluation** (`dev/fast12_runner.py`, `dev/oracles_v3.py`):
  - 21 listed development questions run in `ask` mode; everything else runs in `do`.
  - Oracle syntax stays v2; from v3 a scripted `done` is replayed bare.
  - Questions whose v2 oracle did not end on an answering command get a v3 oracle (18 tasks).
  - Where the scripted solution changes nothing (an answer task), the existing graders check the
    quoted stdout of the last step. A literal echo, or output that is just the whole of a
    multi-line input file, counts as no answer.
  - Change tasks keep v2 grading.
  - Calibration: all 80 development tasks pass their v3 oracle and fail an immediate bare `done`
    (`tests/sandbox/test_dev_v3_live.py`). The same test replays three recorded v2 model writes
    in question mode: all are rejected, nothing is staged and the originals are untouched.
- **Not yet:**
  - held-out v3 recalibration, which needs modes and v3 oracles for its question tasks and is
    authorised as part of v3, before any model runs on it;
  - corpus revision 7;
  - training.
