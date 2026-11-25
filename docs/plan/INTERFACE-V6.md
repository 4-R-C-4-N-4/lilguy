# Interface v6: typed permission and archive tools

Status: started 2026-11-24. Versioning follows [ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on). The shipped app stays on v4 (`INTERFACE_VERSION = 4`), and v6 becomes `LATEST_VERSION`. 2.0 keeps running on v4, and 1.x on v3.

## Why

The factory's premise: when a capability fails consistently, consider the interface before more data.

| Evidence (development only) | What it shows | v6 change |
|---|---|---|
| Lesson 7: "executable by the group" became `chmod g+s`. The fault sits in the request tokens at layers 8–16. Steering towards `x` produced `chmod +g +x`. | The model reads permission words into the wrong mode letters and cannot write mode syntax reliably | `fs.chmod`: who (user, group, others, all) and add/remove per read, write and execute. lilguy owns the mode bits. |
| Roster 106: archives 4–5/10 for 2.0 and both r13 seeds. Errors: `diff` against a .tar, `cat` appended into a tar, extracting "here" into a new folder, `tar -czg` | Wrong tar idioms, not wrong intent | `archive.list`, `archive.pack`, `archive.unpack`, covering .tar, .tar.gz/.tgz and single-file .gz |

## The tools

They are defined in `lilguy/data/toolset_v6.yaml`; the frozen v1–v5 manifest is untouched. Every tool runs inside the sandbox through `lilguy/_typed_step.py`, like `fs.edit`. Policy, approval and audit are therefore unchanged and effect-based: removing a read or write bit still stops as pending, and so does a delete.

| Tool | Arguments | Output |
|---|---|---|
| `fs.chmod` | `path`; `who` user\|group\|others\|all; `read`, `write`, `execute` each add\|remove\|keep (default keep); `recursive` (default false) | One line per changed path: `path: rw-r--r-- -> rw-r-xr--` |
| `archive.list` | `path`; `compare` (default false): for each member, whether the workspace file at that path is the same, differs or is missing | One member per line, with its size or its comparison |
| `archive.pack` | `archive` (.tar, .tar.gz, .tgz or .gz); `source` (file or folder); `exclude` (name glob, optional); `add` (default false: keep the archive's members and add these); `top_folder` (default true: keep the folder's own name inside) | The members written |
| `archive.unpack` | `archive`; `into` (default .); `member` (optional: only this one); `overwrite` (default false: existing files are kept and named) | Files written, and files kept |

Safety notes:
- Extraction uses tarfile's `data` filter. That refuses absolute paths, `..`, links leaving the destination, and device files.
- Every path argument is checked as workspace-relative, as for the other typed tools.
- `.gz` holds one file only. Packing keeps the original, and unpacking writes the name without `.gz`.

## Prompt

v6 is v5 plus the four tools in the tool list, and one change to the habit about tools:

> Use a tool below when it fits; otherwise use run. For permissions, and for tar or gzip files, use fs.chmod and the archive tools rather than chmod or tar.

The golden copy is `tests/unit/interface_v6_system_prompt.txt`. Observations and action syntax are v5 unchanged. v1–v5 render byte-identically.

## Steps, weighed by effort

| # | Step | Effort | Decides |
|---|---|---|---|
| 1 | Tools, protocol gating, golden prompt, unit tests; live sandbox tests of each tool and of policy stops; roster controls under v6 | half a day | v6 declared |
| 2 | 2.0 and r13 s42/s43 on v5 and v6, same code: roster 106 | ~40 min GPU | what the interface alone does for untrained models |
| 3 | If v6 is neutral or better: corpus revision 14 = r13 re-recorded on v6, with permission and archive episodes using the tools | build ~30 min | — |
| 4 | Train r14 at seeds 42, 43, 44; judge by the [three-seed rule](ROADMAP.md#2026-11-24--promotion-rule-for-training-rounds-from-r14-on-decided-before-r14) | ~4 h GPU | promotion candidate |
| 5 | Held-out v3 once on r14 s42 (v6) and once on 2.0 (v4) | ~30 min GPU | release |

**What to expect from step 2:** untrained models have never seen these tools, so a small gain or no change is the likely result. As with v5, step 2 checks that the interface costs nothing before data is built on it. A loss in step 2 sends v6 back for redesign before any training.
