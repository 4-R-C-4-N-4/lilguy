# Revision 9: lead with MiniCPM; retain the small checkpoint

[Paired audit of 80 development tasks, 24 script traces and 19 historical wrong answers](../data/R9-DEVELOPMENT-AUDIT.md). Regenerate from the root with `.venv/bin/python -m dev.revision9_audit`.

## What to preserve

Both bases consistently created a new file, merged named pages in order and handled the protected-file test. MiniCPM consistently extracted the email column and moved a batch up to the approval boundary; Qwen did neither consistently. On r8, normalized-address matching and signed totals passed on both MiniCPM seeds and neither Qwen seed. Conversely, export-owner recovery and the specific-profile tab-stop lookup passed on both Qwen seeds and neither MiniCPM seed. Preserve those exceptions rather than interpreting total score as dominance on every task.

## What to change

On literal-script creation there is an interface cost (escaping shell source inside a shell command) and a separate decision cost (trying to edit an absent destination or the source notes). On branch repair, MiniCPM can stage a syntactically plausible but incorrect edit; Qwen can inspect without repairing. On tuple-named notes both can write plausible content at the wrong path. Do not count a successful command, or `sh -n`, as proof of the requested effect. These are distinct problems, not evidence that the model needs more generic shell text.

Keep all r8 examples. Add training-only create/repair pairs for literal scripts and row-selection examples that vary column order, requested extreme and winner position. Exact staged bytes and untouched inputs are the script labels; the expected record label is calculated independently of the shell oracle. Do not train on development scripts or their outputs. This is a bounded first intervention: it does not teach arbitrary shell-branch repair or one output per row. Leave those as transfer probes. The 19 prior semantic errors include false effect narration (handled by v3 audit/diff), wrong facts despite a relevant observation (keep whole-record identity when narrowing), and genuinely wrong inspections/comparisons (r8 read/check/compare families exist but task success is still inconsistent). No claim that all 19 are fixed.

## Predeclared pilot, not launched

Corpus build result: `reports/corpus/v3-r9/datacard.json` records 2,466 generated, 2,319 after deduplication, all 2,319 passing the split gate, gold execution and replay. `verified_rows` independently recounted 7,108 next-action rows. This verifies the mechanical build, not independent semantic label review or model quality.

Post-build label check: all 2,164 accepted r8 episode records were unchanged. For each of the 155 additions, the request and source fixture were checked against the recorded result: 45 creations and 44 repairs staged exactly the requested script with the card's literal on its own line; 66 read-only highest/lowest queries returned the label from the independently selected numeric row and staged nothing. All ended `done` with originals unchanged and no tool errors. This is a programmatic check, not human sign-off.

After full corpus replay, split gate, verified row recount and label audit: MiniCPM only for the first comparison. Same v3 interface, cosine, one epoch, 50-minute cap per arm and 80-task roster. Use `--base minicpm --arm control=reports/corpus/v3-r8@cosine --arm treatment=reports/corpus/v3-r9@cosine --train-seed 42 --max-epochs 1 --minutes minicpm=50`; match runtime/device and report realized optimizer steps (additive data means unequal exposure). Verify current evaluation fingerprints before reusing any prior results. Advance to seed 43 only if at least one script task improves, answer passes do not fall below the matched control, and no new forbidden read-only effects appear. Report all category and named regressions; do not promote on one seed. If quoting remains the dominant failure despite improved training fit, test a guarded literal-write interface separately, not in this data comparison. No held-out inference; release gate separate.

Qwen's justification today is a 0.76 GiB Q8_0 artifact versus 2.50 GiB and two reproducible specialized wins, not an established wall-clock advantage. Keep its current weights and reports; revisit at the next interface milestone, or earlier for a sub-1-GiB deployment target. Do not double each experimental run on the assumption that more training closes the gap.
