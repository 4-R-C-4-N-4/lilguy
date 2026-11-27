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

## Implementation (prototype, uncommitted on `work/bulk-renames`)

- `lilguy/data/toolset_v8.yaml`, `lilguy/protocol.py` (`TOOLS_V8`, `tool_names`, `_HEADERS[8]`, `SUPPORTED_VERSIONS` 1–8, `LATEST_VERSION = 8`, collapse for every version but 7), `lilguy/serve.py` (`--interface 8`).
- `lilguy/_typed_step.py`: `rename_target` (pure, idempotent) and `rename` (whole mapping and collision check before the first move; undo on a mid-batch `OSError`).
- `lilguy/mcp_server.py`: audit argument types are the union over all versions, so v7's `fs.append` keeps its audited path now that v8 is the latest interface.
- `lilguy/policy/renames.py` + `approval.summarize()`: the review block. Only the pending step's own changes (`step_paths`) can be credited to the rename; each pair needs matching size and identical staged bytes.
- `dev/focus_rename.py`: five development fixtures, with a v6 `mv` oracle and a v8 `fs.rename` oracle each.
- Tests: `tests/unit/test_protocol_v8.py`, `interface_v8_system_prompt.txt`, `test_approval_renames.py`, `test_mcp_audit_v8.py`, `test_focus_rename.py`, `tests/sandbox/test_interface_v8_live.py`.

Known limits: `zero_pad` splits the extension at the last dot only, so `v1.tar.gz` becomes `v001.tar.gz`, padding the digits in front of `.tar`. Selection is one folder, not recursive. Folders are never renamed.
