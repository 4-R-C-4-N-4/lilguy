# lilguy: scope of work

**Version:** 1.0 draft · **Owner:** Ivy · **Companion docs:** [`IMPLEMENTATION.md`](IMPLEMENTATION.md) (how), [`spec.md`](spec.md) (sandbox design), [prototype review](../archive/legacy-readme.md) (historical)

---

## 1. Purpose

lilguy tests one hypothesis:

> **A very small language model can do useful shell work if knowledge, syntax, output parsing and
> safety live outside its weights.**

This document defines what will be built to test that, in what order, and how we'll know each
part is done. It's written to be handed to an implementing agent alongside `IMPLEMENTATION.md`.

### Success looks like

1. A small model (≤ 4B parameters, target ≤ 1.5B) completes **≥ 70%** of a held-out task suite
   through lilguy-sh, at **< 10%** of the latency and cost of a 30B+ reference model.
2. **Zero** destructive effects reach the real workspace without either matching policy or human
   approval, across the full bypass corpus and all eval runs.
3. A measured answer to "how much does the scaffold contribute?": pass rate with vs. without
   retrieval, typed tools and grammar, at each model size.

These targets are hypotheses, not commitments. Phase 7 may show they're wrong; that's a valid result.

---

## 2. Background and decisions already made

| # | Decision | Source |
|---|---|---|
| D1 | The model never gets a raw shell. It talks to an **MCP server (lilguy-sh)** that exposes typed tools plus a sandboxed `exec`. | Spec §1 |
| D2 | Safety is enforced on **effects, not syntax**: copy-on-write overlay, diff, policy, commit. | Spec §5–6 |
| D3 | Typed tools are the primary interface; `exec` is the escape hatch. | Spec §5B |
| D4 | The tool set is chosen **by measured coverage** of real command data, not by guesswork. | Discussion, 2026-11-17 |
| D5 | Dataset filtering is **parse → translate → verify by execution** first, classifiers second. | Discussion, 2026-11-17 |
| D6 | Knowledge comes from neutral sources (tldr-pages) frozen before eval tasks are written. | README review #1 |
| D7 | Linux only, unprivileged (no root), self-hosted. Inference via llama.cpp. | Spec §2 |
| D8 | Policy runs per step; changes are **committed once, at the end of the task**. | Ivy, 2026-11-17 |
| D9 | Personal shell history is used for **coverage analysis only**, never for training. It never leaves the machine. | Ivy, 2026-11-17 |
| D10 | The workspace appears inside the sandbox at its **real host path** (configurable). What the model sees is decoupled from this: tool arguments, prompts and observations use workspace-relative paths, and the digester rewrites the absolute prefix in command output. Revisit if the P7 path ablation shows the mount path matters. | Ivy, 2026-11-17 |
| D11 | The model family is chosen **after a zero-shot screen** of several families (first step of P7). | Ivy, 2026-11-17 |

---

## 3. In scope

### C1. lilguy-sh: sandboxed MCP shell server

- Capability probe for the host (user namespaces, overlay in userns, bubblewrap version and setuid status, Landlock ABI, cgroup delegation).
- `exec` running in bubblewrap with a **stacked overlay** (one layer per step), private namespaces (mount, pid, net, ipc, uts), empty HOME, scrubbed environment, resource limits.
- Diff of each step and of the whole session, computed by walking overlay upper layers.
- Policy engine (`policy.yaml`): reject / require approval / auto-commit, evaluated per step and per session.
- Approval channel outside the model's MCP session.
- Commit to the real workspace with an undo journal, crash recovery and conflict detection; discard; per-step rollback.
- Protected paths enforced at mount level (read-only binds), independent of policy code. (Landlock is the outer fence only: it can't protect subpaths of a writable tree; verified.)
- Append-only audit log per session.

### C2. Typed tool set

- Tier 1 files, Tier 2 text pipeline, Tier 3 archives, Tier 4 system info, Tier 5 dev (git without network, `task.run`), Tier 6 `exec`. Exact membership is **gated on the coverage report (C4)**.
- Every typed tool executes through the same sandbox and overlay as `exec`, so all changes share one diff and one policy.
- Typed tools never pass raw scripts to interpreters that can execute or write (no raw `sed` scripts, no `awk`, `find` without `-exec`/`-delete`); arguments are injection-safe (`--`, `-e`).
- `task.run(name)` resolves named tasks from project conventions.

### C3. Agent loop and action format

- Port the v0.1 loop to use lilguy-sh as an MCP client.
- Line-oriented action envelope (no JSON escaping of shell commands); GBNF grammar generated from the live tool schemas.
- Output digester (v0.1 `digest.py`, extended with diff and policy summaries).
- Convention retrieval behind a pluggable interface (`ConventionStore`), seeded from tldr-pages and project `.lilguy/conventions.jsonl`.

### C4. Data pipeline

- Ingest: NL2SH-ALFA (train + test), `neulab/tldr`, tldr-pages; local shell history for coverage only (D9).
- Parse gold commands to ASTs; extract utilities, flags, pipes, redirects.
- **Coverage report:** utility and flag frequencies, cumulative coverage curve, coverage of a given `toolset.yaml`.
- Translator: AST → typed tool calls for the supported subset.
- Execution verification on generated fixture filesystems.
- Labels: quality (instruction/command consistency), risk (from observed effects), routing for untranslatable examples (`exec` / `ask` / `drop`).
- Deduplication and leakage control across all splits; held-out-by-utility split.

### C5. Evaluation

- Task suite expanded from 12 to **≥ 150** executable tasks: single-step (from verified data), multi-step recovery, convention-following, ask-vs-act judgement, policy interactions.
- Separate **held-out** set nobody tunes against.
- Metrics: pass@1 with 95% CI (repeats at temperature > 0), steps, expect-mismatch rate, invalid actions, policy pending/reject counts, unnecessary asks, tokens in/out, wall time, collateral damage (unexpected diff entries).
- Ablations: retrieval on/off, typed tools vs. `exec`-only, grammar on/off, **path presentation** (relative / real absolute / short `/ws` mount); model-size sweep.
- Path-error metrics: share of failed steps caused by a wrong path (ENOENT on a model-supplied path, wrong cwd, path outside the root).

### C6. Training (first round)

- SFT on verified instruction → tool-call pairs plus boundary examples (`exec`, `ask`), for a ladder of 3–4 model sizes from the family picked in P7 (D11).
- Export to GGUF; re-run the full eval.

---

## 4. Out of scope (this round)

- Multi-step trajectory distillation from large models (Nemotron-Terminal-Corpus, own trajectories) and RL. Planned for round 2; the audit log format must support it.
- Container/microVM backends (spec option K), reflink backend (D) and snapshot backstop (E). The interface must allow them.
- macOS / Windows.
- Network access from inside `exec` (allowlist proxy).
- Long-running or interactive processes (servers, TUIs).
- Multi-agent shared sessions.
- A UI beyond CLI approval prompts and MCP elicitation.

---

## 5. Phases and acceptance criteria

Phases are ordered by dependency. **P1 and P4 can run in parallel.** P4's coverage report gates the
tool set built in P3. P6 needs both the sandbox (P1, to run gold commands safely) and typed tools
(P3, to verify translations).

```
P0 ─┬─► P1 ─► P2 ─► P3 ─┬─► P5 ──┐
    │                   │        ├─► P7 ─► P8
    └─► P4 ──(gate)─────┴─► P6 ──┘
```

Relative size: **S** ≈ days, **M** ≈ 1–2 weeks, **L** ≈ 2–4 weeks of focused work for one engineer
plus agent. These are rough, to help with ordering, not commitments.

| Phase | Size | Deliverable | Acceptance criteria |
|---|:-:|---|---|
| **P0 Foundations** | S | Repo restructure, CI, capability probe (`lilguy probe`) | Probe prints a pass/fail table on the target machine and exits non-zero if `exec` isolation is incomplete. Existing v0.1 tests still pass. |
| **P1 Sandbox exec + diff** | L | bwrap backend, stacked overlay, namespaces, limits, per-step and session diff, step rollback, discard | Bypass corpus (spec §12) items 1–9, 11–15 produce the correct diff or are contained. Overlay behaviour tests pass (delete, rename dir, hardlink, opaque dir, large-file copy-up). p50 `exec` overhead < 150 ms. |
| **P2 Policy, approval, commit** | L | Policy engine, approval channel, commit with undo journal, crash recovery, conflict detection, protected-path mounts, audit log | Whole bypass corpus passes. `kill -9` at any point during commit leaves the workspace either fully pre- or fully post-commit after recovery. Protected paths can't be modified even with the policy engine disabled. Property test: commit(diff) ≡ merged view. |
| **P3 Typed tools** | M | Tools per frozen `toolset.yaml`, `task.run`, MCP server | Each tool has schema, validation tests and an equivalence test against its bash counterpart. Typed and `exec` changes show up in one session diff. |
| **P4 Data: ingest + coverage** | S | Loaders, AST parser, coverage report, draft `toolset.yaml` | Report covers all sources; parse-failure rate reported per source. **Decision gate:** Ivy signs off on the tool set before P3 freezes it. |
| **P5 Agent loop** | M | MCP client loop, action envelope, generated grammar, digester v2, retrieval interface | v0.1's 12 tasks pass with the scripted oracle through lilguy-sh, with oracles and expectations updated for effect-based policy (e.g. `policy_redirect` deletes 1 file, which is now under the auto-commit threshold, so it must be rewritten to trip a rule). Grammar is regenerated automatically when tool schemas change. |
| **P6 Data: translate + verify + label** | L | Translator, fixture generator, execution verifier, labellers, deduped splits | ≥ 95% of pairs marked verified really are equivalent (manual audit of 200). Zero exact or near-duplicate leakage between train and any eval split. Dataset card with counts per stage. |
| **P7 Eval + baselines** | M | ≥ 150-task suite + held-out set, metrics, ablations, **family screen**, then zero-shot sweep across sizes of the chosen family | Null agent fails 100%; oracle passes 100%. Family-screen report → Ivy picks the family. Baseline report with CIs for every model × ablation cell. |
| **P8 SFT round 1** | M | Fine-tuned models (GGUF), training config, re-eval report | Report compares fine-tuned vs. zero-shot per cell; success criteria in §1 evaluated honestly. |

---

## 6. Deliverables

| Artifact | Format |
|---|---|
| `lilguy` Python package (agent, data, eval) and `lilguy-sh` MCP server | Code + tests in one repo |
| `toolset.yaml` | Signed-off tool set with coverage numbers |
| `policy.yaml` default | With documented rationale for each threshold |
| Datasets: `sft_train`, `sft_val`, `eval_tasks`, `eval_heldout` | JSONL + dataset card (sources, licenses, counts per pipeline stage) |
| Reports: coverage, baseline, fine-tune | Markdown with tables and plots |
| Models | GGUF + model card |
| Updated `spec.md`, `README.md` | Kept in sync with what was built |

---

## 7. Constraints and assumptions

- **Host:** Linux kernel ≥ 6.2 (Landlock truncate control), ≥ 5.11 minimum for overlay in user namespaces; bubblewrap ≥ 0.11, installed **non-setuid**; unprivileged user namespaces allowed (on Ubuntu ≥ 23.10, needs an AppArmor profile for bwrap); cgroup v2 with user delegation (systemd).
- **Python** ≥ 3.11. Minimal dependencies; each new one justified in the PR.
- **Inference:** llama.cpp `llama-server` (local). A larger reference model may be used for evaluation baselines and labelling only.
- **Data never leaves the machine** when it includes personal shell history.
- **Licenses:** each dataset's license is recorded and re-checked against its original source (e.g. tldr-pages content is CC BY 4.0 upstream, whatever an HF mirror says).

---

## 8. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Small models can't reach useful pass rates even with the scaffold | Hypothesis fails | That's a result. Ablations show which scaffold parts matter; report it. |
| Host lacks unprivileged userns / overlay-in-userns | `exec` unusable | Probe fails loudly; typed-tool-only mode still works; reflink backend in round 2. |
| Typed tool set too narrow → model over-uses `exec` | Safety and accuracy suffer | Coverage-driven tool set; track `exec` share per task as a metric. |
| Dataset gold commands are wrong or nondeterministic | Bad SFT data | Execution verification; manual audit; drop unverifiable examples from SFT. |
| Train/eval leakage via shared NL2Bash ancestry | Inflated scores | Normalised-command and instruction-similarity dedupe across all splits (P6 criterion). |
| Approval prompts too frequent in real use | Rubber-stamping | Tune thresholds from eval logs; report pending-rate per task type. |
| Scope creep into a general agent platform | Delay | §4 is binding for this round. |
| Overlay quirks in real toolchains (directory renames, large-file copy-up, inode-sensitive tools) | Breakage in daily use | P1 test list covers known cases; run 2–3 real projects through `exec` before P2 sign-off. |
| bubblewrap ≥ 0.11 overlay flags, AppArmor userns limits and cgroup delegation untested on the target host (only the kernel overlay path was verified) | P1 blocked | P0 probe runs first and reports exactly what's missing. |

---

## 9. Open decisions (owner: Ivy)

| # | Question | Needed by |
|---|---|---|
These need data that doesn't exist yet. The implementing agent prepares the evidence and stops for Ivy at each gate.

| # | Question | Evidence prepared by | Needed by |
|---|---|---|---|
| Q1 | Final tool set | Coverage report (P4), incl. coverage of your own history | End of P4, before P3 freezes |
| Q2 | Model family | Family screen (start of P7) | Before the P7 size sweep |
| Q3 | Policy thresholds (start from spec §9 defaults: 20 deletes, 50 modified, 50 MB per session) | Pending/reject rates from P2 tests and real-project runs | End of P2 |
