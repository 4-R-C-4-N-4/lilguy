# Proposal: ship the smallest useful lilguy

## Decision to make

Can a model at or below 1.5B parameters reliably turn an ordinary request and workspace observations into safe tool calls? Choose the smallest model that meets the [scope](../SCOPE.md) targets: at least 70% held-out task completion, under 10% of the latency and cost of a 30B+ reference, and no destructive effects reaching the workspace outside policy or human approval. 4B is a ceiling, not the goal. Report actual deployed bytes, peak memory and end-to-end latency: a small adapter attached to a large model is not a small product.

## Why start with diagnosis

In the first retry-setting smoke test, three stock models failed unaided; only the 30B coder succeeded with an inventory-first hint. Neither smaller model reached the edit. This is one development fixture, not evidence of a minimum model size. The existing `lilguy.mcp_server` exposes only find, read and literal edit through `GuardedSession`. Keep that boundary fixed while testing the model. Approval remains external.

## Work sequence and promotion gates

1. **Separate discovery from editing.** Run fresh copies of a development fixture under three conditions: task alone, task plus an actual listing, task plus the target path and an actual read. Keep schema, prompt, turn budget, decoding and grader otherwise fixed. Start with installed 0.8B; vary filenames, layouts and wording before drawing conclusions. Include ambiguous fixtures with an explicit ask action: a correct clarification and no edit is success there. Track invalid/repeated actions, exact staged bytes and unexpected diff entries; verify original files independently. If only the open-file condition works, improve discovery before spending on weights.
2. **Establish an untuned baseline.** Complete the scripted P5 regressions; build P6 verified data and the P7 task suite (at least 150 tasks plus a separate held-out set). Split by task template and near-duplicate group before generating variants. Screen several families, e.g. SmolLM2-360M-Instruct, Qwen3.5-0.8B, and a 1–1.5B coding model. Use a 2–4B comparison if needed; keep 30B reference-only. Choose a family after the screen, not from the smoke test. Pin weights, template, grammar and tool versions. Report pass@1 with uncertainty, wrong edits, unnecessary asks, task time and cost on comparable hardware; separate cold load from warm inference.
3. **Run supervised fine-tuning locally first.** Use synthetic fixtures with oracle-verified next actions and licence-cleared instruction/action pairs, including recovery, ask and stop. Public command counts are coverage evidence, not training labels. Never train on personal history. On the 24 GiB 3090, start with a small pretrained checkpoint and ordinary LoRA. Measure peak VRAM, tokens/s, storage and projected duration on a short pilot. Use QLoRA if memory limits the experiment; compare full-weight tuning of a sub-billion model if LoRA plateaus. Compare trained and stock versions with identical inputs and budgets. Promote only gains that survive unfamiliar tasks without a safety regression; recheck after GGUF export and quantization.
4. **Escalate only against a measured gap.** If examples are the bottleneck, compare verified teacher-generated demonstrations against an equal-size oracle-only set; no teacher at inference. Continued pretraining is worth a separate trial only if a recurring domain-language gap remains. From-scratch training is a separate research branch: a tiny selector over observed actions/paths must beat a pretrained small model on unfamiliar instructions, not memorize generated templates. Neither is required for round one.

## Resource and data limits

No cloud reservation or large download by default. With about 32 GB free at planning time, preflight disk for weights, optimizer state, checkpoints and export; use one candidate at a time. Request a specific cloud spending cap only after local throughput and a measured limitation give us a priceable run. Keep evaluation on disposable workspaces, network off for tools; only the trusted driver contacts the local inference service. Do not relax sandbox or approval rules to improve a score. Use development fixtures for iteration and reserve final held-out tasks for frozen comparisons.

## Milestone 1 development evaluation

Run from the repository root with the existing project environment. The driver is
a repository development module. It uses built-in synthetic fixtures for queue
batch size, cache lifetime, and an ambiguous retry-limit change with staging and
production candidates.

```bash
.venv/bin/python -m pytest -q tests/eval/test_small_model_eval.py
run_dir=$(mktemp -d)
.venv/bin/python -m dev.small_model_eval --backend oracle --seed 42 \
  --out "$run_dir/oracle.jsonl"
```

The offline oracle uses the real tracer schemas and an in-memory tool stand-in.
The default matrix has 18 independent episodes. Each fixture runs with the task
alone, with a listing, and with open-file observations, paired with both a named
`fs.find` example and a neutral JSON action template. For the ambiguous fixture,
open-file context shows both candidates. On the guarded backends, all supplied
listings and reads are actual MCP observations. Context calls happen before the
model's action budget starts.

### Parent host validation

Use a host session with the required sandbox capabilities and working user
systemd cgroup delegation. Run the probe and guarded oracle first. The guarded
oracle exercises real stdio transport, tool execution, staging, and review
without an inference service.

```bash
.venv/bin/python -m lilguy.probe
run_dir=$(mktemp -d)
.venv/bin/python -m dev.small_model_eval --backend guarded-oracle --seed 42 \
  --out "$run_dir/guarded-oracle.jsonl"
```

With a local Ollama service already running and the desired tag already installed,
run the same matrix against the stock model. The driver first validates one
guarded oracle episode, then checks the local model inventory. The default
endpoint is `127.0.0.1:11434`. Use `--port` for another local port.

```bash
.venv/bin/python -m dev.small_model_eval --backend ollama --model qwen3.5:0.8b \
  --seed 42 --budget 8 --out "$run_dir/ollama.jsonl"
```

Use repeatable `--fixture`, `--context`, and `--formatting` filters for smaller
runs. Output files must be new. Exit codes are `0` for all selected episodes
passing, `1` for a grading failure, and `2` for a command or infrastructure
failure. An infrastructure failure can leave a partial JSONL file.

Each live episode creates a fresh workspace and separate temporary state root.
The driver starts the existing guarded stdio MCP server with network off and the
default resource checks. It exposes only the three tracer tools and consumes
`done` and `ask` inside the driver. The trusted driver inspects persisted changes
and compares original files independently before the temporary directory is
removed. No approval or commit is issued. Only the trusted inference client
contacts Ollama, and the driver has no model download path.

Compare `effects_ok`, `termination`, `termination_ok`, and `invalid_actions`
separately. A pass requires exact diff entries, expected staged bytes and file
mode, unchanged originals, no unexpected step effects, no pending approval,
and a valid expected terminal action with zero malformed actions. The
ambiguous fixture requires a relevant question about which deployment to
change and zero edit calls. The question grader uses a fixture-specific language
rule. Repeated actions and tool errors are recorded separately so recovery is
visible. Reaching the action budget after a correct edit yields an effect pass
and an episode failure.

JSONL rows include the exact initial prompt, raw responses and observations,
model tag and digest for Ollama, decoding settings and seed, MCP schema and
implementation fingerprints, and elapsed episode time. Compare runs using the
same installed model digest and configuration. These fixtures are development
diagnostics. Their scores do not estimate held-out completion or minimum model
size.

## Paired act-versus-ask development calibration

The opt-in `paired` suite uses two synthetic templates, archive retention and
export headers. Each pair presents the same two candidate files in the same
order, with the same contents, requested setting change, and system prompt.
Only the user request changes. The explicit request names a path. The ambiguous
request leaves the choice of file open. The explicit target appears second in
the archive pair and first in the export pair.

Run the offline controls from the repository root.

```bash
.venv/bin/python -m pytest -q tests/eval/test_paired_calibration.py tests/eval/test_small_model_eval.py
```

On the parent host, with the sandbox prerequisites above and the exact stock
`qwen3.5:0.8b` tag already installed in local Ollama, run these bounded commands
from the repository root.

```bash
run_dir=$(mktemp -d)
.venv/bin/python -m dev.small_model_eval --suite paired --backend guarded-oracle \
  --context open --formatting neutral --seed 42 --budget 8 \
  --out "$run_dir/paired-guarded-oracle.jsonl" &&
.venv/bin/python -m dev.small_model_eval --suite paired --backend ollama \
  --model qwen3.5:0.8b --port 11434 --context open --formatting neutral \
  --seed 42 --budget 8 --out "$run_dir/paired-08b.jsonl"
```

Each command scores four episodes with two MCP context reads and up to eight
action turns per episode. The Ollama run also performs the existing guarded
preflight before contacting the local service. Group JSONL rows by `pair`,
`context`, and `formatting`. Count a pair as passing only if both variants pass.
The explicit variant requires the exact staged edit and `done`. The ambiguous
variant requires a relevant target-selection question and zero edit calls.
`termination`, `write_attempts`, and `effects_ok` show unnecessary asks and
guessed or incorrect edits even when the pair fails.

These development templates are for calibration only. Keep them and their
traces out of weight training, and reserve evaluation cases for evaluation.
The existing commands still select the legacy development matrix by default.

## Training pilot (milestone 3, local)

`dev/sft_pilot.py` runs a bounded LoRA pilot on the verified corpus
([data card](SMALL-MODEL-CORPUS.md)). It runs under a separate training
interpreter with torch, transformers and PEFT; lilguy's runtime never imports
it. It is offline: `--model` must be a local directory, and the Hub is
disabled before transformers loads.

What it guarantees:

- Training and generation render the prompt with the same function, so the
  model is trained on exactly the prefix it later continues. Loss covers only
  the assistant's JSON action and its end-of-turn token.
- Overlong examples are refused, not truncated. Validation inputs that also
  appear in training are refused.
- Base and tuned predictions come from the same loaded weights, template and
  greedy decoding. The base is the PEFT model with its adapter disabled, so a
  difference is the adapter's, not a quantization or runtime difference
  (unlike the earlier Ollama baseline).
- The report records per-action scores (`fs.edit`, `ask`, `done`), invalid
  JSON, the majority-class baseline, the training fit, loss per step,
  tokens/s, peak VRAM, adapter bytes, data hashes and package versions.

Offline tests (tiny random model and toy tokenizer, CPU, no downloads):

```bash
dev/train_tests.sh          # uses $LILGUY_TRAIN_PYTHON, default the Chrysopoeia venv
```

Pilot run, after the base checkpoint is local (Qwen/Qwen3.5-0.8B, revision
`2fc06364715b967f1860aea9cf38778875588b17`, 1.77 GB):

```bash
/home/ivy/Work/chrysopoeia/.venv/bin/python -m dev.sft_pilot \
  --model <local snapshot dir> \
  --train reports/corpus-v2-seed42/train.jsonl \
  --validation reports/corpus-v2-seed42/validation.jsonl \
  --out reports/sft-pilot-<run>
```

Reading the result: the base model's validation score is the bar. The pilot
earns a next step only if the tuned adapter beats the base on **both**
`fs.edit` and `ask` validation rows (not just overall, which `done` dominates)
with no invalid JSON. A high training fit with flat validation means
memorization of the training families. Validation here is four unseen families
on single next actions; it is not the guarded multi-turn evaluation. Before any
claim about task completion, serve the adapter (merged and exported, or through
a transformers backend in `dev/small_model_eval.py`) and run the paired and
development suites through the guarded MCP server, unchanged.

### Guarded evaluation of an adapter

The pilot's validation scores are single next actions. To see what the adapter
does in a real multi-turn episode through the guarded MCP server, serve it from
the training interpreter and point the unchanged evaluator at it:

```bash
M=<local base snapshot dir>
/home/ivy/Work/chrysopoeia/.venv/bin/python -m dev.sft_server --model "$M" \
  --adapter reports/sft-pilot-<run>/adapter --name lilguy-sft:<run> --port 11500 &
.venv/bin/python -m dev.small_model_eval --suite paired --backend ollama \
  --model lilguy-sft:<run> --port 11500 --context open --formatting corpus \
  --seed 42 --budget 8 --out <new file>.jsonl
```

`dev/sft_server.py` implements the subset of Ollama's API the evaluator uses,
on 127.0.0.1 only. It identifies itself in `/api/version`, so result rows record
it (`ollama_version`), and its digest covers the base config and adapter
files. It decodes greedily without JSON-constrained output, and it renders
prompts with the trainer's own function. Omit `--adapter` to serve the
untuned base the same way for a like-for-like comparison.

`--formatting corpus` gives the evaluator the training corpus's system prompt
verbatim (`dev.small_model_corpus.system_prompt`, one shared function). The
episode is still the evaluator's own protocol: after a write, the model sees
its action and an `Observation:` turn. The corpus instead re-reads the files
in a fresh single turn, so a failure to stop after a correct edit here points
at that protocol gap, not at the decision itself.
