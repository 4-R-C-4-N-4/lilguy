# Reliable Decision Learning Sprint Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task; serialize GPU work on the RTX 3090.

**Goal:** Explain the failure to learn clarification and honest stopping, then test one evidence-backed intervention against a matched control, producing a better adapter or a defensible negative result within five hours.

**Architecture:** Keep the frozen v1 interface, current 80-task development roster and held-out boundary unchanged. Add training-only decision diagnostics to the current v2 trainer and factory; isolate one learning intervention rather than simultaneously changing model, corpus, optimizer and exposure.

**Tech Stack:** Existing Python project venv, pinned training interpreter through dev/trainpy.sh, PEFT/Transformers, llama.cpp Q8_0 exports and real guarded evaluation.

## Current context

- MiniCPM stock / round 1 / round 2: 26 / 39 / 34 of 80 development tasks.
- Qwen3.5-0.8B: 2 / 30 / 27 of 80.
- Corpus R2: 1,799 verified episodes, 5,266 rows, including only 287 ask target rows (5.45%).
- R2 teacher-forced decision fit: MiniCPM 88.4%, Qwen 90.4%; neither reached the 99% target.
- Three MiniCPM R2 clarification asks concerned invented missing paths rather than the real ambiguity. A separate answer contradicted cmp output.
- Both bases have saved round-1 and round-2 adapters. Superseded round-1 merged/GGUF artifacts were removed; recover them from the pinned base and adapter only if needed, preserving resource limits and recording new export identities.
- Full safety acceptance remains blocked by absent rsync; human data audit remains open.

## Sprint assignment

Repo: ~/Work/lilguy, branch main. Budget: five hours, one RTX 3090. Do not execute this plan merely because it exists; this document is the proposed next sprint.

Read docs/STATUS.md, docs/data/LORA-V2-PILOT.md, docs/data/CORPUS-V2.md and roadmap steps 6–7. Inspect dev/v2_train.py, dev/v2_corpus.py, dev/factory_pilot.py, dev/v2_report.py and their tests. Call claimbase brief and recall for project lilguy.

### 1. Diagnose before changing the recipe

Extend encode/fit_metrics in dev/v2_train.py, or add a training-only diagnostic module with a tested pure-Python aggregation layer. Preserve action-class labels through batching. Report per-class counts, whole decision-span accuracy, decision log-probability, confusion and sampled mistakes for ask, done, run and each typed tool. Measure both teacher-forced decisions and bounded free-generation next actions; do not call teacher-forced success task completion. Use stratified verified training rows, not development tasks, for fit diagnostics and stopping.

Compare the existing stock, round-1 and round-2 models in the same training runtime. Inspect errors across file read order, missing-output versus missing-input context, ambiguity, recovery and approval stops. Rank hypotheses and write the evidence before selecting an intervention. Do not assume class imbalance is the cause merely because it exists.

Files likely to change: dev/v2_train.py, tests/unit/test_v2_train.py; a new diagnostic CLI and its tests if separation makes the existing trainer simpler. Add failing regression tests first for class accounting, complete multi-token decision spans, padding and diagnostic denominators. Run tests/unit/test_v2_train.py before GPU diagnostics.

### 2. Audit semantic labels and choose one intervention

Audit a stratified 200-example R2 sample, emphasizing ask/act boundaries and recovery/pending/rejected endings. Mark it as an agent audit for Ivy to confirm. Record per-ID verdicts with reasons for questionable or wrong labels; do not treat replay success as semantic correctness.

If labels need correction, fix and rebuild the corpus, replay every admitted episode and pass the frozen split gate. Use the same corrected corpus for control and treatment. Otherwise keep the corpus unchanged. Select one intervention justified by diagnostics, such as action-class balancing or corrected decision weighting. Do not simultaneously change rank, learning rate, model family and corpus mix. Record the unchanged variables and the chosen factor explicitly.

Files likely to change: dev/v2_corpus.py only if verified label defects warrant it; corpus tests and docs/data/CORPUS-V2.md for any rebuilt corpus.

### 3. Run matched control and treatment through the factory

Extend dev/factory.py and dev/factory_pilot.py with explicit recipe configuration as needed, covered by tests. One command must own verification, diagnostics, training, matched export, both development suites and comparison reporting.

Use MiniCPM as the main candidate and Qwen0.8B as the control base. Run at most two new training recipes per base: matched control and one proposed intervention. Reuse an existing control only if data, recipe, export, evaluation and device identities actually match. Choose exposure from training-only fit and a declared time budget, never development score. Measure and record overruns or unmet fit thresholds honestly.

Keep the current roster at 80 total tasks (12 Fast12 + 68 broad) for this causal comparison. Do not expand it mid-sprint. Grade every effect and preserve originals. Review failed done answers and policy-stop traces semantically; distinguish confirmed false-success claims from all failed tasks ending in done.

### 4. Report and stop

Publish per-class fit, intervention/control identities, full development comparisons, per-category Wilson intervals, clarification relevance, confirmed false-success cases, unexpected policy stops and latency. Preserve the prior best adapters. Update STATUS.md and the data card, record durable claims in claimbase, commit completed milestones locally and do not push.

Validation: .venv/bin/python -m pytest -q tests/unit; relevant new diagnostic tests; .venv/bin/python -m pytest -q tests/sandbox/test_v2_corpus_live.py after corpus changes; .venv/bin/ruff check dev tests/unit. Verify actual GGUF hashes, matching evaluation/device fingerprints, exact rosters, zero infrastructure failures and unchanged originals before comparing.

## Targets, boundaries and stop conditions

Ambitious targets, not guaranteed outcomes: MiniCPM at least 48/80 and Qwen at least 36/80, at least 6/9 relevant clarification passes on the selected candidate, no confirmed false-success claims, and no additional unexpected policy-stopped attempts versus its matched control. Report category regressions rather than hiding them behind the total. No promotion if safety or existing promotion gates fail.

Hard rules: no interface-v1 or golden-prompt changes; no held-out task inspection, editing or model inference in this sprint; no new model downloads or cloud spend; only original fixtures and pinned attributed tldr-pages; every training episode replay-verified; destructive and dataset command execution inside sandboxes. Keep at least 30 GiB free. Use CUDA_DEVICE_ORDER=PCI_BUS_ID and CUDA_VISIBLE_DEVICES=0. Run heavy jobs in a dedicated systemd user scope with verified RAM/swap limits sized to host headroom; the prior run used MemoryMax=20G and MemorySwapMax=1G. Save exact parameters, data digests, epoch metrics and adapters before merging. Keep one merged checkpoint per candidate; remove superseded large exports only after their reports are durable.

Time allocation: roughly the first two hours for diagnostics, semantic audit and the chosen change; the next two for sequential paired runs; the last hour for verification and reporting. If diagnosis/setup leaves insufficient time for a matched run, reduce scope explicitly rather than running unmatched experiments. Stop at five hours or the recipe limit with a reported result. A well-tested diagnosis and a negative controlled experiment count as a completed sprint; inventing a win does not.
