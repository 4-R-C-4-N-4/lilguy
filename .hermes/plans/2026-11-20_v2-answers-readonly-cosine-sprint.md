# Sprint goal: answer-complete, read-only-safe v2 data, then cosine vs constant

Repo ~/Work/lilguy, branch main, RTX 3090 only (PCI GPU 0). Five hours, working alone. Read first:
docs/STATUS.md, docs/data/INTERFACE-V2-RESULT.md, docs/plan/INTERFACE-V2.md. Call claimbase
brief and recall for project lilguy.

Starting evidence (v2 roster, 80 tasks):
- MiniCPM v2 43/80 and Qwen v2 36/80, both trained on corpus revision 5 with a constant LR for
  one epoch.
- Training decision fit was 77.5% and 91%.
- Question tasks sometimes end with a bare done and no answer: MiniCPM 5, Qwen 7. Revision 5 has
  1,072 bare-done rows against 503 answered rows.
- Inputs are edited in read-only tasks: MiniCPM 1, Qwen 4. One of these emptied a file in a "do
  not modify" question.

1. Fix the data (shared by every arm). Build revision 6 from revision 5:
   - every question or no-op episode ends with its answer, and question episodes are frequent
     enough that a bare done is not the default for them;
   - add read-only contrast families (compare, check, "tell me whether", "do not modify") that
     inspect and never write, paired with near-identical requests that do write;
   - keep missing-input asks.
   Every episode is replayed through the real loop and sandbox, deduplicated against development
   tasks and passed through the held-out split gate. Record the yield per stage and per family.
   Run a stratified agent audit of 100 new or changed episodes, labelled as an agent audit for
   Ivy to confirm. Development failures informed these families, so mark development scores as
   optimistic.
2. Test one recipe change: warmup plus cosine decay. Apply the parked stash@{0} (3% linear warmup,
   cosine to zero, needs a declared epoch cap) and commit it with its tests. Run both bases
   through one factory command with two arms on revision 6:
   - control: constant LR;
   - treatment: cosine.
   Everything else is identical: seed, rank, dropout 0, decision weight, batching, epoch cap and
   time box. Declare the epoch cap and time boxes before launch from training-only fit and the
   GPU budget, never from development scores. Use the same fixed set of verified training rows
   for every fit measurement, so fit is paired across arms. In the same job, re-score the
   revision-5 v2 adapters on the same roster and fingerprint, to measure the data effect. At most
   two new recipes per base.
3. Prove the result.
   - Keep the 80-task v2 development roster fixed.
   - Compare matched Q8_0 artifacts, evaluation fingerprints and the device.
   - From the traces, report for each arm: answer omissions on question tasks, staged edits of
     existing inputs the oracle leaves alone (especially in read-only tasks), unexpected policy
     stops, and confirmed false answers.
   - Targets:
     - zero answer omissions;
     - no more unsafe input edits than the revision-5 adapters, and none in "do not modify"
       tasks;
     - MiniCPM at least 48/80, Qwen at least 40/80;
     - cosine at least matches the constant-LR fit, with no category regression against control.
   - Report regressions and missed targets honestly. A negative controlled result is acceptable;
     an unexplained aggregate gain is not.

Hard rules:
- Keep interface v2 and its golden prompt; do not add the proposed harness check for a bare done
  without approval.
- Do not run models on held-out; it stays for the shipping candidate.
- Data sources: original fixtures plus pinned tldr-pages with attribution.
- Memory-bounded GPU scopes (20G/1G); keep at least 30 GiB free; preserve earlier adapters.
- Commit milestones locally in the "Area: what changed" style; do not push.
- Stop after five hours or the recipe limit, with a committed result document and an updated
  STATUS.md.
