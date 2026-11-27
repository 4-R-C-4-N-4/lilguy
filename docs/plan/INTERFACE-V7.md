# Interface v7: the application owns appends

Status: experimental design tested 2026-11-26, after release 3.0.0; [not adopted](#result-not-adopted). The shipped app remains on v6 (`INTERFACE_VERSION = 6`). Versioning follows [ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on).

## Why

3.0's held-out v3 "append exact lines" family scored 4/10, against 6/10 for 2.0. That is a two-task drop; the comparison alone does not identify its cause. On separate development fixtures, 3.0 scored higher than 2.0:
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

## Result: not adopted

The same shipped 3.0 checkpoint ran on the RTX 4070 at both interfaces. The Fast12 and broad fingerprints differ only in the interface input; each arm covered the same task IDs with no infrastructure failures.

| Measurement | v6 | Experimental v7 |
|---|---:|---:|
| Fast12 | 9/12 | 9/12 |
| Broad | 64/94 | 62/94 |
| Total roster | 73/106 | 71/106 |
| Append probe, existing final newline | 9/10 | 1/10 |
| Append probe, missing final newline | 9/10 | 1/10 |

The roster gained three tasks and lost five, including `append_meeting_agenda_item`. The append probe lost sixteen and gained none. The model chose `fs.append` on every probe, but all twenty initial calls supplied a single-line payload; nineteen contained literal `\n`. The two successes repaired the result afterwards with `fs.edit`. The application handles real multi-line inputs correctly in live controls, but the unchanged model did not produce them in this experiment. This comparison does not isolate the output-rendering change from the new tool and prompt.

Run directories under `reports/factory/`: v6 `fast12-pti3nymt`, `broad-7jat3bea`, `focus-append-probe-3.0-v6-4070`; v7 `fast12-hujm_z_f`, `broad-xfdm1p65`, `focus-append-probe-3.0-v7-4070`.

Both predeclared checks failed. Keep v7 experimental and do not start training on this design. A future redesign should validate the multi-line argument format on development fixtures before changing the full interface again; don't silently decode literal `\n`, which can be requested file content. Shipped 3.0 stays on v6, and held-out v4 remains unused.
