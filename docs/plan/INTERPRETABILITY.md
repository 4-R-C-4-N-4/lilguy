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

## Lesson 2: coin flips or habits? Margins on r12's roster losses (2026-11-23)

**Setup:**
- **Script:** `dev/interp/lessons.py margins`. **Output:** `reports/interp/lessons-2-4/margins.json`.
- **Tasks:** the 13 roster tasks that 2.0 passes on v5 and at least one r12 seed fails.
- **Method:** for each failing seed, find the first action where its trace left 2.0's passing trace. Then score log P(its action) − log P(2.0's action) on the shared history, under every model.
- **Thresholds:**
  - **≥ +2 nats:** a habit;
  - **under 1 in either direction:** a coin flip;
  - **≤ −2:** not reproduced. In bf16 the failing model itself prefers the correct action, so its miss came from greedy decoding on the Q8_0 server.

Some first divergences are harmless (reading a file before acting, listing `.` instead of a subfolder). Those are marked and not counted.

| Task (failing seed) | Divergence | Failing model | Other models | Reading |
|---|---|---|---|---|
| `executable_tools_group_pending` (s42, s43) | `chmod g+s` vs `g+x` | **+3.0**, +0.5 | stock −3.0, 2.0 −0.5 | **habit grown in r12**, strong at s42; the permission-wording weakness |
| `rejected_protected_file` (s42) | `sed -i` vs `fs.edit` on a protected file | **+3.8** | all others −0.7 to −7.9 | **seed-specific habit** (r12 s42 only) |
| `copy_east_welcome_line` (s42) | writes an extra line | **+2.0** | all others −21 to −27 | **seed-specific habit** |
| `copy_review_folder_structure` (s43) | `cp -r review package/review/` vs `review/*` | **+2.3** | r11 −0.2/−0.1, 2.0 −4.5 | habit at s43; r11 was already near a coin flip |
| `insert_line_at_changelog_heading` (s42) | the edit with request words copied into the line | **+7.1** | stock +7.0, r11 s43 +7.1, 2.0 −17, r12 s43 −12 | a base-model preference that some seeds keep and others remove |
| `restrict_local_draft_mode` (s42) | `chmod 644` vs `600` | +0.9 | −0.5 to −5.3 | coin flip |
| `extract_email_column` (s42) | `cut -f1` without reading first | −0.4 | −3.6 to −11 | coin flip |
| `generate_tuple_named_notes` (s42; s43) | the loop body | −0.8; −2.2 | −7 to −27 | coin flip; not reproduced |
| `matching_normalized_addresses` (s42; s43) | a broken `diff` pipeline | −23; −5.5 | −26 to −80 | **not reproduced** (the Q8_0 greedy path) |
| `aggregate_signed_amounts` (s42) | a broken `awk -F` | −12 | −17 to −37 | **not reproduced**. s43's `NR>1` is lesson 1: 0.43 |
| `find_todo_comments`, `latest_iso_timestamp`, `move_closed_batch_pending` (s43) | read or list first | — | — | harmless first divergence; the real error comes later |

**What it shows:**

1. **About half of r12's losses are not habits.**
   - Five are coin flips or "not reproduced": in bf16 the failing model prefers the right action, and greedy decoding on the 8-bit server went the other way.
   - Writing data for these would be chasing noise.
2. **Most real habits belong to one seed.**
   - `sed` on a protected file and the extra written line appear only in r12 s42; every other model is strongly against them (−3 to −27).
   - Seed-to-seed swings on the same decision reach 20 nats (`insert`: +7.1 against −12.4).
   - Two seeds share a habit only for `chmod g+s`, and the folder copy is borderline.
3. **The one habit that training clearly built is the old permission-wording weakness.** It is also the most consequential of these losses: a wrong permission change, though one that waits for review.
4. **Consequence for the factory:** a roster loss should count as evidence for new data only if its margin is ≥ 2 at both seeds. Under that rule, r12's 13 losses come down to about 2 actionable items.

## Lesson 3: where does the append-for-insert habit live? Activation patching (2026-11-23)

**Setup:**
- **Script:** `dev/interp/lessons.py patch`. **Output:** `patch.json`.
- **Decision point:** the roster task `insert_line_at_changelog_heading`, right after reading `briefing.md`.
- **r11 s42 (the habit model) prefers** `printf … >> briefing.md` over 2.0's block `fs.edit` by **+5.05 nats**. 2.0 prefers the edit by **−14.96**.
- **Method:** run r11, but replace one layer's output with 2.0's at the same positions. Measure what fraction of the 20-nat gap closes.

**Patching every prompt position, one layer at a time:**
- **Layers 0–6:** under 10% of the gap closes.
- **Layers 7–19:** 12–23%.
- **Layers 20–30:** rises to about 34%.
- **Layers 31–41:** about 36–38%.

**Patching one segment of the prompt, every fourth layer:**

| Segment patched | Fraction of the gap closed |
|---|---|
| System prompt | ≤ 0.03 at every layer |
| Request text | ≤ 0.06 (largest at layers 8–12) |
| The earlier read and its observation | ≤ 0.05 |
| **The answer slot** (where the model starts writing its action) | 0.10 at layer 20 → **0.22 at 24 → 0.32 at 28 → 0.36 at 40** |

**What it shows:**

1. **Both models read the request and the file the same way.** Swapping in 2.0's representation of the request or the file contents changes almost nothing (≤ 6%). r11 does not misunderstand "under ## Friday".
2. **The difference is computed late, at the point of writing the answer.** It is concentrated in layers 20–30 at the answer slot, the same late band where lesson 1's logit lens saw decisions form.
3. **Most of the habit (about 62%) is not in the prompt states at all.** It is in how r11 writes its own action tokens. That is the signature of an output habit (a learned "this is how I add lines" template), not of a comprehension error.

## Lesson 4: can a direction flip it without training? Steering (2026-11-23)

**Setup:**
- **Script:** `dev/interp/lessons.py steer`. **Output:** `steer.json`.
- **Building the direction:** 12 synthetic pairs, all new (not roster, not held-out). Each pair is the same Markdown file read, then either "Add X **directly under ## Heading**" or "Add X **as the very last line**". The direction is r11's mean difference at the last prompt token between the two, scaled to a typical residual norm.
- **Applying it:** add α × direction to one layer's output. Measure the roster margin, and an **append control**: a held-back append request, which must still prefer the append (control < 0).

| Layer | α = 0.05 | 0.1 | 0.2 | **0.4** | Append control at 0.4 |
|---|---|---|---|---|---|
| 8 | +5.0 | +5.0 | +4.8 | +3.7 | −29.7 |
| 14 | +5.0 | +4.8 | +4.7 | −0.9 | −29.0 |
| 20 | +4.3 | +2.9 | −1.2 | −7.3 | −30.7 |
| **26** | +4.4 | +3.4 | −1.2 | **−12.5** | **−42.4** |
| 32 | +4.9 | +4.7 | +4.2 | +2.0 | −40.7 |
| 38 | +4.6 | +4.4 | +3.4 | +0.5 | −32.1 |

**Generated actions (r11 s42, greedy):**
- **Unsteered:** `printf '%s\n' '- Verify projector' '## Friday' >> briefing.md`, which is the habit.
- **Steered, layer 26, α 0.4:** `sed -i '2a - Verify projector directly beneath ## Friday, before existing entries' briefing.md`. It now *inserts*: the intent flipped.
- **Same steering on the append control:** `printf '%s\n' '- ember' >> amber-notes.md`, still a correct append.

**What it shows:**

1. **The model already knows the difference between "insert" and "append".** A single direction, read off its own activations, flips the habit by 17.5 nats at layer 26 and leaves real appends alone. Training did not destroy the concept; the r11 data mix made "append" the default way of writing an addition. That is exactly lesson 3's late answer-slot effect.
2. **Flipping the intent is not enough to get the action right.** The steered model inserts at the wrong line (`2a`, before `## Thursday`) and copies request words into the new line. Knowing *what* to do and *how* to do it precisely (a block `fs.edit` at the right heading) are separate skills. The second still needs examples.
3. **Steering is a diagnostic here, not a fix to ship.** lilguy serves Q8_0 GGUFs through llama.cpp, where injecting a direction is possible (control vectors) but changes the tested artifact.

## What these lessons change

- **Gate data on margins.** Write data only for losses with a margin ≥ 2 at both seeds. For r12 that is the permission wording (`g+s`) and possibly the folder-copy form, not 13 tasks.
- **Rebalance, don't add.** The append/insert habit is an output-template default, not a comprehension gap.
  - The fix is the mix: more insert episodes relative to appends, weighted at the answer step.
  - Add near-miss twins, so the same file and heading appear with both requests.
- **Seed variance is the biggest single factor in these numbers.** Single decisions swing by up to 20 nats between seeds trained on identical data. Promotion needs at least two seeds, and the roster delta must be read against that spread.

## Lesson 5: margins in the factory (2026-11-23)

`dev.factory margins --pilot PILOT [--pilot PILOT]` runs lesson 2 for any round. It uses the training Python, on whichever GPU the caller makes visible, and writes `reports/factory/margins-*/margins.{json,md}`.

**Columns and verdicts:**
- every roster task the reference (2.0 on v5) passes and a candidate seed fails;
- the first divergence from the reference trace, scored under stock, 2.0 and each seed;
- the verdict: habit / lean / coin flip / not reproduced / harmless first look (an extra read or listing at step 0);
- **actionable**: tasks that are a habit at every seed that lost them, with at least two seeds.

**r12 (run on the RTX 4070):** 13 lost tasks.

| Verdict | Count |
|---|---|
| habit | 4 |
| lean | 3 |
| coin flip | 3 |
| not reproduced | 3 |
| harmless first look | 5 |
| **actionable** | **none** |

- **No r12 loss is a habit at both seeds.** Under this rule, round 12 gave no evidence for new training data at all.
- **Margins depend slightly on the hardware.** The 4070 run differs from the 3090 run by up to about 0.6 nats; for example, `copy_east_welcome_line` moved from +2.0 to +1.8. Verdicts near a threshold are therefore soft, which is one more reason to require two seeds.

## Lesson 7: the permission mistake, `chmod g+s` against `g+x` (2026-11-23)

**Setup:**
- **Script:** `dev/interp/lessons.py patch|steer --case chmod`. **Output:** `reports/interp/lesson-7/`.
- **Decision point:** the roster task `executable_tools_group_pending`, after listing `helpers/`. The request asks for the scripts to be executable by their group.
- **Margins:**
  - r12 s42 prefers `chmod g+s` by **+2.75**;
  - 2.0 prefers `g+x` by −0.87;
  - stock −2.9.
  The 4070 measured +2.8 and −0.9.

### Patching (2.0's states into r12 s42)

**Every prompt position:**
- **Layers 5–16:** 28–59% of the gap closes (most at layer 14, 0.59).
- **Layers 17–27:** the effect goes **negative**, down to −0.63 at layer 21. Here 2.0's later states make r12 *more* wrong, so the two models compute the answer differently from this point on.

**The request span alone** closes the whole gap at layer 8 (**1.00**), 0.48 at layer 12 and 0.31 at 16, then −0.62 at layer 24.

**Answer slot and earlier turns:** at most 0.17 at any layer.

**This is the opposite of the insert habit:**

| Habit | Where it is | What kind of error |
|---|---|---|
| append-for-insert (lesson 3) | the answer slot, late (layers 20–30) | the request is understood correctly; the action is written from a learned template |
| **`g+s` for "executable by the group"** | the **request tokens, early to middle (layers 8–16)** | **how the words are read**: "the group can execute" is mapped to the wrong mode letter while the request is being understood |

### Steering

- **The direction:** "let the group execute" minus "let the group write", built from 12 synthetic folder listings. 4 more are held back as controls; a "writable" request must keep preferring `g+w` over `g+x`.
- **What worked, and how far:**
  - Only **layer 8** steers cleanly. At α 0.4 the margin goes from +2.75 to **−1.52**, and the control stays at −6.9.
  - Layer 26 flips the margin too (−1.25), but it breaks the control (+2.96).
  - Layer 20 makes the mistake *stronger*.
- **Generated actions:**
  - **Unsteered:** `chmod g+s helpers/*.sh`.
  - **Steered:** `chmod +g +x helpers/*.sh`. It now reaches for `x`, but writes an invalid mode.
  - **Steered control:** `chmod -R u+r,g+r quince-bin`. The control's *margin* still favours `g+w`, but its greedy action drifted to a third, wrong command.

### What it shows

1. **Permissions are a knowledge gap, not a habit.**
   - The fault sits where the request is read.
   - Steering pushes the model towards `x` but cannot make it write valid mode syntax.
   - Even the steered control loses `w`.
   The model's grasp of symbolic chmod modes is weak in general. That matches the [permission contrast](../data/PERMISSION-CONTRAST.md), where stating the mode explicitly (`600`) rescued the guarded runs.
2. **This is a case for the interface, not more data.** The factory's premise is that when a capability is shaky, the application should take the burden. A typed permission tool (who: user/group/others; what: read/write/execute; add/remove) would let lilguy own the mapping to mode bits, the way `fs.edit` took over quoting. That would be a candidate interface version after v5.

## Next lessons

| # | Lesson | Question |
|---|---|---|
| 6 | **Mix experiment: done** ([R13](../data/R13-V5-RESULT.md)) | The append-for-insert habit is gone at both seeds. The only actionable loss left is an ambiguous, unquoted request. Roster 53 and 48 against 54: seed spread now dominates. |
| 8 | **A typed permission tool** | Plan it as an interface change; measure 2.0 and r12 on it before any training. |
