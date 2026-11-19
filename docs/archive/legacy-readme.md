# lilguy

**Can a tiny model run a shell if everything except judgment lives outside its weights?**

lilguy is a scaffold and eval harness built to test that bet. The model's only job is
mapping *(goal, state, observation) → next action*. Command knowledge, project
conventions, syntax validity, output parsing and safety are all handled by
deterministic code around it. The model is meant to be a fuzzy router between
retrieval, templates and verifiers, not a store of facts.

Status: v0.2 foundations are being implemented phase by phase; see [PROGRESS.md](PROGRESS.md).
The v0.1 harness is preserved as a regression baseline: all 12 tasks pass with a scripted
oracle and an agent that does nothing fails all 12. No model result is claimed.
The Linux sandbox backend is implemented and exercised on disposable fixtures.
`sandbox-run` previews effect-policy decisions without committing the workspace.
Full MCP integration, approval CLI, retention and model evaluation remain incomplete;
the legacy model runner is still unsandboxed.

---

## Architecture

```
            ┌──────────── memory.py ────────────┐
 goal ──►   │ global snippets + .lilguy/ project │──► CONVENTIONS ─┐
            └────────────────────────────────────┘                 ▼
 state (cwd, step n/N) ─────────────────────────────────────►  prompt  ──► model ──► grammar.gbnf
 history (last 4 full, older as one-liners) ────────────────►     ▲                       │
                                                                  │                       ▼
            digest.py ◄── shell.py ◄── policy.py ◄──────────── action {run|ask|done, arg, expect}
     exit, tags, clipped     bash per cmd,   deny / confirm / allow
     streams, outcome        cwd carried
```

| Module | Responsibility |
|---|---|
| `grammar.gbnf` | Constrains every turn to one JSON action (passed to llama-server's `grammar` field) |
| `actions.py` | Tolerant parsing for grammar-free servers |
| `memory.py` | Keyed token-overlap retrieval with a relative score cutoff; project conventions get a boost |
| `digest.py` | Raw output → `exit=1 tags=ENOENT(path)` + deduped, clipped stderr/stdout + an outcome label |
| `policy.py` | Regex deny/confirm/allow layer |
| `shell.py` | One bash process per command with a minimal env, cwd tracked explicitly, timeout kills the process group |
| `agent.py` | The loop, history compression, prediction-mismatch notes |
| `eval.py` | Fresh temp dir per task: setup → agent → check; writes trajectories to JSONL |
| `cli.py` | Interactive mode: you approve confirm-level commands and answer the model's questions |

### Action space

```json
{"action": "run|ask|done", "arg": "<command | question | summary>", "expect": "ok|output|fail"}
```

`expect` is the model's prediction of the result. When it gets success vs. failure
wrong, the next prompt says `NOTE: you expected ok, got fail`. That gives the model
a cheap self-correction signal, and the mismatch rate doubles as a calibration
metric.

---

## Quick start

Python 3.11+; Linux is required for the sandbox capability checks. The existing
v0.1 loop is stdlib-only; packaging declares the dependencies for the v0.2 MCP/data work.

```bash
uv venv
uv pip install -e '.[dev]'

# Host capability checks (nonzero means exec prerequisites are incomplete)
.venv/bin/lilguy probe
.venv/bin/lilguy probe --json

# Offline tests, including all 12 oracle and 12 null-agent controls
.venv/bin/python -m pytest -q
.venv/bin/ruff check lilguy tests

# Preview one sandboxed command; effects are discarded by default, never committed
.venv/bin/lilguy sandbox-run --workspace ~/proj --cmd 'find src -type f -name "*.py"'

# Keep a session to continue it and to review anything that needs approval
.venv/bin/lilguy sandbox-run --workspace ~/proj --keep --cmd 'make'        # prints the session id
.venv/bin/lilguy sandbox-run --session <id> --cmd 'make test'              # continue it
.venv/bin/lilguy diff <id>                                                 # what changed (in the sandbox only)
.venv/bin/lilguy approve <id>              # shows the changes; type y to approve exactly those
.venv/bin/lilguy deny <id> [--discard]     # roll back the step that asked, or drop the session
.venv/bin/lilguy commit <id>               # write the reviewed changes into ~/proj (journaled)
.venv/bin/lilguy undo [<commit-id>]        # list or undo commits (refuses if you edited since)
.venv/bin/lilguy sessions [--prune DAYS]   # list kept sessions; delete idle ones

# Long commands keep running while they make progress (new output or files). A step that sits
# idle is stopped; one that is busy without progress is paused and you are asked whether to continue.
# Stopped steps keep their partial work for review. Tune with --idle-timeout / --stall-timeout /
# --timeout (hard limit, default 600 s). Nothing reaches ~/proj without lilguy commit.

# Trusted v0.1 regression harness only (NOT sandboxed)
.venv/bin/lilguy eval --backend scripted --out results.jsonl

# Legacy model eval (NOT sandboxed; do not use downloaded dataset commands)
llama-server -m model.gguf --port 8080 -c 4096
.venv/bin/lilguy eval --backend llamacpp --url http://127.0.0.1:8080 -v

# Legacy interactive mode: explicit acknowledgement that commands run on the host
.venv/bin/lilguy run --unsafe-legacy "find the 3 largest files under src" --cwd ~/proj
```

`python -m lilguy` exposes the same commands. `python -m lilguy.eval` remains
available for the trusted legacy harness. The new `run` command refuses execution
without `--unsafe-legacy`; this is a warning/opt-in, not isolation.
The sandbox preview command has no commit switch. Journaled commit/recovery/undo
exist as tested Python primitives, not yet as a complete approval CLI or MCP service.

`LILGUY_BWRAP=/path/to/bwrap` selects an alternative non-setuid bubblewrap for the probe.
Capability failures include their reason; cgroup delegation failure is warning-only,
with rlimits required in the future backend. Tests do not fetch datasets or call models.

`--no-grammar` works with any OpenAI-compatible server.

### Task format (`lilguy/data/tasks.json`)

```json
{
  "id": "mkdir_recover",
  "goal": "Copy msg.txt to out/reports/2026/msg.txt.",
  "setup": "echo hello > msg.txt",
  "check": "cmp msg.txt out/reports/2026/msg.txt",
  "expect_final": "done",
  "allow": [],
  "max_steps": 10,
  "oracle": [{"action": "run", "arg": "...", "expect": "ok"}, {"action": "done", "arg": "..."}]
}
```

### Conventions format (`.lilguy/conventions.jsonl` in a project)

```json
{"keys": ["test", "tests", "check"], "text": "This project runs its tests with `make check`."}
```

---

## Design review

I reviewed v0.1 against its own thesis and probed the weak spots directly rather
than reasoning about them. The findings are ordered by how badly each one
undermines the core question.

### 1. The eval measures copying, not competence (critical)

The global snippets were written alongside the tasks, and I tuned retrieval
against those same tasks. For **10 of 12 tasks, the top retrieved snippet is
essentially the answer**. `approved_delete` retrieves `rm -- *.tmp`, which is
exactly what the oracle runs. `csv_filter` retrieves the awk command with
`"x"` where the answer has `"eng"`.

A model that passes this suite has shown that it can fill a template slot. That's
part of the thesis, but only part. The suite can't tell "lilguy works" apart from
"the snippets were written for these tasks."

**Fix:** split knowledge and tasks. Write snippets from a neutral source (real tldr
pages) and freeze them before writing tasks. Keep a held-out task set nobody tunes
against. Report results with and without retrieval: the gap between the two is the
number that tests the thesis.

### 2. The policy layer is decorative (critical)

Probing `policy.check` with destructive commands:

| Command | Verdict |
|---|---|
| `rm -rf build` | confirm ✓ |
| `find . -name '*.o' -exec rm {} \;` | **allow** |
| `ls \| xargs rm` | **allow** |
| `python3 -c 'import shutil; shutil.rmtree("src")'` | **allow** |
| `r''m -rf src` | **allow** |
| `> src/main.c`, `truncate -s0 …` | **allow** |
| `mv src /tmp/gone` | **allow** |

Regex can't classify shell commands; the language is too expressive. Worse, the
evals reward models for staying inside the regex, which teaches evasion as easily
as caution.

**Fix:** stop classifying commands and verify effects instead. Run each command in
a copy-on-write overlay (bubblewrap + overlayfs, or a container snapshot), diff the
filesystem afterwards, and treat the diff as what needs approving: "this deleted
14 files under `src/`, commit?" Approval then covers exactly what happened, whatever
syntax produced it, and rollback is free. Keep the regex only as a cheap first pass
for network and privilege commands, which a filesystem diff can't catch.

### 3. JSON makes the model escape shell (high)

Inside a JSON string, the awk command becomes:

```
"arg": "awk -F, 'NR>1 && $2==\"eng\" {print $1}' people.csv"
```

The model has to track two quoting systems at once, JSON and shell. That's
precisely the kind of bookkeeping small models get wrong, and the grammar can only
guarantee the JSON is valid, not that the unescaped shell is what was meant.

**Fix:** use a line-oriented format with the command raw:

```
expect: ok
run: awk -F, 'NR>1 && $2=="eng" {print $1}' people.csv
```

A grammar for this is simpler, there's no escaping, and putting `expect` first
makes the model commit to a prediction before writing the command.

### 4. Checks verify the goal, not the absence of collateral damage (high)

`check` scripts test end state. Only a few tasks check for collateral damage. A
model that achieves the goal while also wrecking unrelated files mostly passes.

**Fix:** snapshot the task directory before and after, and score unexpected changes
as a separate metric (or an automatic fail). This uses the same diff machinery as
the overlay in #2.

### 5. The suite is too small and too easy to find a size cliff (medium)

12 tasks, mostly solvable in one command, run at temperature 0: one flipped task
moves the score 8 points. That's no statistical power, and almost nothing exercises
the multi-step reasoning where small models should break.

**Fix:** grow to 100+ tasks, weighted toward recovery chains (2–4 failures before
success), ambiguity, misleading conventions and noisy output. Run `--repeat` at
temperature > 0 and report pass@k with confidence intervals.

### 6. `ask` ends the episode (medium)

With no human in evals, asking ends the episode. So we can test *whether* the model
asks, but not whether it asks a *good* question or uses the answer. Asking is
also unpenalized when it isn't needed, apart from the `expect_final` check.

**Fix:** give tasks an optional `answers` map (or a small user-simulator model) so
episodes can continue after a question. Score unnecessary asks on tasks that
needed none.

### 7. Smaller issues

- **Prompt format is bespoke.** Zero-shot small models have never seen it, so baselines will
  understate them. That's fine if fine-tuning is the plan; just remember it when reading
  zero-shot numbers.
- **No efficiency metrics.** The thesis is that small models are *cheaper*. Tokens in and out
  per step and latency should be recorded alongside pass rate.
- **Env vars don't persist** across steps (`export`, `source venv/bin/activate`). That's
  deliberate, but some real workflows need it. A persistent shell with sentinel framing is
  the upgrade path.
- **The digester is English and coreutils-centric.** Tags come from regexes over GNU messages,
  and the last match wins, which is usually but not always the root cause.
- **Mismatch is binary** (fail vs. not-fail). `ok` vs. `output` confusions aren't tracked.

### What holds up

- **Splitting the work.** Grammar, digester, retrieval, policy and explicit state each
  remove a whole class of errors from what the model must handle.
- **The digester.** Turning 100 lines of output into `exit=1 tags=PY_EXC(KeyError)`
  plus clipped context is the highest-leverage piece, and it's model-independent.
- **`expect` as a cheap metacognition signal**, worth keeping and better placed before the
  command (see #3).
- **Trajectories as JSONL**: eval runs double as distillation data.
- **Real negative controls**: the null agent fails every task.

---

## Roadmap

In priority order. The first three determine whether any result means anything.

1. **De-leak the eval:** neutral snippets, held-out tasks, with- vs. without-retrieval ablation
2. **Overlay execution:** filesystem-diff approvals and collateral-damage scoring (#2, #4)
3. **Line-oriented action format:** no JSON escaping (#3)
4. **Model-size sweep:** 0.5B / 1.5B / 3B / 7B on the expanded suite with pass@k and token costs
5. **Ask continuation:** scripted answers per task (#6)
6. **Distill and RL:** strong-model trajectories → SFT on the small model → RL against the check scripts
7. **Pluggable memory:** put a real convention store with validation behind `ConventionStore.retrieve`
