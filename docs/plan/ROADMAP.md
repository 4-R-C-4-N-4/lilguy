# lilguy's model: a small model whose home turf is lilguy

This is the plan and its gates. Current progress, results and open decisions: [STATUS.md](../STATUS.md).

## Goal

Train a small language model (target ≤ 1.5B parameters, cap 4B) whose home turf
is lilguy. Given an everyday shell request in a workspace, it works through
lilguy's interface, and only that interface:

- it uses typed tools and sandboxed shell commands, and reads what comes back;
- it asks when the request is ambiguous;
- it stops honestly, and never claims success after a failure.

It completes **≥ 70 %** of a held-out suite of everyday shell tasks, with **zero**
destructive effects reaching the real workspace without policy or human
approval. It runs locally at **< 10 %** of the latency of a 30B reference, and
ships as `lilguy do "<request>"` running on llama.cpp.

These are the targets in [SCOPE.md](../reference/SCOPE.md), restated for this goal.

### What "everyday shell work" means here

Requests at the level of the tldr pages, not shell wizardry, for example:

- find the `.log` files over 10 MB and delete the ones older than a week;
- rename these photos by date;
- count the lines of Python in this repo;
- replace `foo` with `bar` in every config;
- make the scripts in `bin/` executable;
- write a small script that backs up this folder;
- "which file here is the biggest?" (read-only, answered in `done`).

### lilguy and the model are two different things

- **lilguy** is the system around the model. It provides:
  - the sandbox, where every command runs on a copy-on-write layer over the
    workspace;
  - the tools, each running inside that sandbox;
  - policy and human approval;
  - commit and undo;
  - the agent loop that shows the model the request and tool output, and runs
    what the model chooses.

  Safety lives here, not in the model's weights. Any model can drive it.
- **The model** is the small LLM that picks the next action. It never touches a
  shell directly. It writes one action per turn, and lilguy executes it in the
  sandbox.

### What "trained on the lilguy interface" means

1. **One interface, one definition.** The system prompt, tool list, action
   syntax, observation format and outcome tags are defined in one module and
   carry a version number. The agent loop, MCP server, data generator,
   evaluator, trainer and model server all import it. Every training row,
   evaluation result and model card records the interface version. Changing
   the interface means regenerating the data.
2. **Training data is recorded through lilguy.** Every training example is a
   trajectory produced by, or replayed through, the real agent loop and
   sandbox. An example is kept only if its effects check out. The model trains
   on exactly what it will see at runtime, including lilguy's own outcomes:
   - `pending` (needs human approval);
   - `rejected` (by policy);
   - `TIMEOUT` and `STALLED`;
   - tool errors.
3. **It learns lilguy's habits, not just bash.**
   - Look before acting.
   - Prefer a typed tool where one exists, and use a shell command otherwise.
   - Read the observation before claiming success.
   - Investigate a failed step instead of declaring `done`.
   - On `pending`, stop and summarise for the human.
   - On `rejected`, do not retry the same thing.
   - Ask when the target is ambiguous. (Superseded by interface v2: `ask` only when an input is
     missing.)

### How the factory is calibrated (Ivy, 2026-11-20)

This balance is the premise of the experiment:

1. **Assess the model's capability with specific tasks.** Each development task tests one simple,
   explicit job through the real lilguy interface, graded on what actually happened.
2. **When tasks are inconsistent or fail, consider refining the interface.** Before asking the
   model to learn something harder, ask whether lilguy can take that burden instead. Examples so
   far:
   - v2: the trusted plan and diff replaced the model's own change report;
   - v3: the quoted command output replaces the model's paraphrased answer, and an `ask` mode in
     which lilguy rejects writes replaces guessing "read-only" from wording.

   The model's job shrinks to choosing the right tool. Training and data changes are for the
   failures that remain.

### Interface versioning (adopted from v3 on)

Every refinement of what the model sees or what its actions mean is a new interface version, not
an in-place edit:

- **A plan before any change.** `docs/plan/INTERFACE-Vn.md` states the failure evidence (task
  traces), the change, its consequences and their effort, and Ivy's approval.
- **One version constant.** `INTERFACE_VERSION` in `lilguy/protocol.py` names the version, with a
  golden prompt per version. Every training row, evaluation identity and model card records it.
- **Earlier versions stay reproducible.** Their prompts, grammars, graders and corpus revisions
  still regenerate byte-identically from the tree.
- **Data is regenerated for the new version** through the real loop and replay, and must pass the
  split gate.
- **Held-out is recalibrated before any model runs on it.** The scripted solution must pass and
  the null control must fail under the new version, re-pinned with Ivy's authorisation.
- **Scores across versions are references, never matched comparisons.** A gate compares only
  artifacts scored on the same version and evaluation fingerprint.

## What exists today

| Area | Path | State |
|---|---|---|
| Sandbox: overlays, Landlock, cgroups, liveness, network setting | `lilguy/sandbox/` | Done (P1/P2). Live bypass corpus passes. |
| Policy, approval, commit, undo, audit | `lilguy/policy/` | Done (P2). Human-only approval. |
| MCP tool server | `lilguy/mcp_server.py` | Tracer only: `fs.find`, `fs.read`, `fs.edit`. No shell command tool yet. |
| Tool definitions | `toolset.yaml` | Draft chosen by measured coverage, not frozen. `pipe` and text tools defined but not served. |
| v0.1 agent loop | `lilguy/agent.py`, `actions.py`, `digest.py`, `memory.py` | JSON `run`/`ask`/`done` against the old unsandboxed path; needs porting to lilguy-sh. |
| Public command data | `lilguy/data/` | 72,244 unique commands cached; licences unverified, so none of it is training data yet. |
| Pilot tooling | `dev/small_model_eval.py`, `dev/small_model_corpus.py`, `dev/sft_pilot.py`, `dev/sft_server.py` | Built for a config-edit tracer; reusable (Appendix A). |
| Pilot model | Qwen3.5-0.8B + 41 MB LoRA | 7/7 on the sandboxed tracer tasks with files open. 0/6 when it must find files itself; it then says `done` after failed edits. |

Test counts and step progress: [STATUS.md](../STATUS.md). Pre-v1 history: [archive/PROGRESS.md](../archive/PROGRESS.md).

## What the pilot taught (rules for the real corpus)

- **Train in the exact runtime protocol.** Pilot 4 kept repeating a correct
  edit because training never showed the evaluator's observation turn.
- **Build contrast pairs so shortcuts fail.**
  - Pilot 3 learned "edit if the request names the file read last". Fixed by
    reading files in both orders.
  - Pilot 4 learned "ask unless a path is named". Fixed by same-wording pairs
    where only the workspace decides.
- **Failures must be in the training data.** Pilot 5 said `done` after every
  failed edit, because every edit in training succeeded.
- **The decision is one token among many.** Under a plain mean loss it stays
  underfit while the loss reaches about 0. Weight the decision tokens, and set
  training length by fitting the training split, never by validation.
- **Score episodes in the sandbox.** Single next-action accuracy (96/96)
  overstated what a model does in a real episode.

## Step-by-step plan

Each step names its deliverables and a gate; the gate says when the step is
done. Steps 1–3 build the interface, 4–5 measure, 6–7 train, 8 ships. Earlier
gates must pass before later steps start, except where a step says it can run
in parallel.

### Step 1: Freeze interface v1 (done, 2026-11-18)

Status: `lilguy/protocol.py`, with `INTERFACE_VERSION = 1`. It sits at the top
level rather than in `lilguy/agent/`, because the v0.1 `lilguy/agent.py`
module still exists and a package would shadow it. What was built and
verified:

- The prompt is frozen by a golden file, `tests/unit/interface_v1_system_prompt.txt`.
  Any change fails the test until the version is bumped.
- 36 unit tests cover parsing and rendering (quotes, backslashes, heredocs,
  multi-line values, 18 malformed forms, smuggling attempts), tool-argument
  typing, observations and the grammar.
- The served tools are `run` plus `fs.list`, `fs.find`, `fs.read`, `fs.grep`
  and `fs.edit`; their definitions come from `toolset.yaml`.
- Arguments are kept in the tool's own order, which is the order the grammar
  accepts. Data generators must render actions with `render_action(action, tools)`.
- Live check (`python -m dev.grammar_check`): a `llama-server` built from our
  own Qwen3.5-0.8B checkpoint (converted to 8-bit GGUF; this also showed that
  this llama.cpp build supports Qwen3.5, which step 8 needs) accepted the
  grammar, and 8/8 constrained replies parsed.
- The live check changed the prompt twice before it was frozen:
  - with `<placeholder>` forms, the untuned model copied a placeholder as its
    command in 2 of 8 replies;
  - with a concrete example question, it copied that question in 3 of 8.

  The frozen prompt gives concrete examples only for `run` and `tool` and
  describes `ask` and `done` in words. One reply still copies the `run`
  example. Expect some example-copying in the untuned step 5 baselines.
- Deviation from the gate below: the pilot evaluator now takes its observation
  wrapper from `lilguy/protocol.py`. The pilot's JSON actions are replaced
  wholesale by the step 3 loop rather than ported.

Deliverables:
- `lilguy/protocol.py`, the single definition:
  - `INTERFACE_VERSION`;
  - a system prompt built from the served tools;
  - action rendering and parsing;
  - observation rendering;
  - outcome tags.
- A GBNF grammar generated from the same definition, for constrained decoding
  in llama.cpp.

The action syntax is a line-oriented envelope (SCOPE C3), so shell text needs
no JSON escaping. As built:

```
run
find . -name '*.log' -size +10M -mtime +7 -delete
```
```
tool fs.read
path: notes/todo.md
```
```
tool fs.edit
path: cfg/app.ini
old: retry=2
new: retry=5
```
```
ask
Which config, staging/app.ini or production/app.ini?
```
```
done
Deleted 3 logs over 10 MB older than a week; see the diff.
```

A value of several lines is written `name <<<`, then the lines, then a `>>>` line.

Observations: `exit=N`, the digested stdout and stderr (already truncated and
path-rewritten by `digest.py`), `changes: <op> <path>; …` (at most 20 entries,
then "and N more"), then `policy: ok`, `policy: pending (<reason>)` or
`policy: rejected (<reason>)`. Tags such as `TIMEOUT` go on the `exit=` line.

Gate:
- Round-trip and adversarial parse tests pass: quotes, backslashes, heredocs,
  multi-line scripts, empty or garbled actions, and an action that tries to
  smuggle a second action.
- The pilot's evaluator and corpus code switch to this module, and their
  tests pass.

### Step 2: Give the model the shell (P3)

Status: v1 scope decided; full safety acceptance passed 2026-11-22 (`reports/factory/check-24wjv4jd`, `ea4e654`, 18/18). Keep `run` and five typed
file tools. Defer separate `text.*` and `pipe`: `run` already supports pipelines,
and changing the interface would invalidate candidate comparisons. Any future
typed additions require a versioned interface change.

Safety acceptance: `tests/bypass/test_v1_run_corpus.py` sends the bypass corpus
through the model-facing v1 `run` tool (`factory check` stage `v1-bypass-corpus`).
All executed cases ended `pending` or `rejected`, or were blocked: an existing protected
path (`.git/`, `.env`) is mounted read-only, so the write fails with
`changes: none` and nothing is staged. In every case the real workspace and a host
canary are unchanged, a pending session refuses further steps, and no approval tool
is offered. An unrecognized policy decision is a tool error, and the shared loop
stops on any missing or malformed policy line. Corpus #17 was excluded from the
historical partial run because rsync was not installed. The full factory check
now requires rsync on the sandbox executable path and verifies the exact 18-case
JUnit roster, including #17. A missing dependency or missing case is a gate failure.
Fast12 is a development check, not a substitute for this acceptance gate.

Deliverables:
- `run` served by lilguy-sh: one shell command or short script per step,
  executed through `GuardedSession` exactly like `lilguy sandbox-run`
  (overlay, policy, liveness, per-session network setting).
- The five reviewed typed tools served from `toolset.yaml`: `fs.list`,
  `fs.find`, `fs.read`, `fs.grep` and `fs.edit`.
- `pending` and `rejected` outcomes returned to the model as observations.

Gate (SCOPE P3 acceptance):
- each typed tool has a schema, validation tests and an equivalence test
  against its bash counterpart;
- typed and `run` changes appear in one session diff;
- all required bypass-corpus cases run through `run` and are held for approval,
  rejected, or blocked before staging; none are silently committed. An excluded
  case keeps full acceptance open.

### Step 3: The agent loop on lilguy (P5)

Deliverables:
- `lilguy/loop.py`, an MCP client using `lilguy/protocol.py`, with:
  - an action budget;
  - stop rules (`done`, `ask`, `pending`, budget);
  - a **trajectory recorder** that saves every episode in the protocol format.
    That recorder is the training-data format.
- A prototype `lilguy do "<request>"` that takes any llama.cpp or
  OpenAI-compatible endpoint, ends by showing the diff, and hands over to the
  existing `lilguy approve` / `commit` flow.

Gate (SCOPE P5 acceptance):
- v0.1's 12 tasks pass with the scripted oracle through lilguy-sh;
- the grammar is regenerated automatically when tool schemas change;
- a recorded trajectory replays to identical effects.

### Step 4: The task suite and a frozen held-out set (P7)

This step can run in parallel with steps 2–3 once step 1's format is fixed.

Deliverables: `lilguy/eval/` with tasks. A task is:
- a request;
- a fixture-workspace builder;
- a grader on effects: exact diff, bytes and modes, untouched originals, plus
  the required `ask`, or the answer text for read-only questions.

Categories follow the target examples:
- find, inspect and count;
- edit and replace;
- rename, move and organise;
- conditional delete (approval path);
- permissions;
- archives;
- small scripts;
- ambiguous requests that call for `ask`;
- recovery from a failed step;
- read-only questions.

Size: ≥ 150 dev tasks and ≥ 100 held-out tasks.

Held-out rules:
- written from separate templates;
- hashed and frozen **before** any training data is generated;
- never used for tuning or failure analysis.

Gate:
- scripted oracle 100 %, null agent 0 %;
- leakage check tooling in place (template and near-duplicate).

#### 2026-11-19 — Held-out re-freeze

Reason: development evidence (a 35B reference model run on Fast12, dev's own
12-task smoke suite) exposed three grader false-negative defects, now fixed in
`dev/fast12.py`. The identical defects existed in the frozen held-out corpus's
equivalent template families. No model had ever been evaluated on the
held-out suite at that point, and no training data existed yet, so fixing the
graders and re-freezing carried no leakage risk.

Families changed in `dev/holdout_corpus.py` (10 tasks each):
- `holdout_h_recovery` — the grader required an error observation that the
  fixture never caused (the requested path existed; only the oracle erred on
  purpose), so a model acting correctly failed. The target file now lives one
  level below the path named in the request (its own natural subdirectory per
  variant), so a model must look or recover, but making a mistake first is
  no longer required to pass.
- `holdout_g_readonly` — `answer_contains` demanded a literal `key=value`
  string; replaced with an `answer_patterns` regex (mirroring Fast12's
  fix) that accepts free prose stating the right value while still
  rejecting a wrong or digit-superset value.
- `holdout_d_protected` — dropped the required literal word "protect" from
  `answer_contains`; an honest rejection report no longer needs that exact
  word to pass.

Old `dev/holdout_manifest.sha256`: `3d4162b2084a0860fbfac9e6bfb7977018563b80710e2354fc0898c012dad5ae`
New `dev/holdout_manifest.sha256`: `f9d408a410c03e7a54275b94522c745f5cfd11fba52ad342c9ab83e8d586325f`

Re-frozen via `dev/holdout_freeze.py` (validates and refuses to write on
failure). `tests/unit/test_holdout_corpus.py` gained regression tests per
family; the full unit suite (holdout, eval_gate, split_audit, factory_job,
fast12) and `ruff check` pass against the new pin.

#### 2026-11-20 — Held-out re-freeze for interface v2 (authorised by Ivy)

Reason: interface v2 changes what the terminal actions mean. `done` is no longer a report and
`ask` is only for being blocked, so v1 graders that expected an ambiguity question or a written
change summary would grade the wrong behaviour. No model had been run on the held-out suite, and
no training data was ever generated from it, so the re-freeze carries no leakage.

- Family B, `ambiguous_two_candidates`, became `missing_named_file`: the request names a file that
  is not in the workspace (two similar files are), so nothing may change and the reply must name
  the missing file (`ask` or `done` accepted).
- Answer-wording checks now apply only where an answer is the deliverable (no staged change, no
  policy stop). This uses the same `interface_grade` wrapper as the development suites; effect,
  terminal, policy and evidence checks are unchanged.
- `tests/sandbox/test_holdout_v2_live.py` calibrates all 100 tasks on fresh guarded fixtures:
  the scripted oracle passes and an immediate false `done` fails.

Old `dev/holdout_manifest.sha256`: `f9d408a410c03e7a54275b94522c745f5cfd11fba52ad342c9ab83e8d586325f`
New `dev/holdout_manifest.sha256`: `e10789bc44b20463af249f3a398bf7fc27b1a114fbcc9a719bc38465f8b8c93f`

### Step 5: Baselines through the real interface

Deliverables: untuned candidates run through lilguy on the dev suite (SCOPE
D11 family screen):
- Qwen3.5-0.8B, Qwen3.5-2B, one ~1.5B coder and SmolLM2-1.7B;
- the 30B reference.

The report gives pass rate with 95 % CI per category, unsafe attempts
(blocked by policy), invalid actions, tokens and latency on the same hardware.

Gate: Ivy picks the model family from the report.

### Step 6: Training data in the lilguy interface (P6)

Status (2026-11-19): corpus v2 is built ([data card](../data/CORPUS-V2.md)). Revision 2 has 36
generator groups / 68 emitted family labels, with original fixtures plus tldr-pages patterns
(CC BY 4.0, pinned):

- revision 1: 1,342 episodes and 3,957 next-action rows;
- revision 2: 1,799 episodes and 5,266 rows.

Every episode is gold-run, then replayed on a fresh guarded fixture, deduplicated against the
development tasks, and passed through the frozen held-out split gate. The gate passed for both
revisions. Gate items still open:

- The audit is an agent audit. The subagent marked 200/200 correct; my own review downgraded 4
  debatable asks, giving 98%. A human audit is still needed.
- Dedup rejected 37 / 68 generated examples in revisions 1 / 2; all remaining examples passed
  the split, gold and replay gates in the final builds. The data card records earlier generator
  development rejections separately.

Deliverables:
1. **[Licence audit](../data/LICENCE-AUDIT.md)** of the public sources. Only
   cleared sources go forward.
2. **Fixture builders** for the most common utilities, ranked by the coverage
   curve. A builder creates a small workspace that a request's command
   actually acts on, for example `.log` files of chosen sizes and ages for a
   `find -size -mtime` request.
3. **Gold execution.** Run the reference command in the sandbox. Keep the
   example only if its effects are deterministic and non-trivial.
4. **Trajectory rendering in the interface:**
   - look (`ls`, `find`, or `read` as needed);
   - act (a typed tool when the translator covers the command, otherwise
     `run` with it);
   - check;
   - `done` with a factual summary.
5. **Replay through the real agent loop and sandbox.** Keep the trajectory
   only if its effects match the gold run.
6. **Behaviour families** carried over from the pilot, now in the interface:
   - ask vs. content-determined target;
   - read order in both directions;
   - a failed step followed by investigation, never `done`;
   - `pending` and `rejected` handling;
   - an honest `done` summary.
7. **Dedup and leakage checks** against the held-out set, and a data card with
   counts per pipeline stage.

Target for round one: a few thousand verified trajectories. Personal shell
history is never used (D9).

Gate:
- ≥ 95 % of a 200-example manual audit is truly correct;
- zero exact or near-duplicate leakage into held-out;
- the yield per stage is reported.

### Step 7: Train and iterate (P8)

Status (2026-11-19): `python -m dev.factory pilot --base minicpm --base qwen08 [--data DIR]` runs
the whole loop as one job:

- corpus verification;
- chat-template parity against llama-server;
- trainer v2 (`dev/v2_train.py`: final-action loss, decision-token weight 5, fit-set stopping,
  time box);
- a matched Q8_0 export of stock and tuned;
- both development suites for both artifacts;
- `comparison.json` and `report.md`.

Results are in [STATUS.md](../STATUS.md). No candidate has yet beaten its stock base in every
category, so the held-out suite has not been run.

Decision sprint (2026-11-20): the factory now accepts matched `--arm control=DIR` and
`--arm treatment=DIR` data inputs with a declared epoch cap. The output-orientation experiment
completed both bases and both arms: MiniCPM 35→42/80 and Qwen 28→31/80, with clarification
0→5/9 and 1→4/9. Category regressions, new unsafe actions and missed targets prevent promotion.
The [controlled result](../data/DECISION-CONTROLLED-RESULT.md) and
[per-example agent semantic audit](../data/DECISION-SEMANTIC-AUDIT.json) close this sprint with
a negative promotion result. Additional warmup/cosine training is a separate experiment,
not an extension beyond this sprint's two-recipes-per-base limit.

For a long run launched by Hermes on this host, use a dedicated memory-bounded scope rather
than its small default worker cgroup. For example, the revision-2 experiment used:

```bash
systemd-run --user --scope --collect -p MemoryMax=20G -p MemorySwapMax=1G \
  env CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 \
  .venv/bin/python -m dev.factory pilot --base minicpm --base qwen08 \
  --data reports/corpus/v2-r2 --minutes minicpm=62 --minutes qwen08=30 \
  --stock-from reports/factory/pilot-w74u7u0b
```

The 62-minute MiniCPM allowance was an explicit second-round extension, not a demonstration
that two epochs fit the original 25-minute target. Verify scope limits and host memory/disk
headroom for each job; these limits are machine-specific, not portable defaults.

Deliverables: LoRA SFT on the chosen base with the pilot recipe:
- loss on the final action only;
- decision-token weighting;
- training length set by training fit.

Then the cycle, one round at a time:
1. train;
2. run the dev suite in the sandbox;
3. classify failures;
4. add targeted data families;
5. retrain.

The held-out set is run **once** per candidate, at the end.

#### 2026-11-24 — Promotion rule for training rounds from r14 on (decided before r14)

Two seeds of one corpus scored 53 and 48 on the 80-task roster (r13), and 68 and 59 on 106. That
spread is larger than any candidate's distance to the bar, so "every seed reaches the bar" rejects
candidates on the draw of a seed. From round 14:

- train **three seeds** (42, 43, 44) on the same corpus and recipe;
- score each on the full development roster, on the same code and GPU as the reference (2.0 on the
  round's interface);
- the round goes to held-out only if **the mean of the three seeds is above the reference** and
  **no seed is more than 5 tasks below it**;
- the seed sent to held-out is chosen **before** scoring: seed 42. Picking the best-scoring seed
  would select on noise.

Rounds 11–13 stay judged by the rule declared for them; r13 is not reopened.

Gate:
- beats its own untuned baseline in every category, with no new unsafe
  behaviour;
- then the held-out run is reported against the SCOPE targets.

### Step 8: Daily driver

Deliverables:
- Merge the adapter, convert to GGUF and quantise with llama.cpp. Re-run dev
  and held-out on the **quantised** file, which is what ships.
- `lilguy do` uses llama-server by default.
- Latency and cost against a 30B+ reference on the same machine. Before the
  latency run, pin the shipped GGUF and reference artifact (including
  quantization), the primary metric, and the shared workload, device and
  runtime. Report whole-episode and model-request timing separately, including
  the task count and timing on tasks both artifacts complete. Check the
  published target against the predeclared metric; a previous screen with
  different artifacts is not a release measurement. See [post-3.0 follow-up](../STATUS.md#post-30-follow-up) for the current state.
- A model card: base, data sources and licences, interface version, scores
  and known limits.

Gate: the held-out result meets the SCOPE targets, or the report says honestly
which target was missed and by how much.

## Decided, deferred, open

**Decided** (with reason):
- **Small model.** ≤ 1.5B target, 4B cap, so it runs on ordinary hardware;
  30B stays reference-only.
- **Trained only on the lilguy interface** (Ivy, 2026-11-18). Home turf beats
  generic bash knowledge for reliability.
- **Safety lives in lilguy.** The model never approves, commits or sees a raw
  shell (D1, decision 004).
- **The held-out set is frozen before data generation and never tuned on**,
  so the score means something.
- **No personal history in training** (D9).
- **Reuse the pilot tooling** rather than rebuilding it.

**Deferred** (not this round):
- reinforcement learning and distilling trajectories from large models
  (SCOPE round 2);
- tasks that need network, such as package installs (the network setting
  exists);
- long-running or interactive programs;
- multiple agents;
- macOS and Windows;
- training from scratch.

**Open** (each with the default that gets built if unanswered):
1. **Action syntax.** Default: the line envelope in step 1.
2. **Typed tools versus `run` only.** Default: train both. The step 5 and 7
   ablations decide whether typed tools stay in the training mix.
3. **Teacher-generated trajectories** from the 30B or a cloud model. Default:
   no. Use them only if data yield is the bottleneck, and only after the same
   sandbox verification.
4. **Base model.** Default: Qwen3.5-0.8B until the step 5 screen says
   otherwise.

## Resource limits

- Local first, on the 3090. No cloud spend without a priced run and an agreed
  cap.
- About 30 GB free disk: one candidate checkpoint at a time; preflight
  weights, optimiser state, checkpoints and export.
- Evaluation always uses disposable workspaces. Tool network stays off unless
  a task category explicitly needs it, and those are deferred.

---

## Appendix A: pilot tools (config-edit tracer, still useful)

These were built for the tracer (find/read/edit on two-file config fixtures).
Steps 1–3 move them onto the new protocol. Results: [archive/PROGRESS.md](../archive/PROGRESS.md).

### Development evaluation driver

```bash
.venv/bin/python -m pytest -q tests/eval/test_small_model_eval.py
run_dir=$(mktemp -d)
.venv/bin/python -m dev.small_model_eval --backend oracle --seed 42 --out "$run_dir/oracle.jsonl"
.venv/bin/python -m lilguy.probe
.venv/bin/python -m dev.small_model_eval --backend guarded-oracle --seed 42 --out "$run_dir/guarded-oracle.jsonl"
.venv/bin/python -m dev.small_model_eval --backend ollama --model qwen3.5:0.8b --seed 42 --budget 8 --out "$run_dir/ollama.jsonl"
```

- **Suites:** the legacy matrix (default), and `--suite paired`: the same two
  files with an explicit or an ambiguous request.
- **Filters:** `--context task|listing|open` and
  `--formatting named|neutral|corpus`. `corpus` gives the training corpus's
  system prompt verbatim.
- **Fresh state:** each live episode creates a fresh workspace and state root.
  It starts the guarded stdio MCP server with network off, and issues no
  approval or commit.
- **What a pass requires:**
  - exact diff entries and staged bytes;
  - unchanged originals;
  - no unexpected step effects;
  - no pending approval;
  - the expected terminal action: `done`, or a relevant `ask` with zero writes.
- **Exit codes:** 0 when all pass, 1 on a grading failure, 2 on an
  infrastructure failure.
- **Summaries:** `python3 dev/guarded_summary.py <rows.jsonl>`.

### Synthetic corpus

`dev/small_model_corpus.py`, data card [pilot-corpus.md](../archive/pilot-corpus.md).

- 16 template families (12 train, 4 validation), disjoint across splits.
- Kinds: `act`, `ask`, `stop`, `infer`.
- Both read orders.
- Post-edit rows in the evaluator's observation protocol.
- Every exported row is verified offline; `--guarded-replay` replays a sample
  through the real sandbox.

### Training pilot and adapter server

```bash
dev/train_tests.sh    # 27 offline tests under the training interpreter
/home/ivy/Work/chrysopoeia/.venv/bin/python -m dev.sft_pilot --model <snapshot> \
  --train reports/archive/pilots/corpus-v4-seed42/train.jsonl --validation reports/archive/pilots/corpus-v4-seed42/validation.jsonl \
  --out reports/archive/pilots/sft-pilot-<run> --steps 720 --accumulation 4 --lr 2e-4 --rank 16 --decision-weight 10
/home/ivy/Work/chrysopoeia/.venv/bin/python -m dev.sft_server --model <snapshot> \
  --adapter reports/archive/pilots/sft-pilot-<run>/adapter --name lilguy-sft:<run> --port 11500 &
.venv/bin/python -m dev.small_model_eval --suite paired --backend ollama --model lilguy-sft:<run> \
  --port 11500 --context open --formatting corpus --seed 42 --budget 8 --out <new>.jsonl
```

The trainer:

- renders prompts with one function for both training and generation;
- trains only on the final answer, so history turns are prompt;
- refuses overlong or overlapping rows;
- compares base and tuned in one runtime, with the base as the same model
  with its adapter disabled.

The server implements the subset of the Ollama API the evaluator uses, on
127.0.0.1, with greedy decoding. It identifies itself and its weights' digest
in every result row. `dev/pilot_summary.py` and `dev/pilot_mistakes.py`
summarise pilot reports.
