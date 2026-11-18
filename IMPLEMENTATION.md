# lilguy: implementation guide

**For:** the implementing agent (and Ivy). **Read first:** [`SCOPE.md`](SCOPE.md) for what and why, [`spec.md`](spec.md) for the sandbox design rationale.

This guide says **how** to build each phase in SCOPE §5: interfaces, algorithms, file layout, tests,
and the pitfalls already found. Where it makes a design choice not already in SCOPE, it's marked
**[choice]** so it can be revisited.

---

## 0. Rules for the implementing agent

### Current goal: lilguy's own model (supersedes the "first local-model milestone")

The working goal and its step-by-step plan live in
[`docs/SMALL-MODEL-PROPOSAL.md`](docs/SMALL-MODEL-PROPOSAL.md). In short, train a
small model (≤ 1.5B target) whose home turf is the lilguy interface. It handles
everyday shell requests through typed tools and sandboxed `run`, asks when a
request is ambiguous, stops honestly, and ships as `lilguy do`. The plan's steps
map onto the phases below:

| Plan step | Phase |
|---|---|
| Step 1: freeze interface v1 | P5 |
| Step 2: `run` and the reviewed typed tools on lilguy-sh | P3 |
| Step 3: agent loop and trajectory recorder | P5 |
| Steps 4–5: task suite, held-out set and baselines | P7 |
| Step 6: verified training trajectories in the interface | P6 |
| Steps 7–8: SFT and quantised daily driver | P8 |

The earlier tracer milestone (find/read/edit on config fixtures) is complete; see
PROGRESS.md.

Neither SWE-chat access nor host process tools gate this work. The approved Git integration (option B) is a separate human action: only reviewed changes enter a project commit; the model never writes `.git`.

1. **Work phase by phase.** A phase is done when its SCOPE acceptance criteria pass in CI (or, for
   sandbox tests, on a host where `lilguy probe` passes). Don't start a dependent phase on assumptions.
2. **Don't change a SCOPE decision (D1–D7) or skip an acceptance criterion silently.** If something
   is wrong or infeasible, stop and write it up in `docs/decisions/NNN-title.md` for Ivy.
3. **Verify platform behaviour; don't assume it.** §1 lists what's been verified and what hasn't.
   Anything you rely on that isn't there gets a test.
4. **`toolset.yaml` is the single source of truth** for tools: MCP schemas, the grammar, coverage
   and the translator all read it. Never hand-maintain a second copy.
5. **No network in tests.** Datasets are fetched by an explicit `lilguy data fetch` step and cached.
6. **Never run dataset commands outside the sandbox.** They include `rm -rf` and worse.
7. **Personal shell history never enters the repo**, test fixtures or committed reports.

---

## 1. Platform facts

### Verified (kernel 6.18, user namespace via `unshare -Urm`, 2026-11-17)

| Fact | Consequence |
|---|---|
| Overlay mounts work inside an unprivileged user namespace with `-o userxattr`. | Core of P1 works without root. |
| Deleted files appear in the upper dir as **character devices 0:0** (whiteouts). | Diff: `S_ISCHR && rdev == 0` → `deleted`. |
| A directory deleted and recreated gets xattr **`user.overlay.opaque = b"y"`**. | Diff: opaque dir → everything under it in lower layers is deleted, except what the upper re-adds. |
| Upper dirs also carry `user.overlay.origin` / `user.overlay.impure`. | Ignore these in the diff; they're bookkeeping. |
| A previous step's upper layer can be stacked as a **lower** layer (`lowerdir=up1:ws`) and its whiteouts are honoured. | Per-step layers: rollback = drop the top layer, no copying. |
| A read-only bind mount over `ws/.git` inside the overlay blocks write (`EROFS`), `rm` (`EROFS`) and `mv` of the mount point (`EBUSY`). | Protected paths are enforced at mount level. |
| Landlock ABI 7 is available. The ctypes shim (`landlock_shim.py`) blocks unlink, truncate and `shutil.rmtree` outside granted trees, and blocks TCP connect. | Landlock is the outer fence (writes only inside the workspace and `/tmp`). |
| **Landlock can't carve a read-only hole inside a writable tree:** `.git` under a writable workspace rule stays writable. Rights granted on a directory apply to everything beneath it. | **Don't use Landlock for protected paths**; use read-only binds (row above). |
| Landlock rules on a regular file accept only file rights (`EXECUTE`, `WRITE_FILE`, `READ_FILE`, `TRUNCATE`, `IOCTL_DEV`); directory rights give `EINVAL`. | Shim masks rights per path type. |
| Ubuntu's packaged bubblewrap can be 0.9.0, which **lacks `--overlay`** (added in 0.11.0, non-setuid only). | P0 must check the version; see §5.6 for the fallback. |

### Not yet verified (each needs a test in P0/P1)

- bubblewrap ≥ 0.11 `--overlay` with multiple `--overlay-src` (stacked layers) as an unprivileged user on the target host.
- Behaviour with AppArmor restricting unprivileged user namespaces (Ubuntu ≥ 23.10).
- Directory rename inside the overlay (`redirect_dir` off by default in userns → expect `EXDEV`; check that `mv` falls back to copy+delete and the diff shows it correctly).
- cgroup v2 delegation via `systemd-run --user --scope` on the target host.
- Copying whiteouts as a non-root user (not needed if layers are never copied; keep it that way).

---

## 2. Repository layout

```
lilguy/
  pyproject.toml            # package "lilguy"; extras: [data], [train], [dev]
  toolset.yaml              # tool definitions (single source of truth)
  policy.yaml               # default policy
  lilguy/
    cli.py                  # `lilguy probe|serve|run|eval|data|approve|undo`
    probe.py                # P0
    sandbox/
      backend.py            # Backend protocol + StepResult
      bwrap.py              # bwrap + overlay backend (P1)
      layers.py             # session layer stack, rollback, discard
      diff.py               # walk uppers → DiffEntry list; fold layers
      runner.py             # in-sandbox entrypoint: landlock, cwd, argv/pipe exec
      landlock.py           # from landlock_shim.py
      limits.py             # cgroup / rlimit setup
    policy/
      engine.py             # policy.yaml → decision (P2)
      commit.py             # journal, apply, recover, undo, conflicts
      approval.py           # out-of-band approval channel
      audit.py              # JSONL audit log
    server/
      mcp_server.py         # lilguy-sh MCP server (P3)
      tools.py              # typed tools generated from toolset.yaml
      tasks.py              # task.run via conventions
    agent/                  # v0.1 loop, ported (P5)
      loop.py  envelope.py  grammar.py  digest.py  memory.py  backends.py
    data/                   # P4, P6
      fetch.py  normalize.py  parse.py  coverage.py  translate.py
      fixtures.py  verify.py  label.py  dedupe.py  splits.py  history.py
    eval/                   # P7
      tasks.py  harness.py  metrics.py  ablations.py  report.py
    train/                  # P8
      build_sft.py  config/  export_gguf.md
  tests/
    unit/  sandbox/ (marked, skipped if probe fails)  bypass/  data/  eval/
  docs/decisions/
  reports/                  # generated; gitignored except final reports
```

**Dependencies:** core stdlib + `mcp` (official Python SDK) + `pyyaml` + `bashlex`. `[data]`: `datasets`, `pyarrow`. `[train]`: whichever trainer is chosen in P8. `[dev]`: `pytest`, `hypothesis`, `ruff`.

---

## 3. P0: foundations and capability probe

`lilguy probe` prints a table and exits non-zero if any **required** check fails.

| Check | How | Required |
|---|---|---|
| Kernel ≥ 5.11 | `os.uname().release` | ✓ |
| Unprivileged userns | `unshare -Ur true` | ✓ |
| Overlay in userns | `unshare -Urm` + mount overlay with `userxattr` on a temp tree; delete a file; check for a 0:0 whiteout | ✓ |
| Stacked overlay | Mount `lowerdir=up1:base`; check the whiteout from up1 hides the base file | ✓ |
| bubblewrap ≥ 0.11, not setuid | `bwrap --version`; `os.stat(...).st_mode & S_ISUID == 0` | ✓ (or fallback, §5.6) |
| bwrap `--overlay` works | Run `true` with an overlay mount | ✓ |
| Landlock ABI | `syscall(444, NULL, 0, 1)`; need ≥ 1, warn < 3 (no truncate control), < 4 (no TCP rules) | ✓ (≥ 1) |
| cgroup delegation | `systemd-run --user --scope -p MemoryMax=64M true` | warn; fall back to rlimits |
| Python inside sandbox | Run `python3 -c 0` in the sandbox | ✓ (runner needs it) |

Also in P0: restructure v0.1 into the layout above; keep v0.1's 12 tasks and oracle as regression tests.

---

## 4. Core data types

```python
@dataclass
class DiffEntry:
    op: Literal["added", "modified", "meta", "deleted", "trashed", "replaced_dir"]
    path: str                       # relative to workspace root
    kind: Literal["file", "dir", "symlink", "special"]
    size_before: int | None
    size_after: int | None
    mode_before: int | None
    mode_after: int | None
    symlink_target: str | None
    is_binary: bool

@dataclass
class StepResult:
    exit_code: int
    stdout: str
    stderr: str
    cwd: str                        # relative to the workspace root
    tags: list[str]                 # TIMEOUT, OOM, TRUNCATED, ...
    step_diff: list[DiffEntry]
    duration_ms: int

class Backend(Protocol):
    def open_session(self, workspace: Path, cfg: SessionConfig) -> Session: ...
    def run(self, s: Session, spec: RunSpec) -> StepResult: ...   # RunSpec = shell cmd | argv | pipe
    def rollback_step(self, s: Session) -> None: ...
    def session_diff(self, s: Session) -> list[DiffEntry]: ...
    def resolve(self, s: Session, rel: str) -> Path | None: ...   # host-side layer lookup (see §5.8)
    def discard(self, s: Session) -> None: ...
```

`meta` = content unchanged, only metadata changed (e.g. `touch`). Detected by hashing against the lower version on copy-up. It matters because policy treats it as harmless.

---

## 5. P1: sandboxed exec and diff

### 5.1 Session directory **[choice]**

```
$XDG_STATE_HOME/lilguy/sessions/<session_id>/
  layers/000/{upper,work}  layers/001/{upper,work}  ...
  meta.json      # workspace path, created, layer count, lower stat snapshot for conflict detection
  audit.jsonl
```

Kept **outside** the workspace so nothing inside the sandbox can see or modify it. Journals, undo
pre-images and audit logs also live in the state dir (keyed by a hash of the workspace path), not in
`.lilguy/`. **[choice]** The workspace's `.lilguy/` holds config only (`policy.yaml`,
`conventions.jsonl`), is protected, and adds nothing large to the user's repo.

### 5.2 Step lifecycle

1. Create `layers/N/{upper,work}`.
2. Launch the sandbox with lower layers `[layers/N-1/upper, …, layers/000/upper, workspace]` and upper `layers/N/upper`.
3. On exit, compute `step_diff` from `layers/N/upper` against the merged view of the lower layers.
4. Policy evaluates (P2). If rejected, `rollback_step` = `rm -rf layers/N`.
5. If a session nears the kernel's lower-layer limit (keep N ≤ 64 **[choice]**), squash old layers into one (offline merge, same algorithm as commit but into a directory).

### 5.3 bwrap invocation (template)

```python
argv = [
  "bwrap",
  "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try",
  "--die-with-parent", "--new-session",
  "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
  "--symlink", "usr/lib64", "/lib64",          # adjust per distro (merged-/usr vs not); probe decides
  "--ro-bind", "/etc/ssl", "/etc/ssl", "--ro-bind", "/etc/alternatives", "/etc/alternatives",
  "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
  "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",   # BEFORE the workspace mount (see note)
  # workspace overlay at its REAL host path (decision D10); lowest layer is the real workspace
  "--overlay-src", str(workspace),
  *[a for up in reversed(lower_uppers) for a in ("--overlay-src", str(up))],
  "--overlay", str(upper), str(work), str(workspace),
  # protected paths: read-only binds layered on top of the overlay (must exist in the merged view)
  *[a for p in protected_existing for a in ("--ro-bind", str(workspace / p), str(workspace / p))],  # protected = never changed, so the real path is current
  "--ro-bind", str(RUNNER_DIR), "/opt/lilguy",
  "--setenv", "HOME", "/tmp/home", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
  "--setenv", "LANG", "C.UTF-8", "--setenv", "LC_ALL", "C.UTF-8", "--setenv", "TERM", "dumb",
  "--unsetenv", "SSH_AUTH_SOCK",               # plus: start from a clean env (clearenv) in the launcher
  "--chdir", str(workspace / cwd),
  "--info-fd", "3",                             # optional diagnostics
  "python3", "/opt/lilguy/runner.py", "--spec-fd", "4", "--result-fd", "5",
]
```

Notes:
- **Mount path is configurable** (`sandbox.mount_path: real | short`, default `real`; `short` mounts at `/ws`). Nothing else may hard-code either, so the P7 path ablation is a config switch.
- **Mount order matters.** The workspace keeps its real host path (D10), so absolute paths in project scripts and configs keep working. Mount `/tmp` *before* the workspace: eval tasks and many real workspaces live under `/tmp`, and a tmpfs mounted afterwards would hide them. Only the workspace itself is visible; its parent directories exist as empty mount points.
- **Check bwrap's `--overlay-src` ordering against `bwrap(1)` on the host.** The man page says it's the reverse of the kernel's `lowerdir` order. Write a test (stacked whiteout hides a lower file) rather than trusting the template.
- **Minimal `/etc/passwd` and `/etc/group`:** generate them (one user, uid 1000 → name `lilguy`) and pass with `--ro-bind-data`/`--file`, or tools like `git`, `id` and `ssh-keygen` misbehave.
- **Protected paths that don't exist** (e.g. `.env` absent) can't be bind-mounted. Their creation is caught by the policy instead (`reject: path_matches: protected`).
- Pass the spec and result over inherited fds, not argv/stdout, so command output can't spoof them.

### 5.4 In-sandbox runner (`runner.py`)

Runs inside the sandbox as PID 1's child. In order:
1. Apply Landlock (`landlock.py`): `--rw <workspace> /tmp /dev/null /dev/zero`, `--ro /usr /etc /opt/lilguy /proc /dev/urandom`, plus `--no-tcp` when ABI ≥ 4 (defence in depth on top of `--unshare-net`).
2. Set rlimits: `RLIMIT_FSIZE` (single-file cap), `RLIMIT_NPROC`, `RLIMIT_CORE=0`.
3. Execute the `RunSpec`:
   - `shell`: `bash --noprofile --norc -c CMD`
   - `argv`: `execvp` with a fixed argv (typed tools; no shell)
   - `pipe`: a chain of `Popen` stages connected stdin→stdout (typed `pipe` tool; no shell)
4. After the command: report exit code and final cwd on the result fd. **[choice]** cwd tracking: for `shell`, append `; printf %s "$PWD" >&5` via a wrapper function so stdout stays clean.
5. Cap captured stdout/stderr at 256 KB each and tag `TRUNCATED`.

### 5.5 Limits

Preferred: wrap the bwrap call in `systemd-run --user --scope -p MemoryMax=1G -p TasksMax=256 -p CPUQuota=200%`. Fallback: rlimits only (`RLIMIT_AS` is unreliable with some runtimes; document it). Wall-clock timeout in the server: kill the process group, tag `TIMEOUT`.

**Upper-layer size cap:** after each step, sum `st_blocks` of the step's upper; if it exceeds the cap, roll back and tag `DISK_CAP`. `RLIMIT_FSIZE` stops single huge files mid-step.

### 5.6 Fallback when bwrap < 0.11 **[choice]**

Preferred: build bubblewrap ≥ 0.11 from source (meson; small) and point `LILGUY_BWRAP` at it.
Alternative: a launcher using `unshare -Urmpn --fork` that mounts the overlay itself (verified working, §1), bind-mounts the read-only system paths into a new root and `pivot_root`s. More code, so only if building bwrap isn't possible.

### 5.7 Diff algorithm (`diff.py`)

Large files: only hash when sizes are equal (that's when `meta` vs `modified` is in doubt); a size change is always `modified`.

```
step_diff(upper, lower_view):
  for each entry e under upper (top-down, skipping overlay xattrs):
    rel = path relative to upper
    if e is char device with rdev 0:0:         emit deleted(rel, from lower_view)
                                                (if lower is a dir → deleted for every descendant)
    elif e is dir with user.overlay.opaque=y:  if lower_view has rel as dir:
                                                  emit deleted for lower descendants not present in upper
                                                emit replaced_dir(rel) if lower had it, else added
                                                recurse into upper
    elif e is dir:                             if not in lower → added(dir); recurse
    else:                                      if not in lower → added
                                                elif same content hash → meta (or skip if mode same)
                                                else → modified
  return entries sorted by path

session_diff = fold step layers in order, last-writer-wins per path:
  added then deleted → nothing; deleted then added → modified (or replaced_dir); modified* → modified
```

### 5.8 Host-side layer resolution (`layers.py`) — required

The overlay only exists inside the sandbox, so the host needs its own resolver for commit, and optionally for fast read-only tools:

```
resolve(rel): for layer in [top upper, …, layer 000 upper]:
                 x = layer/rel
                 if x is whiteout: return None
                 if x exists: return x
                 if any ancestor dir of rel in this layer is opaque: return None
              return workspace/rel if it exists else None
```

Never follow symlinks while resolving (`lstat` only), and reject results outside the session or workspace dirs.
**Optional optimisation:** read-only typed tools (`fs.read`, `fs.list`, `fs.stat`) may use the resolver host-side instead of starting a sandbox. They must still apply the same path and symlink rules.

**Tests (P1 acceptance):** delete file, delete dir tree, recreate a deleted dir (opaque), rename file, rename dir (expect EXDEV path), overwrite with same content (`meta`), chmod, symlink in/out of the root, hardlink, a 100 MB file with a 1-byte append (copy-up cost measured), session folding across 3 layers. Use `hypothesis` to generate random op sequences and check `apply(session_diff)` to a copy of the workspace equals the merged view.

---

## 6. P2: policy, approval, commit

### 6.1 Policy engine

Load `policy.yaml` (schema in spec §9) **from the server's config dir or the workspace's `.lilguy/policy.yaml`, read on the host side only**. `.lilguy/` is always a protected path. If both exist, the stricter value wins per field, so a workspace can tighten the server policy but never loosen it. **[choice]**

```python
def evaluate(step: list[DiffEntry], session: list[DiffEntry], ctx) -> Decision:
    # order: reject → require_approval → auto_commit limits → ok
    # evaluated on BOTH step and session diffs; the stricter result wins
    # Decision(kind="ok"|"pending"|"reject", rule="max_deletes", detail="214 deletes under src/")
```

Session-level evaluation catches slow accumulation (bypass corpus #19: 3 × 15 deletions).

### 6.2 Commit timing (decision D8)

Policy runs after **every step**; changes land in the real workspace **once, at the end of the task**
(`done`, or an explicit `changes.commit`). A task that stops early (`max_steps`, crash, `ask` with no
answer) leaves the session uncommitted: the human can inspect it with `lilguy diff <session>` and
commit or discard it. Per-step commit isn't implemented this round.

### 6.3 Pending state and approval **[choice]**

- `pending` freezes the session: further `exec`/write tools return `SESSION_PENDING` until resolved. Read-only tools still work.
- An approval request = `{session_id, diff_hash (sha256 of canonical session diff JSON), summary, top paths}`, written to the session dir.
- Channels, in preference order:
  1. **MCP elicitation**, handled by the agent loop **process** (the MCP client, trusted code), which prompts the human on its own terminal and **never passes the request into the model's context**. The model's output is untrusted; the client process isn't.
  2. **CLI:** `lilguy approve <session> [--diff-hash H]` / `lilguy deny <session>`, run by the human in another terminal; it reads the request and prints the summary first.
- An approval is valid only for its `diff_hash`. Any further change invalidates it.
- The model-facing MCP server **must not expose** any approve/deny tool. Write a test asserting the tool list.

### 6.4 Commit with journal (`commit.py`)

```
commit(session):
  diff = session_diff(session)
  decision = evaluate(...)                      # must be ok, or approved for this diff_hash
  conflicts = check_lower_unchanged(meta.lower_snapshot, diff paths)   # (mtime_ns, size, ino)
  if conflicts: → pending(rule="conflict")
  journal = $STATE/workspaces/<ws-hash>/journal/<session>.json  (status=preparing, ops=[...])
  for each modified/deleted path: copy pre-image → $STATE/workspaces/<ws-hash>/undo/<session>/<path>   (fsync)
  journal.status = applying (fsync)
  apply ops in order:
     1. deletions: files first, then dirs deepest-first
     2. dirs to create (shallowest first)
     3. added/modified files: copy from resolve(session, path) to <path>.lilguy-tmp, fsync, os.replace
     4. mode changes, symlinks
  journal.status = done (fsync); discard session layers

recover() at server start:
  for journals with status preparing → delete journal + partial undo
  for journals with status applying  → restore every pre-image, remove added paths → status rolled_back
```

`lilguy undo <session>` replays pre-images within the retention window (default 7 days; pruned at startup).

**Test:** kill -9 the committer at every op index (inject a crash hook) → after `recover()`, the workspace equals the pre-commit or post-commit state exactly.

### 6.5 Audit log

One JSON object per line in the session dir, mirrored to `$STATE/workspaces/<ws-hash>/audit/` on commit:
`{ts, session, step, tool, args|cmd, exit, duration_ms, step_diff_summary, decision, rule, approval?, commit?}`.
This is also round-2 training data, so keep it complete and stable.

---

## 7. P3: typed tools and MCP server

### 7.1 `toolset.yaml`

```yaml
tools:
  fs.find:
    tier: 1
    effect: read                    # read | write
    args:
      path:      {type: path, default: "."}
      name_glob: {type: string, optional: true}
      type:      {type: enum, values: [f, d, l], optional: true}
      max_depth: {type: int, optional: true, max: 20}
      max_results: {type: int, default: 200, max: 2000}
    impl: {argv: ["find", "{path}", "-maxdepth?{max_depth}", "-type?{type}", "-name?{name_glob}"]}
    bash:                           # used by coverage + translator (P4/P6)
      utility: find
      flags: {"-name": name_glob, "-type": type, "-maxdepth": max_depth}
  pipe:
    tier: 2
    effect: read
    stages: [grep, sort, uniq, head, tail, wc, cut, tr, sed_sub, jq]
  task.run:
    tier: 5
    effect: write
    args: {name: {type: string}}
    impl: {conventions: task}
```

**Constraint [choice]:** tool arguments are **flat**: scalars, enums, paths, or lists of strings.
That keeps the action envelope (§9.1) JSON-free.

### 7.2 Implementation rules

- Every tool runs through the sandbox backend (`RunSpec.argv` or `RunSpec.pipe`), **never** a host-side `subprocess` on the workspace. That's how typed and `exec` changes share one diff and one policy.
- Path arguments: reject absolute paths and `..`; resolve inside the merged view; reject symlinks pointing outside the workspace. Tool arguments and prompts use **workspace-relative** paths only, so training data stays portable across machines even though the sandbox uses the real path.
- **Argument injection:** always place `--` before positional paths and pass patterns with `-e`, so a value like `-delete` or `--exec` is never parsed as a flag.
- **No execution-capable stages:** `sed_sub` takes `(pattern, replacement, flags ⊆ {g, i})` and builds the `s///` expression itself, escaping the delimiter (raw sed scripts allow `e` and `w`, which execute commands and write files). No `awk` stage (`system()`, file redirection). `fs.find` never emits `-exec`, `-execdir`, `-delete`, `-fprint`. `jq` is fine (no I/O). Keep this list in `toolset.yaml` as a test fixture.
- `fs.trash` moves to `<workspace>/.lilguy-trash/<session>/` **[choice]**. It can't go under `.lilguy/` (protected, read-only). Inside the overlay a move shows up as delete + add, so the diff pairs them: a `deleted` path whose content hash matches an `added` path under `.lilguy-trash/` becomes op `trashed`. Policy counts `trashed` separately (reversible) from `deleted`. Add `.lilguy-trash/` to the workspace's `.gitignore`; `fs.restore` reverses the move; trash older than the retention window is pruned at commit.
- Output from read tools is passed through the digester before being returned (same clipping rules).
- `task.run(name)`: look up `{"task": name, "cmd": "..."}` entries in `.lilguy/conventions.jsonl`; run the cmd as `RunSpec.shell` (it's project-authored, but still sandboxed and policy-checked). Unknown task → error listing the known ones.
- MCP server (`mcp` SDK, stdio transport): register tools from `toolset.yaml` + `exec` + `changes.diff|commit|discard`. **No approve tool.**

### 7.3 Tests

Per tool: schema validation, path-escape rejection, and an **equivalence test** that runs the tool and its bash counterpart on the same fixture and compares output and diff.

---

## 8. P4: data ingest and coverage

### 8.1 Fetch and normalise

`lilguy data fetch` downloads into `$XDG_CACHE_HOME/lilguy/data/` (parquet). Normalised record:

```json
{"id": "nl2sh-alfa/train/1234", "source": "nl2sh-alfa", "orig_split": "train", "verified": false,
 "nl": "...", "cmd": "...", "alt_cmds": ["..."], "difficulty": 1, "license": "MIT"}
```

| Source | Use | Notes |
|---|---|---|
| `westenfelder/NL2SH-ALFA` config `train` | SFT candidates | Unverified; must pass P6 verification |
| `westenfelder/NL2SH-ALFA` config `test` | **Eval only** | 600 verified; has `bash2` alternatives and difficulty. The `config` parameter (not `split`) selects train/test. |
| `neulab/tldr` | SFT candidates, retrieval ablation | `oracle_man` field links docs |
| tldr-pages (upstream repo or a mirror) | Knowledge base | Upstream content license is CC BY 4.0; record it with attribution |
| Local shell history | **Coverage only** (decision D9; never training data) | `history.py` parses bash, zsh extended format, atuin sqlite. Output stays in `reports/private/` (gitignored); P6 must refuse history records as input |

### 8.2 Parse (`parse.py`)

`bashlex.parse(cmd)` → walk nodes → features:
`{utilities: [...], flags: {util: [...]}, pipes: n, redirects: [...], subshells: bool, control_flow: bool, parse_ok: bool}`.
bashlex doesn't support every construct (e.g. some arithmetic, `case`, functions); record `parse_ok=false` with the error class, and report the failure rate per source. Optional fallback: tree-sitter-bash.

Normalise flags: split combined short flags (`-rn` → `-r -n`), map long↔short via a small table per utility.

### 8.3 Coverage (`coverage.py`)

A record is **covered** by a toolset if every (utility, flag) used maps to a tool argument or a `pipe` stage, and the structure is supported (pipes yes, `&&` chains yes as multiple calls, subshells/control flow no).

Report (`reports/coverage.md` + CSV):
- Top 50 utilities by frequency per source, with cumulative share.
- For the top 20 utilities: flag frequency tables.
- Coverage % of the current `toolset.yaml`, overall and per source, plus the top uncovered (utility, flag) pairs by count.
- **Greedy suggestion:** add the uncovered (utility, flag set) with the most records each round; print the curve for 10, 20, 30 … additions.
- Same report on local history (private dir).

**Gate:** Ivy reviews the report and signs off `toolset.yaml` (SCOPE Q1) before P3 is frozen.

---

## 9. P5: agent loop

### 9.1 Action envelope **[choice]**

Line-oriented. No JSON, no escaping:

```
expect: output
tool: fs.find
path: src
name_glob: *.py
```

```
expect: ok
tool: exec
cmd: awk -F, 'NR>1 && $2=="eng" {print $1}' people.csv > eng.txt
```

Multi-line commands use a heredoc block:

```
tool: exec
cmd: <<EOF
for f in *.jpeg; do
  mv -- "$f" "${f%.jpeg}.jpg"
done
EOF
```

`ask` and `done` are pseudo-tools with a `text:` field. List arguments repeat the key (`path: a`, `path: b`).

### 9.2 Grammar generation (`grammar.py`)

Generate GBNF from `toolset.yaml` at startup: `expect` enum, `tool` enum, then per tool its keys in a fixed order, with value rules per type (enum → alternatives; int → digits; path/string → `[^\n]+`; exec cmd → `[^\n]+ | heredoc`). Regenerate whenever the toolset changes; add a test that every tool in the toolset can be produced by the grammar.

### 9.3 Prompt

Same shape as v0.1 (GOAL / CONVENTIONS / STATE / HISTORY), plus:
- a compact **tool card**: one line per tool with its args (from `toolset.yaml`), filtered to the tools relevant to the goal when the list gets long **[choice]**;
- observations include the step diff summary and the policy decision (`changes: -14 deleted (build/**) policy=ok`).

### 9.4 Digester v2

v0.1 `digest.py` plus: diff summary line (counts by op, top 3 path globs), policy line, `SESSION_PENDING` and `TOOL_ERROR(arg=…)` tags.

**Path normalisation (D10):** small models are unreliable with long absolute paths, so the model only ever sees workspace-relative ones.
- Rewrite the workspace prefix in stdout, stderr and error tags: `/home/ivy/proj/src/x.c` → `./src/x.c` (longest-prefix match on the real path and its resolved form; leave paths outside the workspace untouched).
- STATE shows `cwd=./src`, never the absolute path.
- Typed tools reject absolute paths with a hint: `TOOL_ERROR(path=absolute; use ./src/x.c)`.
- In `exec` commands the model may still write absolute paths; that's allowed but counted (metric below).
- `--path-view raw` disables the rewrite, for the ablation.

### 9.5 Retrieval

Keep the `ConventionStore` interface; load tldr-pages as global entries (one entry per example line: description + command; keys = utility + description tokens). **Freeze** this snapshot (record the commit hash) before eval tasks are written (D6). Project entries from `.lilguy/conventions.jsonl`, including `task` entries.

**Acceptance:** v0.1's 12 tasks pass through lilguy-sh with the scripted oracle (oracles rewritten in the envelope format). Update expectations for effect-based policy: `policy_redirect` deletes one file, which is now auto-committed, so rewrite it to delete more than the threshold or touch a protected path.

---

## 10. P6: translate, verify, label, split

### 10.1 Translator (`translate.py`)

A registry `util → fn(ast_node) -> list[ToolCall] | None`, driven by the `bash:` blocks in `toolset.yaml`, plus hand-written handlers where the mapping isn't 1:1. Pipelines → one `pipe` call if every stage is supported; `a && b` → two calls. Anything unsupported → `None` (goes to the routing bucket).

### 10.2 Fixtures (`fixtures.py`)

Generate a deterministic fixture tree **per record**, seeded by record id:
- Extract literal paths, globs, extensions and patterns from the gold command (e.g. `-name '*.py'`, `/testbed/dir1/file.txt`, `grep 'error'`) and **make sure the fixture contains matches for them**.
- Add distractors (non-matching files, nested dirs, hidden files, varied sizes and mtimes).
- Map dataset roots like `/testbed` to the fixture workspace root, and rewrite gold commands to workspace-relative paths before translation.

Without seeded matches, most commands produce empty output on both sides and "verify" trivially. **A verification only counts if at least one side produced non-empty output or a non-empty diff.**

### 10.3 Verify (`verify.py`)

For each translatable record: run the gold command via `exec` and the translation via typed tools, each in a **fresh session on its own copy of the same fixture**. Compare:
- exit status class (0 vs non-0);
- stdout, normalised (trailing whitespace; compare as multisets unless the pipeline sorts or the command orders output deterministically);
- session diffs (ops + paths + content hashes).

Statuses: `verified`, `mismatch`, `trivial` (both empty), `nondeterministic` (gold output differs across 2 runs: date, ps, random, timing), `error`. Only `verified` goes into SFT.

### 10.4 Labels (`label.py`)

| Label | Method |
|---|---|
| **Quality** (does `nl` describe `cmd`?) | Judge with a larger local model on `verified` records; drop low scores. Spot-check 200 by hand (SCOPE P6 criterion). |
| **Risk** | From the **observed diff** of the gold run: deletes, truncations, mode changes outside fixture build dirs → `risky`. No text classifier needed. |
| **Routing** for untranslatable records | Judge proposes `exec` (legit but outside the toolset), `ask` (ambiguous or destructive), `drop` (broken, environment-specific). These become boundary training examples. |

### 10.5 Dedupe and splits

- **Command key:** canonical AST print with literals replaced by typed placeholders (`find <PATH> -name <GLOB>`).
- **Instruction key:** MinHash on word shingles, Jaccard ≥ 0.8 = near-duplicate.
- Priority when duplicates cross splits: `eval_heldout` > `eval` > `sft_val` > `sft_train` (eval keeps the record, train loses it). NL2SH-ALFA test descends from NL2Bash, as do parts of the train data, so expect real overlap.
- **Held-out by utility:** pick ~10% of mid-frequency covered utilities; all their records go to `eval_heldout`.
- Output JSONL + `DATASET_CARD.md` with counts after each stage (fetched → parsed → covered → translated → verified → quality-filtered → deduped) per source.

---

## 11. P7: evaluation

### 11.1 Task format (extends v0.1)

```json
{"id": "...", "goal": "...", "fixture": {"generator": "...", "seed": 1} | {"setup": "sh"},
 "check": "sh script, exit 0 = pass",
 "allowed_changes": ["out/**", "answer.txt"],
 "expect_final": "done|ask", "approvals": {"<rule>": "approve|deny"},
 "answers": {"<question regex>": "<reply>"}, "max_steps": 12, "tags": ["recovery", "convention"]}
```

- `allowed_changes`: any committed diff entry outside these globs counts as **collateral damage** (separate metric; fails the task by default).
- `approvals`: scripted responses to pending decisions, so policy interactions are testable.
- `answers`: lets an episode continue after `ask` (spec open issue #6).

### 11.2 Sources of tasks

| Bucket | Count (target) | Origin |
|---|---|---|
| Single-step | 80 | NL2SH-ALFA **test** records, verified in P6 tooling; check = state/stdout match to gold run |
| Recovery | 25 | Hand-authored templates (missing dir, wrong flag, missing tool, permission, wrong cwd) |
| Convention | 15 | Project conventions decide the right command; the wrong one fails visibly |
| Ask vs act | 15 | Ambiguous or destructive goals; half should ask, half should act |
| Policy | 15 | Tasks that trip pending/reject; scripted approve/deny |
| **Held-out** | 50 | Same mix, written last, never used for tuning; run only for milestone reports |

### 11.3 Metrics and reporting

pass@1 with Wilson 95% CI over 5 repeats (T=0.7) plus one T=0 run; steps; tokens in/out; wall time; expect-mismatch rate; invalid actions; `exec` share of tool calls; pending/reject counts; unnecessary asks; collateral damage; **path errors** (see path ablation).

Ablation flags on the harness: `--no-retrieval`, `--exec-only`, `--no-grammar`, `--model <name>`. The report is a grid of model × ablation with CIs.

**Path ablation (D10):** three cells on the same tasks and model: (a) real mount + relative view (default), (b) real mount + raw absolute view (`--path-view raw`), (c) short `/ws` mount + raw view. Report pass rate and the path-error metrics: share of failed steps whose error tag is `ENOENT`/`ENOTDIR` on a model-supplied path, wrong-cwd errors, absolute paths in `exec` commands. If (c) beats (a) beyond the CI, raise it with Ivy to revisit D10.

**Family screen (first step of P7, decision D11):** before the full sweep, run zero-shot on the non-held-out suite with the smallest and mid-size model from 3–4 families (e.g. Qwen3, Gemma 3, SmolLM, Llama 3.2; check current releases first), full scaffold, 3 repeats. Report pass rate, invalid-action rate and tokens per task. Ivy picks the family (SCOPE Q2); the full sweep and P8 use only that family.

Controls: null agent (immediately `done`) must fail 100%; oracle must pass 100%.

---

## 12. P8: SFT round 1

- **Data:** `verified` + quality-filtered pairs rendered as one prompt-response turn: system prompt + user (GOAL, CONVENTIONS from the frozen KB, STATE) → assistant (envelope). Add boundary examples (`exec`, `ask`) at roughly their natural rate in the routing labels **[choice]**, capped at 20%. Add the eval-free multi-step oracle trajectories from hand-authored templates (never from eval tasks).
- **Models:** 3–4 sizes from the family chosen by the P7 family screen (SCOPE Q2), so size is the only variable.
- **Method:** LoRA SFT; start with lr 2e-4, 2–3 epochs, rank 16, max length 2048; tune only on `sft_val`.
- **Export:** merge LoRA → `convert_hf_to_gguf.py` → quantise (Q8_0 and Q4_K_M); evaluate **both** quantisations, because small models can be quantisation-sensitive.
- **Report:** fine-tuned vs. zero-shot per cell, with held-out results reported separately and once.

---

## 13. Testing and CI

| Suite | Runs in CI | Needs |
|---|---|---|
| `unit/` | always | nothing |
| `data/` | always | small vendored samples (synthetic, not real dataset rows) |
| `sandbox/` | when `lilguy probe` passes | userns, bwrap ≥ 0.11, Landlock |
| `bypass/` | when probe passes | spec §12 corpus as parametrised tests, expected decision per case |
| `eval/` smoke | always (scripted backend, typed-tool-only mode if no sandbox) | |

Mark sandbox tests `@pytest.mark.sandbox`; skip with the probe's reason instead of failing silently.

---

## 14. Known pitfalls

1. **Distro bwrap too old** (0.9 on Ubuntu 24.04 era packages): no `--overlay`. Build ≥ 0.11 or use the §5.6 fallback.
2. **Landlock can't protect subpaths of a writable tree.** Protected paths = read-only binds, Landlock = outer fence only.
3. **Landlock rules on files** accept only file rights; mask per path type.
4. **Overlay `--overlay-src` order in bwrap is the reverse of the kernel's `lowerdir`.** Test it.
5. **Directory renames** inside the overlay may return `EXDEV`; tools usually fall back to copy+delete, so the diff shows a big add+delete. That's correct, and policy may flag it.
6. **Copy-up cost:** appending to a large file copies it whole into the upper. Measure; consider excluding huge binaries from the workspace or using the reflink backend later.
7. **Verification on empty fixtures is meaningless;** seed matches (§10.2).
8. **Leakage via shared NL2Bash ancestry** between NL2SH-ALFA train/test and `neulab/tldr`; dedupe across all sources (§10.5).
9. **HF mirrors can mislabel licenses;** check upstream.
10. **Never expose an approve tool** to the model's MCP session; test the tool list.
11. **sed `e`/`w` flags, awk `system()`, find `-exec`/`-delete`** turn "read-only" tools into executors; typed tools must construct these commands, never accept raw scripts.
12. **The host can't see the merged view;** commit and host-side reads go through the layer resolver (§5.8), which must never follow symlinks.
13. **The retrieval KB and eval can legitimately overlap** (tldr-pages is generic usage, not task answers). That's what the retrieval ablation measures; it's not leakage. Leakage is eval *task* content in training data or hand-written KB entries tuned to eval tasks.

---

## Appendix A: reference code

- `landlock_shim.py` (in repo root, to be moved to `lilguy/sandbox/landlock.py`): verified on ABI 7. It blocks unlink/truncate/rmtree outside granted trees and TCP connect. It also demonstrates the "can't carve holes" limitation.
- v0.1 modules reused: `digest.py` (extend), `memory.py` (interface kept), `eval.py` (harness structure), `tasks.json` (regression suite).
