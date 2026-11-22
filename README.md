# lilguy model factory

The product is a small model that handles everyday shell tasks through lilguy. The model chooses an action; lilguy runs it in a sandbox and owns policy, approval and apply. The factory tests one change to the model without operating servers or grading by hand.

**Current state, open decisions and evidence: [docs/STATUS.md](docs/STATUS.md).**

## Jobs

From this checkout, with the project `.venv` installed:

```sh
.venv/bin/python -m dev.factory check                       # interface, split protection, guarded tools, bypass corpus, trainer smoke
.venv/bin/python -m dev.factory fast12 --gguf MODEL.gguf    # 12 development tasks, daily comparison
.venv/bin/python -m dev.factory broad  --gguf MODEL.gguf    # additional development tasks for family selection
.venv/bin/python -m dev.factory screen --model small=SMALL.gguf --model ref=REFERENCE.gguf --reference ref
.venv/bin/python -m dev.factory trial  --gguf MODEL.gguf    # one disposable edit task, smoke test
.venv/bin/python -m dev.factory compare --stock DIR --candidate DIR    # named tasks improved / regressed
.venv/bin/python -m dev.factory audit-splits --held-out H --held-out-sha256 PIN --manifest M
dev/baselines.sh OUT.tsv                                    # every stock candidate through fast12, sequentially
.venv/bin/python -m dev.baseline_report OUT.tsv --reference LABEL      # comparison table
bash dev/pilot_v1.sh                                      # train, export, and compare the first pinned v1 pilot
bash dev/pilot_v1.sh recovery                             # add replayed recovery and factual read examples
bash dev/pilot_v1.sh handoff                              # test a matched-budget mix with clarification and approval stops
```

Every job writes a fresh directory under `reports/factory/` and never overwrites earlier results. `result.json` records revision, dirty flag, stages and status; stage logs explain failures. A skipped required test or failed stage stops the job.

The full `check` requires `rsync` on the sandbox executable path (`/usr/bin:/bin`). Safety acceptance requires all 18 named cases in the JUnit report; a deselected case is missing evidence, not a pass.

Model jobs (`fast12`, `broad`, `screen`, `trial`) refuse to start unless:

- the frozen held-out suite matches its pinned digest and no development task overlaps it (`dev/holdout_manifest.sha256`);
- exactly one CUDA device is visible and it matches `--gpu-name` (default `RTX 3090`). Device order is forced to PCI order, because CUDA's default order put index 0 on the desktop 4070.

`fast12` runs a scripted solution and a false-completion control beside the model on every task. It reports model misses separately from infrastructure failures, and records requests, tokens and seconds per task. `identity.json` fingerprints the model bytes separately from the evaluation inputs and the GPU. `compare` and the baseline report refuse runs whose fingerprints or devices differ.

`broad` uses those same controls on the additional development fixtures. Read `broad.json` for the outcome and use the separate evaluation fingerprint to check comparability across broad runs.

`screen` runs both development suites for each local GGUF, sequentially under one factory lock. Its `comparison.json` names the tasks each model or the comparison reference alone passed and reports clarification, policy stops, and median episode and model times. A screen exits successfully when the evidence is complete and comparable, even if models miss tasks. A missing, inconsistent, or infrastructure-failed run stops the screen without publishing a comparison. `--reference` is for that screen only; it does not choose the release reference.

`pilot_v1.sh` builds and replays its training-only fixtures, trains the pinned 0.8B adapter locally, exports matched stock and tuned Q8_0 GGUFs, and checks both development suites. It writes `comparison.json` with named gains and regressions. The command is offline and specific to the cached checkpoint, training venv and llama.cpp build it verifies; it is not a shipping job.

The held-out suite is never run by these jobs. It is reserved for the one selected shipping GGUF.

`lilguy do "REQUEST"` is the prototype assistant (`lilguy ask "QUESTION"` is its read-only mode). It uses the same loop and guarded tools, stages changes but never applies them, and hands off to `lilguy diff | approve | deny | commit`.

One-time setup points lilguy at its tuned GGUF and pins a GPU by name; after that `ask`/`do` start the model on demand (port 18088, evaluator flags) and refuse to drive any other model found on that port:

```bash
lilguy setup --model ~/programs/lilguy/minicpm-r8-seed43-q8_0.gguf --gpu 4070
lilguy ask "What is the timeout in staging.conf?"   # run inside the folder to work on
lilguy stop                                         # free the GPU
```

Pass `--url` to drive an already-running server instead (factory jobs do).

## Layout

| Path | Contents |
|---|---|
| `docs/STATUS.md` | Where each step stands, with evidence and open decisions |
| `docs/plan/ROADMAP.md` | The one active plan and release criteria |
| `docs/data/` | Data sources and licence status |
| `docs/reference/`, `docs/decisions/` | Sandbox spec, scope, implementation notes, decision records |
| `docs/archive/` | Superseded progress logs, pilot corpus card, prototype README |
| `lilguy/` | Runtime: protocol, loop, guarded MCP server, sandbox, policy, `lilguy do` |
| `dev/` | Factory: jobs, Fast12, broader development tasks, held-out corpus and gate, baselines |
| `tests/` | `unit/` (offline), `sandbox/` and `bypass/` (real bwrap; run one suite at a time), `train/` |
| `reports/` | Run evidence, gitignored; see [reports/README.md](reports/README.md) |
