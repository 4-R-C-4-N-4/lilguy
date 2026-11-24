# Looking inside: why does the lilguy model make a mistake?

Status: started 2026-11-23, after rounds 11–12. Those rounds fixed 2.0's weak spots but kept losing nearby tasks, and every explanation so far was a guess from traces. This plan replaces some of the guessing with measurements inside the model.

The rules are the same as everywhere else:
- development fixtures only, never a held-out task;
- every claim has a reproducible script and its saved output under `reports/interp/` (gitignored);
- every script runs with the training Python (`LILGUY_TRAIN_PYTHON`, torch 2.11, transformers 5.15, peft 0.20).

## The toolbox, from cheapest to most powerful

| # | Approach | Question it answers | Cost here |
|---|---|---|---|
| 1 | **Preference probe**: log P(habit) − log P(correct) for two complete next actions at one recorded decision point | Does the model prefer the mistake, by how much, and does that move when the input changes? | seconds |
| 2 | **Counterfactual twin**: the same prefix with one fact changed (the file *has* a header) | Is the model reading the input at all for this choice? | seconds |
| 3 | **LoRA layer ablation**: turn the adapter's update off in one band of layers, or on only there | Which layers did *training* change to produce this behaviour? | a minute |
| 4 | **Logit lens**: decode every layer's residual stream at the decision token | At which depth is the choice made? | seconds |
| 5 | **Activation patching**: run the twin and copy one layer's activations into the real run | Which layer and token *cause* the choice? This is the causal version of 3 and 4. | minutes |
| 6 | **Linear probes**: train a tiny classifier on activations ("does this file have a header?") | Does the model represent the fact it needs? | minutes |
| 7 | **Steering vectors**: add the mean activation difference between twins during generation | Can the behaviour be pushed without training? | minutes |
| 8 | **Weight edits**: rank-one edits (ROME/MEMIT), scaling or removing the LoRA update per layer, task arithmetic | Can a localised mistake be fixed in the weights? | an hour+ |
| 9 | **Sparse autoencoders**: learn a dictionary of interpretable features from activations | What concepts does the model use? | a day+ (none exist for MiniCPM5) |

### On "models that look at weights and edit them"

- **Weights alone say little.** The LoRA update of a layer is a matrix. Its size shows that training changed the layer, not what it learned.
- **What can be read is activations:** the values flowing through the weights on a particular input. Methods 3–7 all work there.
- **Weight editing does exist.**
  - ROME and MEMIT rewrite single facts ("the Eiffel Tower is in Rome") with a rank-one change to one MLP layer.
  - Task arithmetic adds or subtracts whole fine-tuning updates.
  - Both work best for **localised** knowledge. Lesson 1 shows that the behaviour we care about here is spread across layers, so a surgical edit is unlikely to be the fix.

## Lesson 1: the "header-skip habit" (2026-11-23)

**Setup:**
- **Script:** `dev/interp/habit_probe.py`. **Output:** `reports/interp/header-skip/probe.json`.
- **Decision point:** the roster task `aggregate_signed_amounts` on v5. The model has just read `adjustments.txt` (`18`, `-5`, `2`, `-4`, with no header) and must pick the command that answers "what is the net total?".
- **Candidates:**
  - habit: `awk 'NR>1 {s+=$0} END {print s}'` (skips line 1);
  - correct: `awk '{s+=$0} END {print s}'`.
- **Twin:** the same file with an `amount` header line, where skipping line 1 is right.

**Preference (nats; positive means the habit is preferred):**

| Model | Real file (no header) | Twin (has header) | Roster result on this task |
|---|---|---|---|
| Stock MiniCPM5-2B | **+0.71** | +2.04 | — |
| 2.0 (r10 s42) | −0.37 | +0.99 | pass |
| r11 s42 | −1.30 | +1.09 | pass |
| r11 s43 | −6.29 | +0.71 | pass |
| r12 s42 | −7.04 | −0.92 | fail (different error: skipped the read, looped) |
| r12 s43 | **−0.43** | +2.06 | **fail: used `NR>1`** |

**What it shows:**

1. **The habit was not learned in round 11; the base model already has it.** Untuned MiniCPM prefers skipping line 1 even with no header. Every tuned model moves away from it, including r11, which the round-12 report wrongly blamed (now corrected).
2. **Every model reads the file.** For every model the twin pushes towards the habit (by 1.4 to 7 nats), so the header line changes the decision. The failing model is not ignoring the input.
3. **The failing model barely preferred the correct command.** r12 s43 favoured it by only 0.43 nats. That is close to a coin flip, and the Q8_0 server's rounding tipped it the wrong way. Seed-to-seed spread on this one decision is 0.4 to 7 nats. **Lesson:** a single failed task in a roster run can be a marginal decision, not a habit. Before writing data for a failure, measure the margin.
4. **There is no single layer to fix.** Switching the adapter off band by band, or on in only one band, moves the preference in both directions with no clear location. For r12 s42 the largest single effect is layers 7–13 (−7.0 → −2.9 when removed). For r11 s42 it is layers 14–20. This behaviour is distributed, which argues against a surgical weight edit.
5. **The decision is made late.** The logit lens at the divergence token (`␣'` against `␣'{`) is flat until about layer 30. The generic quote token peaks around layer 36, and the choice between the two forms appears in the **last 5–6 layers**.

## Next lessons

| # | Lesson | Question | Method |
|---|---|---|---|
| 2 | **Margins across the roster** | Which roster misses are coin flips, and which are real habits? | Preference probe at the first consequential error of each shared loss (`copy_review_folder_structure`, `insert_line_at_changelog_heading`, the `chmod g+s` task). Tasks with margins under about 1 nat get measured, not trained for. |
| 3 | **Causal patching on the append-for-insert habit** | Where does "add a line → `>>`" come from? | Patch r10's activations into r11's run layer by layer and token by token on the `## Friday` prefix. |
| 4 | **Steering** | Can an "insert, not append" direction, taken from twin prompts, flip the behaviour without training? | If yes, the representation exists and the training data is what is off-balance. |
| 5 | **A decision-margin gate for the factory** | — | Add the margin probe to `dev.factory` so every round reports margins as well as pass/fail. |
