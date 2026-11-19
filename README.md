# lilguy model factory

The product is a small model that handles everyday shell tasks through lilguy. The model chooses an action; lilguy runs it in a sandbox and owns policy, approval and apply. The factory is how we test one change to the model without operating the servers or grading the result by hand.

## Run a job

From this checkout, with the project `.venv` installed:

```sh
.venv/bin/python -m dev.factory check
.venv/bin/python -m dev.factory trial --gguf /path/to/candidate.gguf
.venv/bin/python -m dev.factory fast12 --gguf /path/to/candidate.gguf
```

`check` runs the interface tests, guarded tool integration, and trainer smoke tests in order. A missing dependency, skipped required test, or failed stage stops the job. The trainer smoke uses a toy model and legacy pilot fixtures; it does not train the product. Set `LILGUY_TRAIN_PYTHON` to an interpreter with torch, transformers and PEFT if not using the local training environment.

`trial` starts its own loopback llama-server and sandbox tool server, gives the candidate one disposable file-edit task with six actions, checks the file rather than trusting `done`, then shuts down. Supply `--server /path/to/llama-server` if needed. It never applies a change. This is a development smoke test, not a held-out score.

Both commands print their run directory under `reports/factory/`. `result.json` records the revision, dirty flag, stages, times and status; stage logs explain failures. `trial.json` records the model's turns and task verdict when a trial completes. Exit zero means the job passed; jobs do not overwrite previous results.

`fast12` is the everyday development comparison: 12 disposable tasks, with a scripted solution and a false-completion control for each. Read `fast12.json` for the counts and `task_*.json` for individual actions, observations and grading reasons. A nonzero exit can mean model misses or infrastructure failures; the report separates them. This job does not train or use held-out tasks.

## What to read

- [Model plan and release criteria](docs/SMALL-MODEL-PROPOSAL.md): the one active roadmap. Target ≤1.5B parameters (4B hard ceiling), ≥70% held-out completion, <10% of 30B latency, and no unauthorized destructive changes.
- [Sandbox specification](docs/reference/spec.md), [scope](docs/reference/SCOPE.md), [implementation details](docs/reference/IMPLEMENTATION.md) and [decision records](docs/decisions/): reference, not separate model roadmaps.
- [Data sources](docs/DATA-SOURCES.md) and [pilot corpus card](docs/SMALL-MODEL-CORPUS.md): provenance, not permission to train on raw commands.
- [Historical progress](docs/archive/PROGRESS.md) and [prototype review](docs/archive/legacy-readme.md): old results and superseded designs. Run evidence belongs under `reports/`, not here.

## Where the factory stops today

The repeatable path ends at a development trial. Production training is not enabled: finish the guarded tool review, freeze disjoint development and held-out suites before generating training data, then wire verified episode generation, training, GGUF export and development evaluation into this same entry point. Keep the one-shot held-out release test out of the everyday iteration job.
