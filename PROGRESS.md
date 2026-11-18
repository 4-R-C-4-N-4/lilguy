# Implementation progress

## Small-model development pilot

**Pilot 5 (corpus v4; pilot 4's settings at 720 steps ≈ 10 epochs, 951 s, peak 8.1 GiB, adapter 41 MiB).** Single next action on the four unseen validation families: edits 32/32 (including all 16 content-determined `infer` cases), asks 16/16 by action (the 3 non-exact list the two files in the other order), stops 48/48 (including the multi-turn post-edit stops), no invalid JSON; base 48/96 (all `done`); training 288/288. **Guarded multi-turn evaluation, files open (corpus prompt, seed 42, budget 8): 7/7** (base 0/7, pilot 4 3/7). Every episode used the minimum actions: `fs.edit` then `done` for the four edits, one relevant `ask` and no write for the three ambiguous requests; originals unchanged. Episodes took 1.2–2.4 s (bf16 transformers on the 3090; the 30B Q4 Ollama reference took 1.6–3.8 s on the paired suite with a different prompt — not a like-for-like latency comparison, and not yet the <10% target). Rows: `reports/guarded-pilot5-{paired,legacy}.jsonl`.

**Outside its training, pilot 5 is unsafe in behaviour, though the guard contained it.** With no files open (task-only or listing context, never trained): 0/6. In every episode it immediately edited an invented path or invented text (`queue`, `config.json`, `batchSize = 16`), and all six edits were refused by the tool (`Expected a regular file`, `exactly one literal match`): nothing staged, originals unchanged. **It then returned `done` after each failed edit**, claiming completion after an error. Every post-edit observation in training was a success, so it learned "after an edit, stop" without reading the result. Rows: `reports/guarded-pilot5-discovery.jsonl`. Needed before any wider use: training rows where a failed tool call is followed by recovery (read the file) and never `done`, plus discovery (find/read before acting) or a scaffold that supplies candidate files.

Pilot 4 (corpus v3, both read orders; pilot 3's settings at 480 steps ≈ 10 epochs, 619 s). Single next action on the four unseen validation families: edits 15/16 (base 0/16), asks 16/16 by action (5 list the two files in the other order, so exact-match says 11/16; all are the right question), stops 32/32, no invalid JSON; training 192/192. Read-order bias gone: edits correct 8/8 when the target was read first, 7/8 when last (pilot 3: 0/4 and 4/4). **Guarded multi-turn evaluation** through `dev/sft_server.py` (corpus prompt, open context, seed 42, budget 8): 3/7 vs base 0/7. Ambiguous requests 3/3 correct (relevant question, no write). Paired explicit edits: exact effect, then the model repeats the edit until the budget runs out instead of `done` — the corpus only taught stopping after a fresh re-read, never after the evaluator's `Observation:` turn. Legacy queue/cache: the request names no file but only one file has the setting; the model asks. The corpus taught "edit only if the request names one file", while the real criterion is whether the target is determined by the workspace; no training case had a target fixed by content alone. No originals changed in any episode. Rows: `reports/guarded-pilot4-{paired,legacy}.jsonl`. Next: corpus v4 adds multi-turn post-edit rows in the evaluator's protocol and content-determined targets (same ambiguous wording, but only one file has the setting → edit). Caveat: these failure classes were found on the development suite, so after v4 that suite is no longer an unbiased estimate; the held-out P7 suite is.

Corpus v4 (`reports/corpus-v4-seed42/`): kinds act/ask/stop/infer, 256 cases → 288 train / 96 validation rows (train: 96 edit, 48 ask, 144 done). Post-edit `done` rows continue in the evaluator's protocol via the shared `observation_message`; the trainer now accepts history assistant turns and trains only on the final one. Full guarded replay reproduced all 384 rows, no leftover scopes. Tests: 98 corpus/eval, 27 training-env.

Pilot 3 (same as pilot 2 but 240 steps ≈ 10 epochs, chosen to fit the training asks, 306 s): validation 27/32 — **asks 8/8** (0/8 before), edits 4/8, stops 15/16, no invalid JSON; training 91/96 (asks 24/24, edits 19/24). Every mistake is an over-ask, and all nine (5 train, 4 validation) are edits whose named target is the *first* of the two files read; every edit naming the second (last-read) file is correct on both splits. The corpus always read the files in the same order, so "the request names the last-read file" partly stands in for "edit". Fix motivated by the training errors: corpus v3 emits each case in both read orders. `dev/pilot_mistakes.py` lists mistakes by kind.

Corpus v3 (`reports/corpus-v3-seed42/`): 192 cases → 192 train / 64 validation rows; a full guarded replay reproduced all 256 rows (no leftover scopes). The corpus system prompt is now one shared function (`system_prompt`, export byte-identical after the refactor) and the evaluator can use it verbatim with `--formatting corpus` (opt-in, legacy defaults unchanged). `dev/sft_server.py` serves base or base+adapter from the training interpreter behind the Ollama API subset the evaluator uses, so adapters run through the unchanged guarded multi-turn evaluator; 26 training-env tests, 94 eval/corpus tests.

Guarded baseline for the untuned base through that server (corpus prompt, open-file context, seed 42, budget 8): paired suite 0/4, legacy fixtures 0/3. Six of seven episodes end in an immediate `done` with no edit; the seventh asks although the file was named. No originals changed. Rows: `reports/guarded-base-{paired,legacy}.jsonl` (the legacy file holds each episode twice from a repeated `--context` flag; `dev/guarded_summary.py` collapses duplicates). Full gate: 540 passed, 3 skipped; Ruff clean.

First real LoRA pilots (Qwen3.5-0.8B base, revision `2fc0636…`, 752M parameters, text-only `Qwen3_5ForCausalLM`; corpus v2 seed 42; rank 16 all-linear, lr 2e-4, 72 steps × 4 accumulation ≈ 3 epochs; 3090: 90 s, ~1,970 tok/s, peak 7.9 GiB, adapter 41 MiB). Base and tuned evaluated in the same runtime with greedy decoding. Base: `done` on all 32 validation rows (16/32, the majority class). Pilot 1 tuned: validation 24/32 — edits 8/8 exact on the four unseen families (including targets named only by directory word), stops 16/16, **asks 0/8: every ambiguous request became a guessed edit**, mostly of the first file. It also failed all 24 *training* asks while the token-mean training loss reached ~0.02. Diagnosis (teacher-forced probability of the decision token): p(ask) ≈ 0.13 on training ask rows vs 0.08 on training edit rows. The adapter learned an unconditional "after reading the files, edit" shift plus argument copying, not the conditional decision; the decision is ~1 of ~30 target tokens, so the mean loss hid it. Pilot 2 added a 10× loss weight on the action-name span (`--decision-weight`, tested): identical scores, p(ask) on a training ask row 0.18. So the conditional decision is underfit at this budget, not only diluted. Neither pilot passes the proposal's gate (beat base on both edit and ask). Reports: `reports/sft-pilot-{1,2}/report.json`; summary via `python3 dev/pilot_summary.py reports/sft-pilot-*`.

Corpus v2 and training pilot harness. The corpus generator now has 16 template families (12 train, 4 validation) instead of 4. Train and validation share no group, path, directory word, setting name or sentence template; the old shared "already satisfied" template leaked across splits and is gone. Each family names its target once by full path and once only by directory word ("the glaze gauge"), and the oracle enforces that explicit/stop requests identify exactly one candidate and ambiguous ones none. Seed 42: 96 train rows (24 edit, 24 ask, 48 done) and 32 validation rows (8/8/16) in `reports/corpus-v2-seed42/`. A full guarded replay of all 96 cases reproduced every exported row (1m44s, zero leftover scopes). `dev/sft_pilot.py` is the LoRA pilot: same prompt rendering for training and generation, loss on the answer only, overlong and overlapping rows refused, base vs tuned compared in one runtime with per-action scores; 14 offline tests via `dev/train_tests.sh` (tiny random model on CPU: the trained adapter emits `fs.edit` for the explicit row and `ask` for the ambiguous one; the base emits noise). Runbook and decision rule: "Training pilot" in `docs/SMALL-MODEL-PROPOSAL.md`. Full gate: 536 passed, 2 skipped; Ruff clean. The `bootstrap-seed42` corpus below is superseded. Not yet run: the pilot on real weights (needs the 1.77 GB Qwen3.5-0.8B checkpoint).

Before tuning, stock Ollama `qwen3.5:0.8b` was evaluated on all eight seed-42 validation inputs with the gold assistant message withheld (local JSON mode, seed 42, temperature zero). It returned `done` on every row: 4/4 correct stops, 0/2 edits, 0/2 clarifications. Exact action match was 4/8, identical to always predicting the majority class. No tool calls executed and no weights changed. Model digest, inference settings, source hash and predictions: `reports/bootstrap-seed42-stock-validation.json`. Rerun the untuned base in the actual training backend before attributing a difference to tuning rather than quantization or formatting.

Seed-42 synthetic corpus: `reports/bootstrap-seed42/{train,validation}.jsonl` contains 24 train and 8 validation next-action rows, split by template family. The documented six-case guarded check passed, then an independent full guarded replay of every case reproduced both export splits row-for-row. All 60 focused tests passed; Ruff clean. Data card: `docs/SMALL-MODEL-CORPUS.md`. This establishes label/effect consistency for a small open-file pilot, not generalization or model quality.

Local training preflight: the existing Chrysopoeia Python environment (torch 2.11.0+cu128, PEFT 0.20.0, transformers 5.15.0) ran a BF16 forward/backward check and a separate one-step LoRA optimizer check on the 3090. A randomly initialized 58,560-parameter test network changed its adapter weights; this verifies the software path, not fit, throughput or quality for a real checkpoint. Nothing installed or downloaded; no checkpoint saved.

Worked-example control (`dev/paired_prompt_spike.py`): added one edit demonstration and one clarification demonstration about unrelated UI files to the neutral system prompt. Same paired cases, open context, seed 42, eight turns and stock 0.8B. Guarded oracle 4/4. Model 1/4 vs baseline 0/4; neither pair passed both variants. The archive explicit case edited the wrong field and file; the ambiguous archive case guessed and staged a change. Export ambiguous asked correctly, export explicit unnecessarily asked. All original files unchanged. Do not promote this prompt on aggregate score. Traces: `reports/demo-oracle.jsonl`, `reports/demo-08b.jsonl`.

Paired host calibration (two templates, explicit vs ambiguous request, same files/read context, neutral prompt, seed 42): guarded oracle 4/4; stock 0.8B 0/4, no edit attempts and neither ambiguous question resolved the missing choice; 30B coder 1/4, two edit attempts on each ambiguous request. All original fixtures unchanged. Neither model passed both sides of either pair. Traces: `reports/paired-oracle-live.jsonl`, `reports/paired-live-08b.jsonl`, `reports/paired-live-30b.jsonl`. These four episodes diagnose behavior, not deployment accuracy.

Matched comparison on the same 18 development episodes (seed 42, eight actions): the installed SmolLM3-derived Chrysopoeia 3.1B Q4_K_M passed 0/18 and exhausted the budget on all 18. Qwen3-Coder 30B reference passed 10/12 unambiguous edits and 0/6 ambiguous cases: five `done` responses with incorrect effects, one budget exhaustion. Originals unchanged in both runs. These are three fixtures under six prompt/context combinations, not 18 independent tasks or a completed family screen. Do not use unverified reference responses as teacher labels. Local traces: `reports/m1-chrysopoeia.jsonl`, `reports/m1-30b-reference.jsonl`.

Parent-host verification of `dev/small_model_eval.py`: probe passed all nine checks and the guarded oracle passed all 18 episodes. Stock Qwen3.5-0.8B (seed 42, eight actions) passed 1/18 on these development fixtures: one relevant clarification, no successful edits. It asked on all 12 unambiguous edit episodes. Originals unchanged in every episode. This stricter matrix differs from the earlier effect-only smoke tests. Local traces: `reports/m1-guarded-oracle.jsonl`, `reports/m1-08b.jsonl`. Full tests: 512 passed, 1 skipped; Ruff clean.

Paired follow-up: 12 independent runs on two new synthetic settings (queue batch size and cache lifetime), same stock 0.8B model and eight-turn budget. With the named `fs.find` example, no exact edits in six runs. With neutral action-format wording, both open-file runs staged the exact edit and preserved the sibling setting; neither task-only nor listing-only run did. All originals unchanged. These are effect-only passes: neither successful trace recorded an explicit `done`. Raw local results: `reports/paired-development.jsonl`. This is evidence for separating edit accuracy from discovery and clean termination, not a held-out pass rate.

Approach and promotion gates: [small-model proposal](docs/SMALL-MODEL-PROPOSAL.md). Stock `qwen3.5:0.8b` (`f3817196d142`), local Ollama JSON mode, thinking disabled, temperature 0, eight-action budget. Three independent copies of the synthetic retry-limit fixture: task alone (8 actions, guessed an absolute path), listing supplied (2 actions, used the correct path but stopped without editing), and target path plus actual read supplied (8 actions, repeated find instead of editing). No staged changes; original fixture files unchanged throughout. This isolates path discovery as insufficient on this example, not a model capacity limit. The prompt's JSON action example names `fs.find`; control for that cue before interpreting tool-choice failures or training on them.

## P3 tracer milestone

The stdio server exposes `fs.find`, `fs.read`, and `fs.edit` from the trusted `toolset.yaml`. Each tool runs through `GuardedSession` and the existing sandbox backend with network off and the default resource requirements. Literal edits require exactly one match in a UTF-8 file up to 1 MiB. Typed argument values are omitted from audit and approval records.

Launch with `.venv/bin/python -m lilguy.mcp_server --workspace <disposable-fixture> --state-dir <scratch-state> --toolset <trusted-toolset.yaml>`. After the client disconnects, the session can be reviewed with `.venv/bin/python -m lilguy diff <session-directory>`.

- The project venv passed 44 focused schema, dispatch, policy, and review CLI tests. Ruff passed on the touched Python files.
- A real MCP SDK stdio client verified the tool list and invalid-path rejection. This environment failed to wake idle asyncio selectors from worker threads, so the smoke run used a scratch-only timer to wake the client and server event loops. The repository transport and test assertions were unchanged.
- Verified on the host: the stdio MCP client found, read and literally edited the fixture in the real sandbox; external review saw the staged bytes, while the original remained unchanged. The trusted server launch needs `XDG_RUNTIME_DIR` for user systemd cgroups; the MCP SDK omits it by default. No rlimits fallback or sandbox exception. Full suite: 472 passed, 1 skipped; Ruff clean. This is a scripted tool-client result, not a local model result.

## Earlier implementation status

Local-model smoke demo (Ollama, no fine-tuning, disposable fixture; not a P7 benchmark): qwen3-coder:30b, qwen3:8b and qwen3.5:0.8b all failed the initial retry-limit task within the eight-turn budget. On fresh fixtures with one general discovery hint (begin with `fs.find {}` and use observed relative paths), the 30B coder found and read `service/runtime.ini`, staged exactly `retry_limit=2` → `retry_limit=5`, then stopped (2.1 s in this run). Neither smaller model staged an edit. The checked original files were unchanged in all six runs. This exploratory demo does not replace the scripted P5 regressions or the held-out evaluation.

Full report: `reports/MILESTONE.md`. Coverage: `reports/coverage.md`.

Verified gate (2026-11-18): `.venv/bin/python -m pytest -q` → 321 passed, 1 skipped (rsync absent); live sandbox + bypass suites 76 passed, 1 skipped; ruff clean; wheel/sdist build; installed wheel `sandbox-run` preview leaves the host workspace untouched. Per-step p50 over three 20-step runs: 113.5 / 157.0 / 136.8 ms (target <150 ms, borderline).

Reviews: P1 spec review APPROVED; P1 security review found cgroup scoping could be skipped silently (fixed, decision 003). P2 security review found a deep-subtree conflict blind spot (fixed; confirmation review APPROVED). All fixes have red-first regressions. No active workers.

Status by phase:
- P1 — done for acceptance on this host, except: no layer squash (fails closed at 64), p50 borderline, rsync case skipped.
- P2 — engine, pending/approval binding, per-step rollback, journaled commit/recover/undo and subtree conflict detection done. Missing: approval CLI, startup recovery wiring, retention, full crash cross-product, live corpus #19, Q3 threshold calibration.
- P3 — the three-tool tracer is implemented. Live overlay verification is pending. The wider draft toolset remains unfrozen.
- P4 — fetch (actual source schemas), static AST parse and record-level coverage done on 50,126 records inside bubblewrap. Missing: greedy curve, `-exec`/`xargs` payload splitting, frozen tldr snapshot, private history aggregate.
- P5–P8 — not started (depend on P3).

Decisions (2026-11-18, Ivy): Q1 accepted as recommended (typed find feeding typed actions; general sandboxed exec for the long tail; sudo → ask); decisions 001–005 accepted; ALFA test used as-is (300 rows).

Update (same day): human approval flow (`lilguy diff | approve | deny`, kept and continued sessions, approval carry-forward) and progress-aware time limits are implemented (decision 004). Then: `lilguy commit` / `lilguy undo` (undo refuses to overwrite later edits; commit recovers interrupted commits first), corrected policy layering (decision 005), live corpus #9 and #19, find -exec / xargs / sudo payload splitting, and the greedy coverage curve (reports/coverage-curve.md: 23.6% after 86 additions). Independent review found one critical issue (chmod race in private_io), fixed and verified. Added `lilguy sessions [--prune DAYS]`. Gate: 425 passed, 1 skipped.

Safety invariants that held throughout: no dataset command executed; every destructive test ran in bubblewrap on disposable fixtures; personal shell history not read; legacy host runner only behind `run --unsafe-legacy`.

## Verified historical milestone: P0 foundations

The supplied SCOPE.md and IMPLEMENTATION.md are the implementation plan. Work is proceeding in dependency order, beginning with P0; P1/P4 are not assumed complete.

This directory was not a Git repository at intake. No repository, branch, commit or remote has been created.

### Baseline verified

- Existing v0.1 scripted oracle: 12/12 pass on the target host.
- Source remains a host-shell prototype; regex policy is not a sandbox.
- Host bubblewrap reports 0.12.0, and `unshare -Ur true` succeeds.

### Implemented and locally verified

- Installable package, local uv environment, console/module command dispatch, offline tests, CI definition.
- Capability probe: overlay whiteouts, stacked layers, bubblewrap overlay execution, sandbox Python, Landlock ABI, cgroup delegation; required capability failures produce a nonzero exit.
- Full local gate: `.venv/bin/python -m pytest -q` → 72 passed; `.venv/bin/ruff check lilguy tests` → all checks passed.
- `.venv/bin/lilguy probe` → all 9 checks passed: kernel 6.18.52, unprivileged userns, overlay whiteouts, stacked overlay, non-setuid bubblewrap 0.12.0, bubblewrap overlay, Python in sandbox, Landlock ABI 7, cgroup delegation.
- `uv build --quiet` produced both wheel and sdist. Installed the wheel without dependencies into a separate scratch venv; from outside the checkout, module help worked and the packaged scripted oracle passed 12/12. This verifies bundled grammar and fixture resources, not future MCP dependencies.
- CI workflow has been written but not run on a remote service; this folder has no Git repository or remote.

### Review status

Independent P0 spec review found no blocking gaps, quality/security review approved the slice, and final integration review also approved. All three independently reran the 72-test gate and real host probe. Integration review independently installed the built wheel in a fresh environment and reproduced the 12/12 oracle result outside the checkout.

Known non-blocking CLI UX limitation: `lilguy run --help` hits the unsafe-execution opt-in gate; `lilguy run --unsafe-legacy --help` shows the legacy runner options without executing a model.

The supplied root `landlock_shim.py` remains reference code for P1, not imported or enforced by P0. It is included in the source distribution for implementation reference, not in the installed wheel. It must receive enforcement tests and lint coverage when moved into the sandbox package; the probe currently checks only Landlock ABI availability.

Later source-layout migration is intentionally phase-local as described below.

### Boundaries

The v0.1 agent remains in its existing modules until P5 replaces its execution interface. Moving it into the future `agent/` and `eval/` subpackages early would require compatibility wrappers without providing v0.2 behavior. Phase-specific modules are added as implemented rather than empty placeholder packages. No D1–D11 scope decision is changed.

Only trusted, vendored v0.1 fixtures execute through the legacy runner. No downloaded dataset commands may use it. `lilguy run` requires an explicit `--unsafe-legacy` flag until the sandbox backend is implemented.

P1/P2 sandbox execution, effect policy, approval, commit/recovery, MCP tools, data pipeline, model evaluation and training remain unimplemented. Passing the capability probe will establish host support, not certify an unbuilt sandbox.

## Next implementation seam

Once P0 is verified: P1 sandbox backend and per-step overlay diffs; P4 ingest/coverage can proceed independently. P3 tool membership remains gated on Ivy's coverage review; model-family and policy-threshold gates remain unchanged.

Data round (2026-11-18): three more public sources (72,244 unique commands total, reports/coverage-sources.md) and a private, aggregate-only analysis of the local shell history (reports/private/, gitignored).
Network (decision 006): per-session setting off/ask/always, default ask = a human allows full network for one exact command once; networked steps stay file-sandboxed and are blocked from host abstract sockets and signals (Landlock scoping). Gate: 459 passed, 1 skipped.
