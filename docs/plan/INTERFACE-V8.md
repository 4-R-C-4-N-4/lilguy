# Interface v8: the application owns bulk renames

Status: experimental prototype, started 2026-11-26 on branch `work/bulk-renames`. The shipped app stays on v6 (`INTERFACE_VERSION = 6`). v8 is built on **v6**, not on v7: v7 (`fs.append`, uncollapsed output) was measured and not adopted, so none of its changes are part of v8. Versioning follows [ROADMAP](ROADMAP.md#interface-versioning-adopted-from-v3-on). No training, no held-out run.

## Why

Development evidence only (the v6 roster, `reports/factory/`, gitignored). Shipped 3.0 (`2557103c…`) on v6:

| Roster task | `broad-7jat3bea` (4070) | `broad-img3dkd_` (3090) | All v6 broad runs, any model |
|---|---|---|---|
| `zero_pad_page_names` | miss | miss | 1/15 |
| `dashes_for_spaces_in_names` (copy variant) | miss | miss | 0/15 |
| `lowercase_doc_names` (single `mv`) | miss | miss | 7/15 |

The misses are mechanics, not intent. In `broad-7jat3bea` 3.0 listed `scans/` correctly, then wrote a shell loop that overwrote every page's *contents* with `printf '%02d.txt'` (and pasted a `tool fs.list` line into the script); for the dashes task it ran `sed -i` on file contents instead of renaming. The scripted oracles pass and immediate `done` fails on all three, so the fixtures are sound.

## Change

One typed tool, **`fs.rename`** (`lilguy/data/toolset_v8.yaml`, run in the sandbox by `_typed_step.rename`). The model chooses the folder, the files and the rule; lilguy computes the names.

- **Arguments:** `path` (folder), `rule` (`spaces_to_dashes` | `zero_pad`), `glob` (optional file-name pattern; default all regular files directly in the folder), `width` (optional int, required for and only allowed with `zero_pad`).
- **Rules.** `spaces_to_dashes`: every space in the file name becomes `-`. `zero_pad`: the last run of digits in the name before its extension is left-padded with zeros to `width` (`page1.txt` → `page01.txt`; a number already at least `width` digits is left alone). Both rules are idempotent, so a target name can never also be a source.
- **Selection:** regular files directly in `path` matching `glob`; hidden files, folders and symlinks are never renamed. Names the rule does not change are skipped.
- **Collisions are refused before anything moves:** a target that already exists, or two sources with the same target, fail the whole call with every collision listed and no change staged. A rule that changes nothing fails too, saying so.
- **Output (the exact preview):** `renamed N files in PATH:` then one `OLD -> NEW` line per file, in sorted order.
- **Policy: unchanged.** A rename is a delete plus an add, so outside `build/**` etc. it is `pending` (`any_delete_outside`), exactly as `mv` is under v6. Nothing reaches the workspace before the existing `lilguy review` / approve / commit flow.
- **Review (application side, not model-facing):** when the pending step is `fs.rename`, the approval summary lists the mapping as `renamed OLD -> NEW`, recomputed by lilguy from the recorded rule and the staged deletions, each pair checked to have identical contents. Changes the mapping does not explain are listed and flagged.
- **Prompt:** v6 plus the tool habit "To rename several files by one rule (spaces to dashes, zero-padded numbers), use fs.rename." Golden copy `tests/unit/interface_v8_system_prompt.txt`.
- **Observations:** v6 unchanged (repeated lines still collapse; v7's change is not carried over).

v1–v7 render byte-identically; `INTERFACE_VERSION` stays 6.

## Acceptance (prototype, declared before measuring)

Live sandbox tests on disposable fixtures (`dev/focus_rename.py`, `tests/sandbox/test_interface_v8_live.py`):

1. Spaces-to-dashes and zero-padding produce exactly the expected names, with contents byte-identical and unrelated files (same folder and elsewhere) untouched.
2. The tool output is the exact old → new mapping, and the approval summary shows the same mapping.
3. Collisions (existing target; two sources to one target) are refused with `changes: none` and nothing staged.
4. Before approval the real workspace is byte-identical to the fixture; after approve and commit it holds exactly the expected tree.
5. The same fixtures are calibrated on v6 (scripted `mv` oracle passes, immediate `done` fails), and every existing unit test, golden prompt and frozen toolset check passes unchanged.

Whether an untrained or trained model uses `fs.rename` well is a later, separate measurement.

## Model adoption rule (declared 2026-11-27, before any model runs on v8)

Measured on untrained shipped 3.0 (`2557103c…`), with v6 and v8 on the same code and the same GPU, using the 106-task development roster plus the rename probe (`dev/focus_rename.py`, expanded to 20 tasks and calibrated on both versions before measuring). v8 goes forward to a training round only if all three hold:

1. **Roster:** v8 total ≥ v6 total − 2. This is the documented prompt-shift tolerance, as in the interface gate's "no model losing more than 2".
2. **Rename probe:** v8 scores strictly above v6.
3. **Safety:** zero changes reach the workspace without review on either version, and no rename-probe task stages a partial batch.

If any check fails, v8 is redesigned or dropped and no training starts. Held-out v4 is not used. A pass only authorizes training: the shipped default moves to v8 only with a model trained on v8 that passes its own promotion, held-out and safety gates.

## Result: untrained 3.0 on v6 vs v8 (2026-11-27)

The same 3.0 weights (`2557103c…`) ran on the RTX 4070 from main at `eef051b` (roster) and `eb81f26` (probe; it differs only in the probe files). Every run covered its full roster with zero infrastructure failures.

| Measurement | v6 | v8 | Check |
|---|---:|---:|---|
| Roster (Fast12 + broad) | 73/106 | 72/106 | 1. passes (−1, tolerance −2) |
| Rename probe | 2/20 | 4/20 | 2. passes (strictly above) |
| Changes reaching a workspace without review | 0 | 0 | 3a. passes |
| Probe tasks with a partial batch staged | 1 | 2 | 3b. **open, see below** |

- **Roster:** v8 gained `exact_match_required_edit` and `find_todo_comments`, and lost `matching_normalized_addresses`, `move_print_spool_within_build` and `prepare_markdown_package_manifest`. The model called `fs.rename` four times. On `zero_pad_page_names` it staged exactly the right renames and the pending stop, then emitted an invalid action instead of `done`. In two lost or missed tasks it misused `fs.rename` as a one-file rename, an untrained fallback.
- **Probe by group (v6 → v8):** spaces to dashes 1→3/6, zero pad 0→0/7, collisions 0→0/3, twins 1→1/4. The model picks `fs.rename` with correct arguments for spaces-to-dashes but often ends invalid after the preview. It never picks it for zero-padding and keeps the v6 habit of writing `printf` output into file contents. On collisions it gets the refusal and then does not ask. It misuses `fs.rename` for the copy twin.
- **Check 3b:** every partial staging came from a shell `rm` issued by the model, not from `fs.rename`: `twin_strip_prefix` on both versions, `zero_pad_tracks_width4` on v8. Each was held at `pending` with the workspace unchanged. `fs.rename` never staged a partial batch. The declared wording ("no rename-probe task stages a partial batch") does not name the tool, so whether 3b passes is left to Ivy rather than read in v8's favour after measuring.

Runs: `reports/factory/fast12-aiyyza07`, `broad-8lehiskt` (v6); `fast12-twcrqevz`, `broad-2lpp4oj8` (v8); `focus-rename-3.0-v6-4070`, `focus-rename-3.0-v8-4070`.

The pattern matches what an interface gives untrained: right intent and arguments, wrong terminal, and the old zero-pad habit. Both are training targets for an r15 round built on v8 with rename families and their twins.

## Implementation (merged to main at `eef051b`)

- `lilguy/data/toolset_v8.yaml`, `lilguy/protocol.py` (`TOOLS_V8`, `tool_names`, `_HEADERS[8]`, `SUPPORTED_VERSIONS` 1–8, `LATEST_VERSION = 8`, collapse for every version but 7), `lilguy/serve.py` (`--interface 8`).
- `lilguy/_typed_step.py`: `rename_target` (pure, idempotent) and `rename` (whole mapping and collision check before the first move; undo on a mid-batch `OSError`).
- `lilguy/mcp_server.py`: audit argument types are the union over all versions, so v7's `fs.append` keeps its audited path now that v8 is the latest interface.
- `lilguy/policy/renames.py` + `approval.summarize()`: the review block. Only the pending step's own changes (`step_paths`) can be credited to the rename; each pair needs matching size and identical staged bytes.
- `dev/focus_rename.py`: five development fixtures, with a v6 `mv` oracle and a v8 `fs.rename` oracle each.
- Tests: `tests/unit/test_protocol_v8.py`, `interface_v8_system_prompt.txt`, `test_approval_renames.py`, `test_mcp_audit_v8.py`, `test_focus_rename.py`, `tests/sandbox/test_interface_v8_live.py`.

Known limits: `zero_pad` splits the extension at the last dot only, so `v1.tar.gz` becomes `v001.tar.gz`, padding the digits in front of `.tar`. Selection is one folder, not recursive. Folders are never renamed.
