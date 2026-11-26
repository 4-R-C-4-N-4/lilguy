# Interface v7: the application owns appends

Status: started 2026-11-26, after release 3.0.0 (which ships v6). Versioning follows [ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on). The app stays on v6 (`INTERFACE_VERSION = 6`) until a model trained on v7 ships.

## Why

3.0's held-out v3 "append exact lines" family scored 4/10, against 6/10 for 2.0. That is two tasks, within noise. On development fixtures 3.0 is far better at appends than 2.0:
- focus "append without final newline": 4/5 against 0/5;
- the new 20-task append probe (`dev/focus_append.py`): 18/20 against 10/20.

3.0's remaining append failures are mechanics, not intent (development traces only):

| Trace | Defect | v7 change |
|---|---|---|
| `printf '%s\n' 'alias gs='\''git status'\''' && 'alias …'`: lines containing quotes broke the shell command | the model must shell-quote content | **`fs.append`**: path plus lines, no shell. Every line ends with a newline, and a missing final newline is added first. |
| It appended after `files=1024` despite `(no newline at end of output)` and glued two lines | the model must remember the EOF state | the same: `fs.append` owns the separator |
| Its repair doubled a line, which it was shown as `stack=8M  (x2)` | v5's "exact" output still collapses consecutive identical lines, contradicting "exactly as printed" | **v7 output shows every line as printed.** Long outputs are still clipped. |

## Changes

- **`fs.append`** (`lilguy/data/toolset_v7.yaml`, run in the sandbox by `_typed_step.append`).
  - **Arguments:** `path`, and `lines` (one line, or several in `<<< >>>`).
  - **The file must exist.** A missing named file is a reason to ask, as since v5.
  - **Output:** `appended N lines to PATH`, plus `(added the missing final newline first)` when that applies.
  - **Policy:** unchanged. A modified file is an ordinary effect.
- **Prompt:** the tool habit adds "To add lines at the end of a file, use fs.append." The golden copy is `tests/unit/interface_v7_system_prompt.txt`.
- **Observations:** v7 never collapses repeated lines. v1–v6 render byte-identically.

## Adoption rule (declared before measuring)

Untrained 3.0 is measured on v6 and v7, on the same code and GPU, on the 106-task roster and the append probe. v7 is adopted if both hold:
- **Roster:** v7 scores at least v6's score.
- **Append probe:** v7 scores above v6's score.

Otherwise v7 is redesigned or dropped before any training. Held-out v4 is not used for this.
