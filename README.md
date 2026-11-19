# lilguy model factory

The product is a small model that handles everyday shell tasks through lilguy. The model chooses an action; lilguy runs it in a sandbox and owns policy, approval and apply. The factory tests one change to the model without operating servers or grading by hand.

**Current state, open decisions and evidence: [docs/STATUS.md](docs/STATUS.md).**

## Jobs

From this checkout, with the project `.venv` installed:

```sh
.venv/bin/python -m dev.factory check                       # interface, split protection, guarded tools, bypass corpus, trainer smoke
.venv/bin/python -m dev.factory fast12 --gguf MODEL.gguf    # 12 development tasks, daily comparison
.venv/bin/python -m dev.factory trial  --gguf MODEL.gguf    # one disposable edit task, smoke test
.venv/bin/python -m dev.factory compare --stock DIR --candidate DIR    # named tasks improved / regressed
.venv/bin/python -m dev.factory audit-splits --held-out H --held-out-sha256 PIN --manifest M
dev/baselines.sh OUT.tsv                                    # every stock candidate through fast12, sequentially
.venv/bin/python -m dev.baseline_report OUT.tsv --reference LABEL      # comparison table
```

Every job writes a fresh directory under `reports/factory/` and never overwrites earlier results. `result.json` records revision, dirty flag, stages and status; stage logs explain failures. A skipped required test or failed stage stops the job.

Model jobs (`fast12`, `trial`) refuse to start unless:

- the frozen held-out suite matches its pinned digest and no development task overlaps it (`dev/holdout_manifest.sha256`);
- exactly one CUDA device is visible and it matches `--gpu-name` (default `RTX 3090`). Device order is forced to PCI order, because CUDA's default order put index 0 on the desktop 4070.

`fast12` runs a scripted solution and a false-completion control beside the model on every task. It reports model misses separately from infrastructure failures, and records requests, tokens and seconds per task. `identity.json` fingerprints the model bytes separately from the evaluation inputs and the GPU. `compare` and the baseline report refuse runs whose fingerprints or devices differ.

The held-out suite is never run by these jobs. It is reserved for the one selected shipping GGUF.

`lilguy do "REQUEST" --state-dir DIR` is the prototype assistant. It uses the same loop and guarded tools, stages changes but never applies them, and hands off to `lilguy diff | approve | deny | commit`.

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
