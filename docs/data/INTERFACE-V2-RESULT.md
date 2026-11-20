# Interface v2: first training result (2026-11-20)

Development evidence only. Held-out was re-frozen for v2 and calibrated with scripted controls;
no model has been run on it. Local artifacts: `reports/factory/pilot-2u67f8ec/`
(`comparison.json`, `report.md`, per-task traces).

## What changed

See [the plan](../plan/INTERFACE-V2.md):

- `done` is not a report; lilguy's executed plan and content diff are. `do`, `diff`, `approve`
  and `commit` show both, rebuilt from the session's trusted audit log and layers.
- `ask` is only for a missing input.
- The nine ambiguity tasks became explicit requests (category `explicit`).
- Answer wording is graded only where an answer is the deliverable.
- Corpus revision 5 is revision 4 under v2:
  - 1,595 replayed episodes and 4,901 rows;
  - change, pending and rejection endings are a bare `done` (1,072 rows);
  - questions and no-op reports keep their answer (503 rows);
  - asks remain only for a missing input (20 rows);
  - ambiguity asks are dropped.

## One factory command

```bash
systemd-run --user --scope --collect --unit=lilguy-v2-pilot -p MemoryMax=20G -p MemorySwapMax=1G \
  env CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0 \
  .venv/bin/python -m dev.factory pilot --base minicpm --base qwen08 --data reports/corpus/v2-r5 \
  --minutes minicpm=35 --minutes qwen08=30 --max-epochs 1 \
  --previous minicpm=reports/factory/pilot-_jk0eppk/treatment/minicpm/tuned-q8_0.gguf@1 \
  --previous qwen08=reports/factory/pilot-_jk0eppk/treatment/qwen08/tuned-q8_0.gguf@1
```

Recipe as in the decision sprint: constant LR 2e-4, rank 16, decision weight 5, seed 42. Both
runs stopped at the declared one-epoch cap (307 steps) on the RTX 3090. Training decision fit
on 800 training rows was:

- MiniCPM 77.5%, token fit 95.9%;
- Qwen 91.0%, token fit 97.8%.

Neither reached the 99% target. Cosine warmup/decay was not used; it remains parked in `stash@{0}`.

Stock and tuned are matched Q8_0 pairs scored by the same v2 evaluation on the same device.
The "reference" is last sprint's best adapter (output-orientation treatment, interface v1),
scored on the same 80 tasks with its own v1 prompt, grammar and answer grading. It is not a
matched pair: different interface, different training corpus.

## Results on the 80-task v2 development roster (12 Fast12 + 68 broad)

| Base | Stock v2 | v2 adapter (95% CI) | v1 reference | v2 vs reference |
|---|---:|---:|---:|---|
| MiniCPM5-2B | 19/80 | 43/80 (43–64%) | 43/80 | +10 / −10 tasks |
| Qwen3.5-0.8B | 5/80 | 36/80 (35–56%) | 32/80 | +10 / −6 tasks |

| Category | n | MiniCPM stock | MiniCPM v2 | MiniCPM ref | Qwen stock | Qwen v2 | Qwen ref |
|---|---:|---:|---:|---:|---:|---:|---:|
| delete | 2 | 1 | 2 | 2 | 0 | 2 | 2 |
| edit | 32 | 10 | 12 | 11 | 2 | 11 | 10 |
| explicit | 9 | 5 | 7 | 6 | 1 | 7 | 5 |
| inspect | 12 | 0 | 8 | 7 | 0 | 4 | 4 |
| organise | 9 | 3 | 6 | 6 | 2 | 6 | 3 |
| permissions | 4 | 0 | 2 | 4 | 0 | 2 | 2 |
| read-only | 7 | 0 | 4 | 4 | 0 | 3 | 4 |
| recovery | 2 | 0 | 1 | 2 | 0 | 1 | 2 |
| scripts | 3 | 0 | 1 | 1 | 0 | 0 | 0 |

- MiniCPM v2 beats its stock in every category and passes the no-category-regression gate.
- Qwen v2 has no category regression against stock, but `scripts` stays at 0.
- Against the v1 reference, MiniCPM ties overall and loses `permissions` (4→2) and `recovery` (2→1).
- Qwen gains overall (`organise` and `explicit`) and loses `read-only` (4→3) and `recovery` (2→1).
- All 480 episodes in this job preserved their originals, with no infrastructure failures.

The scores are not comparable with earlier sprints' 80-task totals or targets. Nine tasks
changed and answer grading changed.

## Behaviour checks (from the traces)

- **No change summaries to contradict.** Of the `done` endings, the v2 adapters wrote a bare
  `done` 53/71 times (MiniCPM) and 63/79 times (Qwen). On change tasks the review now relies on
  the executed plan and diff, so the decision sprint's false change claims cannot occur there.
- **New failure: missing answers.** On question tasks the v2 adapters sometimes end with a bare
  `done` and give no answer: MiniCPM 4, Qwen 6 (recounted with `dev/v2_behaviour.py`; an earlier
  hand count of 5 and 7 was a miscount). The v1 reference
  always answered, though often wrongly. Bare endings outnumber answered ones 2:1 in revision 5,
  which plausibly explains this.
- **Unsafe input edits (staged, never committed).** Edits to an existing input that the oracle
  leaves alone:
  - MiniCPM v2: 1 (`format.conf` in a read-only question), against 0 for its reference.
  - Qwen v2: 4 (`run-notes.sh` mode, also present in the reference; `queue/readme.txt`;
    `display.ini` in a "tell me whether you changed it" task; and emptying `postcard-b.txt` in a
    "do not modify either" question, which reached `pending`), against 1 for its reference.
  - This is new unsafe behaviour for both v2 adapters. The guard contained it: nothing reached
    a workspace. The executed plan and content diff make it visible at review.
- **Unexpected policy stops:**
  - MiniCPM v2: none (reference 2).
  - Qwen v2: 2, both from the edits above (reference 1).

## Read

v2 removes the false-summary failure by construction and matches (MiniCPM) or modestly exceeds
(Qwen) the v1 reference on the same tasks. It reaches this with a smaller corpus and the same
exposure. It does not make the models more careful:

- question answers now go missing;
- Qwen edits inputs in read-only tasks more often.

No candidate is promoted.

Next steps, in order:

1. Fix answer omission in the data. Every question episode must end with its answer, so make
   them more frequent or balanced. Consider a harness check that turns a bare `done` on a
   no-change, no-policy-stop episode into an observation asking for the answer. That would be
   an interface change and needs approval.
2. Add read-only contrast episodes that inspect and never write: "do not modify", comparison
   and "tell me whether" requests.
3. Run the agreed cosine warmup/decay experiment as a separate single change on fixed data.
