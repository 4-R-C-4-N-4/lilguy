# Interface v5: show the whole file

Status: started 2026-11-23, after release 2.0.0. Versioning follows [ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on). The shipped app stays on v4 (`INTERFACE_VERSION = 4`) until a model trained on v5 ships. v5 is `LATEST_VERSION`. 2.0 keeps running on v4, and 1.x on v3.

## Why

The focus round on 2.0's weak spots ([diagnosis](../data/FOCUS-R11-DIAGNOSIS.md)) found observations that hide what the model needs to see:

| Trace (development fixtures only) | Defect | v5 change |
|---|---|---|
| `alpha\nbeta` showed as `alpha` / `beta`, like a file that ends in a newline. 0/20 tuned appends were right. | v4 output hides a missing final newline | A line `(no newline at end of output)` after `>>>` when stdout does not end with a newline |
| A blank line was written as three spaces, and the read-back looked identical | v4 strips trailing spaces and drops trailing blank lines | Output lines are shown exactly as printed: trailing spaces and blank lines are kept |
| The model read a missing `settings.local.ini`, got `Expected a regular file`, and edited `settings.ini` | The refusal reads like a type problem | `No such file: PATH`, `PATH is a directory, not a file`, and `No such file or directory: PATH` from `fs.list`/`fs.find`/`fs.grep` |
| Same | The prompt never says what to do when a named file is absent | One sentence: "If a file the user names does not exist, ask: never change a file with a similar name instead." |

The system prompt adds two sentences: the marker, and the absent-file rule. Its golden copy is `tests/unit/interface_v5_system_prompt.txt`. Action syntax and grammar are unchanged.

## Where it lives

- `lilguy/digest.py`: `digest(..., exact=True)` (v5 implies framed).
- `lilguy/protocol.py`: `render_observation(version>=5)` and `_HEADERS[5]`.
- `lilguy/_typed_step.py`: refusals gated on the interface the server passes.
- `lilguy serve --interface 5` / `setup --interface 5`.

v1–v4 render byte-identically (`tests/unit/test_protocol_v5.py`).

## Steps, weighed by effort

| # | Step | Effort | Decides |
|---|---|---|---|
| 1 | Code, golden prompt, unit tests; live controls for the 80-task roster, both focus sets and held-out v3 under v5 | half a day | v5 declared |
| 2 | 2.0 unchanged on v4 and v5, on the same code: roster and focus-r11 | ~30 min GPU | what the interface alone fixes |
| 3 | Corpus revision 11: r10 re-recorded on v5, plus five families (`dev/corpus_r11.py`). The split gate covers held-out v1, v2 and v3, and the dedup covers focus-r11. | build ~30 min | — |
| 4 | Train r11 at seeds 42 and 43 with the cosine recipe of 1.0/2.0; roster and focus at each seed | ~2.5 h GPU | promotion candidate |
| 5 | Held-out v3 once on the chosen candidate (v5), and once on 2.0 (v4) | ~30 min GPU | release |
