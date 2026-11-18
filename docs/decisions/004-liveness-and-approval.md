# 004: Progress-aware time limits, and the human approval flow

Status: implemented and tested; changes spec §8 (`exec timeout_s ≤ 60`) and §10 (wall-clock timeout). Accepted by Ivy in discussion on 2026-11-18 ("sounds good" / "yes please"). **Accepted by Ivy 2026-11-18.**

## Time limits

A fixed 10–60 s wall clock killed legitimate slow work (builds) and threw it away. Halting can't be decided in general, so the sandbox now watches what a step does instead:

- **Progress** = new output that is still being captured, or the step's overlay layer reaching a new high in bytes or file count. Output past the capture cap and create/delete churn do not count: nobody sees the first, and the second accumulates nothing. CPU alone is never progress. (`io.stat` is not delegated to user scopes on the target host, so disk I/O is not used.)
- **Idle** (CPU < 50% of one core, no progress) for `idle_timeout_s` (default 60 s): stop.
- **Stalled** (busy, no progress) for `stall_timeout_s` (default 30 s): **freeze** the step's cgroup and ask the trusted monitor. In `sandbox-run`, that is the terminal: continue or stop. With no one to ask, it stops. Verified on the target host: CPU use while frozen is exactly zero, and it resumes after thaw. Frozen time doesn't count against the budget. If freezing fails, the step keeps running while the monitor decides, and that time is counted.
- **Hard wall** `timeout_s` (default 600 s, maximum 24 h) remains as the backstop.
- Heartbeats every `heartbeat_s` (30 s) report elapsed time, CPU, files and bytes written, and the last output line (with control characters neutralised).
- **A stopped step keeps its partial layer.** Its diff is computed as usual and the policy marks it pending (`incomplete_step`), unless it touched something that is always rejected (protected paths) — then it is rolled back. Disk-cap, runner errors and uninspectable effects are still rejected and rolled back.

Without cgroups (the explicit rlimits fallback, decision 003), CPU can't be measured, so any no-progress stretch is treated as stalled.

## Approval

- A pending step writes `approval-request.json` to the private session directory: the rule, every change with sizes and modes, which changes are new since the last approval, the (untrusted) command, and a hash over the diff and file contents.
- `lilguy diff | approve | deny <session>` run in the human's terminal. The session directory is outside the workspace and is verified invisible inside the sandbox, so the model cannot reach these.
- `approve` shows a readable summary (e.g. `src/main.c   mode 644 -> 000`) and needs a typed `y`, or `--diff-hash` matching what was reviewed. Without a terminal, `--diff-hash` is required. Paths and output are shown with control characters neutralised.
- **Approval carries forward.** Each approved change is fingerprinted (operation, path, sizes, modes, content hash). Later steps and commit exempt only changes whose fingerprint still matches exactly; anything new or altered is checked again. Rejections (protected paths) and workspace conflicts are never excused by an approval.
- `deny` rolls back only the step that asked; earlier accepted steps stay. `deny --discard` drops the whole session. The real workspace is never touched by either.
- Run, approve and deny take a per-session lock. A process whose session was changed by `deny` elsewhere refuses to continue (`SESSION_CHANGED`) rather than run on stale layer state. Session state is re-validated on reload (private 0700 directory owned by the user, contiguous layers, safe cwd, mandatory protected paths present); tampered state is refused.

## Reading files a command made unreadable

`chmod 000` on a single file used to crash the host-side diff (the host can't read a mode-000 file without root), turning decision 001's own example into a reject. The host now briefly adds owner-read to such a file, opens it, and restores the exact mode immediately. It does this only for regular files it owns inside the private session directory, never through symlinks and never in the real workspace. Unreadable workspace files still fail closed. Recursive `chmod -R 000` on a directory is still rejected (decision 002): directory traversal is blocked and widening directories is not done.

## Still not done

No `lilguy commit` command yet; commit/undo remain tested library calls. No retention/expiry of kept sessions or requests. The agent loop (P5) does not yet have a "still running — continue?" action; only the terminal monitor exists.
