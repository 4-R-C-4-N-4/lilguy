# Qwen3.5-0.8B: which schedule to test next

Keep cosine as MiniCPM's working recipe and Qwen's control. In the matched [v2 revision-6 study](../data/ANSWER-COSINE-RESULT.md), warmup plus cosine beat constant without warmup on both seeds: Qwen 34 vs 28 and 36 vs 20 out of 80; MiniCPM 50 vs 20 and 53 vs 48. This does not separate warmup from decay or compare cosine to linear.

Two runnable Unsloth notebooks point in different directions. The exact-size 0.8B notebook uses LaTeX image transcription, peak LR 2e-4, 5 warmup steps in 30 updates and linear decay.[1] The 4B typed-decisions notebook uses peak LR 2e-4, 10 warmup steps in 60 updates and cosine decay.[2] The first matches model size; the second is closer to action selection. Neither tests paired schedules on our text-only, multi-turn tasks. Do not port the entire recipe.

## Proposed development test, after the declared revision-8 comparison

Run Qwen only, with the same verified v3 corpus in both arms. Use `--arm control=DIR@cosine --arm treatment=DIR@linear`, seeds 42 and 43 separately, one epoch, unchanged peak LR and 3% warmup. Match optimizer updates (a time-box truncation is not a matched test), row order within each seed, LoRA, loss, export, runtime and task roster. Report named wins and losses on the 80 tasks, answer-task passes and reasons for omissions, edit regressions and read-only effects. Prefer linear only for repeatable answer gains without losing change-task performance; otherwise retain cosine. For ordinary mixed-base pilots the proposed selector is `--base-schedule minicpm=cosine --base-schedule qwen08=linear`; this is an example, not a promotion.

## When to change lilguy instead

In [v3 revision 7](../data/INTERFACE-V3-RESULT.md), Qwen passed 5/23 answer tasks; in 12 the last output lacked the answer. Guessing `^theme=` before seeing `theme: juniper` is a demonstrated data issue; revision 8 restores inspection. If inspecting works but converting the observation to the requested fact still fails across recipes, test a narrow read-only fact tool on those cases. Follow [the approved versioning rule](ROADMAP.md#interface-versioning-adopted-from-v3-on): a new interface gets a numbered plan, frozen prompt and reproducible predecessor, regenerated data and recalibrated controls. A schedule change is not a new interface. Do not select schedules on held-out.

## Workbook verification and trainer comparison

The notebook code below was fetched and inspected at the pinned revision in [1–3], not inferred
from tutorial prose. These are runnable demonstrations, not controlled evidence of an optimum.

| Workbook | Relevant match | Explicit settings | Transfer limits |
|---|---|---|---|
| Qwen3.5-0.8B Vision [1] | Exact checkpoint size | bf16/16-bit LoRA; rank/alpha 16/16; dropout 0; LR 2e-4; linear decay; 5 warmup / 30 updates; batch 2 × accumulation 4; AdamW 8-bit; weight decay 0.001 | LaTeX OCR; adapts vision as well as language; short demo |
| Qwen3.5-4B Decision [2] | Same model family, typed decision task | rank/alpha 16/16; dropout 0; LR 2e-4; cosine; 10 warmup / 60 updates; batch 8 × accumulation 4; weight decay 0.01 | Larger checkpoint; specialized DecisionTrainer; loads in 4-bit, unlike our bf16 path |
| Qwen3-4B Tool Calling [3] | Closest ordinary generative tool-call SFT | rank/alpha 32/32; dropout 0; LR 2e-4; linear; 5 warmup / 60 updates; batch 2 × accumulation 4; AdamW 8-bit; weight decay 0.001; response-only loss | Previous Qwen generation, not Qwen3.5-0.8B; no paired schedule comparison |

Our actual trainer (`dev/v2_train.py`) uses bf16 text-only `Qwen3_5ForCausalLM`, all-linear
LoRA rank/alpha 16/32, dropout 0, LR 2e-4, and final-next-action-only loss with decision-span
weight 5. It uses length-bucketed variable-size batches (up to 16), one optimizer step per
batch, ordinary torch AdamW without explicit weight-decay/beta/epsilon overrides, and a fixed
800-row training-fit probe. The declared cosine runs use 3% warmup. Constant currently has
no warmup at all. Linear is not implemented, nor is the proposed per-base schedule selector.

Consequences:

- The previous experiment supports **warmup plus cosine over no-warmup constant** for Qwen
  too; it does not prove cosine over linear or over warmup-plus-constant. Consult the committed
  ANSWER-COSINE-RESULT rather than treating the recalled historical trainer description as current.
- Both 3.5 notebooks use alpha equal to rank; ours uses alpha twice rank. That is a separate
  adapter-scaling candidate, not something to change together with the schedule.
- Notebook warmup occupies a substantial part of a very short demo. Do not copy the raw
  warmup-step count or train only 30/60 steps on our different corpus.
- Keep bf16 LoRA. The current Unsloth Qwen3.5 guide [4] warns against 4-bit QLoRA because
  of quantization differences; its older pinned decision notebook still uses 4-bit. This source
  disagreement is another reason not to port the notebook wholesale.
- The official model card [5] describes this post-trained 0.8B model as suitable for task-specific
  fine-tuning and says it defaults to non-thinking mode. Keep our deployment-exact template,
  end token, no-thinking setting and text-only loader, rather than changing them with the recipe.

Recommendation order (research proposal, not newly authorized training):

1. Finish and diagnose the declared revision-8 data intervention before another recipe test.
2. Make recipes explicit per base while preserving old command defaults and recorded identities.
3. Test Qwen-only linear versus cosine with identical 3% warmup, peak LR, update count, corpus,
   seed pair and fit probe; retain MiniCPM's working recipe. Record the complete resolved recipe.
4. If train-fit failures remain, investigate per-action fit and consider a separately controlled
   alpha or learning-rate experiment. Full fine-tuning is a later capacity test, not justified by
   these notebooks alone and requires a measured memory/optimizer-step preflight.
5. Keep model and application failure attribution separate. A faithfully learned but awkward
   shell idiom is a data/tool-interface candidate, not automatic evidence for more training.
   Any fact-tool addition follows the approved numbered interface process; no held-out model runs.

No training code, active run, dataset or interface was changed by this research.

## Sources

[1] https://github.com/unslothai/notebooks/blob/d8e941169cb2d101bc5b9ad175a86bbf80450a5b/nb/Qwen3_5_%280_8B%29_Vision.ipynb
[2] https://github.com/unslothai/notebooks/blob/d8e941169cb2d101bc5b9ad175a86bbf80450a5b/nb/Qwen3_5_%284B%29-Decision.ipynb
[3] https://github.com/unslothai/notebooks/blob/d8e941169cb2d101bc5b9ad175a86bbf80450a5b/nb/Qwen3_%284B%29-Tool_Calling.ipynb
[4] https://unsloth.ai/docs/models/qwen3.5/fine-tune
[5] https://huggingface.co/Qwen/Qwen3.5-0.8B
