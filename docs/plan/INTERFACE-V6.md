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

## Step 1 result (2026-11-24): declared

Unit tests cover the tools, the version gating, the golden prompt, the path checks and safe extraction. The live sandbox runs cover:
- the 106-task roster plus the focus fixtures under v6;
- every tool's effects and policy stops;
- compare in question mode, and the refusal to pack in question mode;
- the bypass suite;
- v5 unchanged.

One defect was found and fixed before measuring: repacking an existing archive went through a 0600 temp file, so the policy saw read bits removed. It now keeps the original mode, as `fs.edit` does.

## Step 2 result (2026-11-24): v6 goes back for redesign before any training

The setup: the same code and the same RTX 3090 for all six runs, 106 roster tasks, untrained on v6. The v5 runs reproduce today's scores exactly.

| Model | v5 | v6 | Permissions v5 → v6 (/4) | Archives v5 → v6 (/10) | Calls to the new tools |
|---|---|---|---|---|---|
| 2.0 | 64 | 63 | 3 → 2 | 4 → 5 | 5 |
| r13 s42 | 68 | 64 | 2 → 1 | 5 → 4 | 11 |
| r13 s43 | 59 | 58 | 3 → 1 | 4 → 5 | 17 |

The rule in the step table above was that a loss sends v6 back. All three models lost (−1, −4, −1), and permissions fell at every model.

Runs:
- v5: `fast12-lq8rj9nv`, `broad-o8hroiih` (2.0); `fast12-evxe27xh`, `broad-px1ervgb` (s42); `fast12-g_wm3mhw`, `broad-yx6c2yqq` (s43)
- v6: `fast12-v8rxi_tr`, `broad-xvy_t78f` (2.0); `fast12-9q2l82pi`, `broad-n5q3zy9h` (s42); `fast12-zg5ubl2a`, `broad-2gg0uogq` (s43)

### What the traces show (development only)

**`fs.chmod` cannot express "only".**
- `restrict_local_draft_mode` asks for "owner-readable and owner-writable only". All three models reached for `fs.chmod`, and all three lost the task. On v5, two of them passed it with `chmod 600`. Each picked a different single class:
  - 2.0: `who: all`, remove read and write, giving `---------`;
  - s42: `who: others`, giving `rw-r-----`;
  - s43: `who: user`, giving `---r--r--`.
- The add/remove design needs two calls to reach 600 (group and others), and no model planned that.
- This is the same comprehension gap lesson 7 found. The typed form moved it rather than removing it.

**`fs.chmod` takes one path.** s43 tried `path: helpers/*.sh`, got "No such file or directory", then changed one of the two scripts.

**`fs.chmod` became a fallback action.** r13 s42 and s43 called it 1 and 3 times on tasks with nothing to do with permissions, after a failed command (`chmod a+x settings.tar`, `others: read add` on a folder). One call even had every bit set to keep. An untrained model treats an unfamiliar tool as something to try.

**The archive tools are used for what they are for.** `archive.list` is used to look before acting in nearly every archive task, and `archive.unpack` passed `unpack_without_overwriting` for 2.0 and s42 (0/3 on v5). The net archive score is still flat:
- `archive.pack` with `add: true` was used to *extract* (s43, twice);
- no model used `member` to take one file out.

### Redesign before step 2 is repeated

| # | Change | Why |
|---|---|---|
| 1 | `fs.chmod` states the result per class: `user`, `group` and `others` each take `keep`, or the permissions to end with, written as words: `none`, `read`, `read write`, `read execute`, `read write execute`. A separate `add`/`remove` stays for "let the group execute" | "Owner only" becomes one call: `user: read write`, `group: none`, `others: none` |
| 2 | `fs.chmod` `path` accepts a glob (`helpers/*.sh`) | It is what models wrote |
| 3 | `archive.pack` loses `add`, and a separate `archive.add` takes over adding to an existing archive | "pack … add" read as "take out" |
| 4 | The prompt names the one-file case: "to take one file out, use archive.unpack with member" | No model found `member` |

Nothing has been trained on v6, so it is revised in place, and the golden prompt is regenerated. Step 2 is then repeated under the same rule.

## Redesign (2026-11-24, in place: nothing has been trained on v6)

| Change | Now |
|---|---|
| `fs.chmod` | `path` (a path or a glob such as `helpers/*.sh`); `user`, `group`, `others`, each one of: `keep`; a final state (`none`, `read`, `write`, `execute`, `read write`, `read execute`, `write execute`, `read write execute`); or one change (`add read|write|execute`, `remove read|write|execute`); `recursive`. Output: one line per path, `before -> after` or `(unchanged)`. |
| `archive.pack` | New archives only (no `add`). A file source keeps its workspace path inside the archive, as tar does. |
| `archive.add` | New tool: add a file or folder to an existing .tar, .tar.gz or .tgz, keeping its members. |
| Prompt | The tool habit adds: "To take one file out of an archive, use archive.unpack with member." |

This is one change from the redesign table above: instead of a separate add/remove argument, each class takes one value, either a final state or a single change. "Owner only" (`user: read write`, `group: none`, `others: none`) and "let the group execute" (`group: add execute`) are each one call.

The golden prompt was regenerated. Unit and live tests were updated, and a test was added that globs cannot leave the workspace. Step 2 is repeated below under the same rule.
