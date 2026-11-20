# Decision-learning controlled result

2026-11-20. Development-only experiment; no held-out model evaluation or task inspection.

## Decision

Do not promote either adapter. Output-orientation coverage improved development clarification
and overall scores on both bases, but neither meets the requested targets and both regress on
other tasks. This is a completed controlled experiment with a negative promotion result, not
an unexplained aggregate gain or proof that clarification and honest stopping are solved.

Diagnosis: [DECISION-DIAGNOSIS.md](DECISION-DIAGNOSIS.md). Local evidence:
`reports/factory/pilot-_jk0eppk/{arms.json,arms-report.md,failed-done-review.json}`.
The comparison can be rendered with:

    .venv/bin/python -m dev.arm_report reports/factory/pilot-_jk0eppk

## Design and data

The intervention was chosen from training-fit, contrast and development-trace evidence before
training these recipes. The shared correction compares source and destination before an
`ask_collision` claim of different contents. Only treatment adds output-orientation episodes.

| Arm | Revision | Generated | Deduplicated / gold OK / replay match | Training rows |
|---|---|---:|---:|---:|
| Control | 3 | 1,867 | 1,799 each | 5,286 |
| Treatment | 4 | 1,987 | 1,919 each | 5,586 |

Both corpus builds passed their pinned split gates. All retained episodes were run and replayed
through the real loop and guarded sandbox. Erroneous initial probes are context, not training
targets. Source policy is unchanged: original fixtures and cleared pinned tldr-pages patterns;
no new external dataset. Revision 1/2 row regeneration still passes after these extensions.

The revision-2 stratified audit contains 200 per-example verdicts/reasons at
`reports/diagnosis/decision-sprint/audit-verdicts.json`, labelled **agent audit for Ivy to confirm**.
Its initial 200/200 verdict is not a reliable corpus-correctness estimate: targeted diagnosis
subsequently found the collision-label defect it missed. The common correction was replayed
in both new arms; human semantic approval remains outstanding.

One factory invocation ran both bases and both arms sequentially:

    systemd-run --user --scope --collect --unit=lilguy-decision-arms \
      -p MemoryMax=20G -p MemorySwapMax=1G \
      env CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 \
      .venv/bin/python -m dev.factory pilot \
      --base minicpm --base qwen08 \
      --arm control=reports/corpus/v2-r3 --arm treatment=reports/corpus/v2-r4 \
      --minutes minicpm=35 --minutes qwen08=30 --max-epochs 1 \
      --stock-from reports/factory/pilot-kqfyui0g

Equal across arms: seed 42, AdamW constant LR 2e-4, rank 16/alpha 32/dropout 0 LoRA,
final-action loss with decision weight 5, batching, pinned base revisions and converter.
Both bases completed exactly one epoch, as declared from training-only evidence, not selected
using development scores. MiniCPM's budget was 35 minutes and Qwen's 30 minutes per run.

Treatment adds 300 rows (about 5.7%) and 19 optimizer steps (331 to 350). This tests the data
addition as a package, **not** an exposure-matched causal effect of content alone. There is one
seed and no independent replication. Development failures informed treatment design, so these
scores are optimistic development evidence, not generalization estimates.

## Fixed development roster and matched results

Exactly 80 tasks: 12 Fast12 plus 68 broad. The roster, interface v1 and golden system prompt
were unchanged. Stock/control/treatment use matched Q8_0 exports, the same per-suite evaluation
fingerprints, and NVIDIA GeForce RTX 3090 device identity. Stock scores were fingerprint-checked
before reuse. Failed task exits in the factory log are model misses, not incomplete suites;
`compare_base` refuses missing tasks, infrastructure failures or changed originals.

| Base | Stock | Control | Treatment | Treatment 95% Wilson CI | Relevant asks: control → treatment |
|---|---:|---:|---:|---|---|
| MiniCPM5-2B | 26/80 | 35/80 | 42/80 | 42–63% | 0/9 → 5/9 |
| Qwen3.5-0.8B | 2/80 | 28/80 | 31/80 | 29–50% | 1/9 → 4/9 |

MiniCPM gains 15 tasks and loses 8 relative to control. Qwen gains 12 and loses 9. The full
named lists, per-category intervals and measured model/episode times are in `arms-report.md`.

| Category | n | MiniCPM control | MiniCPM treatment | Qwen control | Qwen treatment |
|---|---:|---:|---:|---:|---:|
| Ask | 9 | 0 | 5 | 1 | 4 |
| Delete | 2 | 2 | 2 | 2 | 2 |
| Edit | 32 | 14 | 11 | 8 | 10 |
| Inspect | 12 | 6 | 7 | 7 | 4 |
| Organise | 9 | 7 | 6 | 4 | 3 |
| Permissions | 4 | 2 | 4 | 2 | 2 |
| Read-only | 7 | 2 | 4 | 2 | 4 |
| Recovery | 2 | 2 | 2 | 2 | 2 |
| Scripts | 3 | 0 | 1 | 0 | 0 |

Missed targets: MiniCPM 42 < 48; Qwen 31 < 36; best clarification 5 < 6. Both treatment arms
fail no-category-regression. MiniCPM edit and organise regress; Qwen inspect and organise
regress. No new recipe is launched in this sprint: the two-recipes-per-base limit is reached.

## Training fit

These are training-only aggregate measurements on up to 800 rows, not the earlier stratified
per-class diagnostic sample. The sample changes with the corpus; do not interpret the two
arms' fit percentages as a paired fixed-row measurement.

| Base / arm | Steps | Total seconds | Decision fit | Token fit | Weighted fit loss | Peak allocated GPU MiB |
|---|---:|---:|---:|---:|---:|---:|
| MiniCPM control | 331 | 1,622.5 | 90.375% | 97.859% | 0.1193 | 11,160 |
| MiniCPM treatment | 350 | 1,714.6 | 72.875% | 96.737% | 0.2877 | 11,267 |
| Qwen control | 331 | 1,639.7 | 87.5% | 97.367% | 0.1093 | 9,020 |
| Qwen treatment | 350 | 1,731.4 | 89% | 98.064% | 0.1059 | 9,075 |

None reaches 99% decision fit. MiniCPM treatment's aggregate training fit is worse despite its
development gain. Do not claim the data addition repaired training fit or that more training
necessarily helps.

## Semantic clarification and stopping review

Automated grading is not semantic approval. All nine clarification traces per arm are exported
in `arms-report.md`. Treatment learns the simple two-file selection question on both bases.
MiniCPM additionally handles the missing-order and collision clarification cases, but still
writes an ambiguous date and asks insufficient questions about conflicting guides, quantities
and revision evidence. Qwen regresses from a relevant missing-order ask to writing its own
order, acts on the ambiguous date, and chooses a separator despite conflicting guides.

| Counter (not a semantic verdict) | MiniCPM control | MiniCPM treatment | Qwen control | Qwen treatment |
|---|---:|---:|---:|---:|
| Pending/rejected observations | 3 | 6 | 5 | 5 |
| Failed task ending in done | 42 | 24 | 25 | 28 |
| Ask terminal | 1 | 10 | 12 | 10 |
| Budget terminal | 2 | 9 | 16 | 15 |
| Invalid terminal | 0 | 0 | 0 | 0 |

Pending/rejected counters include correct handoffs. Failed `done` includes honest stops,
wrong transformations and grader mismatches; it is not a count of false-success claims.
Independent per-example semantic stopping and unsafe-action reviews are pending at this draft.
No safety improvement is claimed from the counters. The original fixtures are preserved;
this establishes containment in these episodes, not correct model decisions.

## Verification and remaining gates

- Both arm plans and the final `arms.json` were produced; all four runs stopped at `max_epochs`.
- Full current unit suite: 762 passed; ruff over `dev`, `tests/unit` and the live corpus test passed.
- Real sandbox corpus variant suite: 87 passed in 121.30 seconds across revisions 1–4.
- Frozen protocol and golden prompt match interface commit `5392523`.
- Earlier adapters and all four new adapters/merged checkpoints/GGUFs are retained.
- Filesystem has about 67 GiB available after the experiment, above the 30 GiB floor.
- Full 18-case safety acceptance is still blocked by absent rsync; this was not passed by omission.
- Human audit, broader development coverage, release latency and shipping selection remain open.
- Cosine warmup/decay is a separate proposed experiment. Its implementation remains in
  `stash@{0}` and was not used by either arm; this result cannot be attributed to cosine.

Final independent artifact and semantic reviews are pending; their findings must be integrated
before calling this report finalized.
