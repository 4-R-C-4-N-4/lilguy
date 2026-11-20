# Interface v2: the model does simple work, lilguy reports it

Status: proposed 2026-11-20. Interface change approved by Ivy; the scope below needs a go.

## Why

The decision sprint ([result](../data/DECISION-CONTROLLED-RESULT.md)) showed that 0.8–2B models do
not reliably judge ambiguity, and that their `done` summaries often contradict what ran: 11 of
24 MiniCPM and 20 of 28 Qwen failed-done answers in the treatment arms were contradicted by the
trace. Decision (Ivy): the model is for simple, clearly specified work, not reasoning. The human
reviews the executed plan and the diff at the commit stage, so the model need not judge
ambiguity or describe its own effects.

## Already done (v1-compatible)

`lilguy diff`, `approve`, `commit` and `do` now print the executed plan before the diff. It is
rebuilt from the session's trusted audit log, numbered, with each command's outcome and the
files it changed (commit `d7c9e4f`). Shell commands appear verbatim. Typed tools show paths,
numbers and flags, but edit contents, patterns and globs only by length, keeping the existing
rule that typed literals are not persisted. `do` labels the model's `done` text as an
unverified note.

## v2 changes

1. **`done` stops being a report.** The prompt says `done` ends the task. Text after it is the
   answer to a question the user asked, and nothing else. For change requests the report is
   lilguy's executed plan and diff. The grammar allows `done` with no text.
2. **No ambiguity judgement.** Remove the habit "if the request could mean more than one file or
   target, ask". `ask` stays only as a blocked stop: "say what is missing when you cannot do the
   request with what is in the workspace". Pending/rejected stop rules are unchanged.
3. **Version bump.** `INTERFACE_VERSION = 2`, regenerated golden prompt, records refuse
   mismatched versions (existing check). The v1 prompt and data stay reproducible from git.

## Consequences

| Area | Work | Effort |
|---|---|---|
| Protocol, prompt, grammar, loop, `do` | Edit `lilguy/protocol.py`; golden prompt v2; unit tests | ~1 h |
| Corpus v2 → interface v2 | Re-render `done` texts (empty for change tasks, answer for read-only); drop content-judgement ask families; keep missing-input stops; regenerate, replay, split gate | ~1.5 h |
| Development suite | Retarget graders: change tasks graded on effects and an honest terminal; read-only answers checked against the observations; the 9 clarification tasks become explicit-request variants, or move to a non-model harness test | ~1.5 h |
| Held-out suite | Its graders assume v1 (`ask` targets, answer text). It must be re-frozen for v2 before any model runs on it. No model has run it yet, so a re-freeze is leakage-free, but it means editing held-out templates | ~0.5 h, needs your authorisation |
| Train and compare | One factory command, both bases, v1-trained vs v2-trained on matched data. Evaluation runs on the v2 dev suite; v1 scores are not comparable | ~2.5 h GPU |

Total: about one five-hour sprint, plus the held-out re-freeze if authorised.

## Success measures (v2)

- Effect correctness on explicit requests, per category, with Wilson intervals.
- Honest terminal: `done` only after a successful final step; a failed step is never followed
  by `done` without a fix.
- Read-only answers supported by the command output.
- Latency.

Not measured on the model: ambiguity detection.

## Not in scope

- An input language. Executed-plan review covers most cases. Revisit only if review shows
  repeated misreadings of plain requests.
- Cosine warmup/decay remains a separate single-factor experiment.
