# 005: Mandatory policy floor vs. tunable approval rules; safe undo

Status: implemented and tested. Corrects an over-strict floor introduced earlier this round. **Accepted by Ivy 2026-11-18.**

## Policy layering

Spec §6 / guide §6.1: "workspace config cannot weaken server config". Earlier, every policy list was prefixed with the full default `Policy()`. That stopped workspace config from weakening anything, but it also stopped *trusted* config from tuning approval rules. One consequence: spec corpus #19 ("3 steps × 15 deletions → pending at step 2, session total > 20") could never happen, because the default `any_delete_outside` rule already makes the first deletion pending, and no config could switch it off.

Now there are three layers, and the strictest decision wins:

1. **Mandatory floor** (`engine.MANDATORY`). No configuration can lift it. It covers protected paths (`.git/**`, `.lilguy/**`, `**/.env`), special files, invalid paths, workspace conflicts, and permission reduction (decision 001).
2. **Trusted policies**: the server, or whoever constructs the session. When none are given, the spec defaults (`Policy()`) apply, so the behaviour out of the box is unchanged.
3. **Workspace `.lilguy/policy.yaml`**: it can only add restrictions. A workspace file that sets a higher limit doesn't lift a trusted limit.

Corpus #19 now runs live (`tests/bypass/test_corpus_extra.py`). With trusted config that disables per-delete approval, step 1 (15 deletions) is ok and step 2 is pending on `max_deletes`. Under the spec defaults, the first deletion is already pending, which is stricter than #19 asks.

## Undo never destroys later work

`lilguy undo` used to restore pre-images unconditionally, so it would silently overwrite edits made after the commit, and remove files added inside a directory the commit created. Each commit now records the post-commit state of every path it touched (kind, mode, content hash, symlink target, and every descendant). Undo refuses with `UndoConflict`, listing the paths, if any of these changed. Undo data expires after 7 days (`prune_commits`, run on every `lilguy commit`).

Commit also now refuses whenever the workspace changed under the session, independent of which approval rule was reported.

## Commit and recovery from the CLI

`lilguy commit <session>` shows the changes and asks you to confirm by typing `y` (or `--diff-hash` without a terminal). It refuses while a decision is pending. Before committing, it recovers any interrupted commit for that workspace, as guide §6.4 requires at startup. It mirrors the session's audit to `<state>/audit/<session>.jsonl` and then discards the session's layers. `lilguy undo` with no argument lists undoable commits.
