---
license: apache-2.0
base_model: openbmb/MiniCPM5-2B
base_model_relation: finetune
library_name: gguf
pipeline_tag: text-generation
language:
- en
tags:
- gguf
- llama.cpp
- lora
- agent
- shell
- sandbox
- lilguy
---

# lilguy-minicpm5-2b-GGUF

The model half of **[lilguy](https://github.com/4-R-C-4-N-4/lilguy)**: a small local assistant for everyday file tasks that runs every command in a Linux sandbox and changes nothing until you review the diff and commit it.

This is a LoRA fine-tune of [openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B), merged and exported as a single Q8_0 GGUF for llama.cpp.

> **This is not a chat model.** It was trained to emit one action at a time in lilguy's line protocol (`run`, `tool fs.read`, `tool fs.edit`, …, `done`), with lilguy supplying the tools, the sandbox and the observations. Prompted directly, it will be unhelpful. Use it through lilguy.

## Use

```bash
uv tool install git+https://github.com/4-R-C-4-N-4/lilguy@v1.1.0
lilguy probe                 # sandbox prerequisites (Linux, bubblewrap ≥ 0.11, Landlock)
lilguy setup                 # downloads this file, checks its SHA-256, finds llama-server
lilguy demo ~/lilguy-demo    # practice folder + commands to try
cd ~/lilguy-demo
lilguy ask "What is the timeout in staging.conf?"
lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."
```

Full instructions, requirements and troubleshooting: [README](https://github.com/4-R-C-4-N-4/lilguy#readme).

| File | Size | SHA-256 |
|---|---|---|
| `lilguy-v1-minicpm5-2b-q8_0.gguf` | 2,679,706,816 bytes (2.50 GiB) | `5626927a90f9981d56ab94d4bed8495c183487df818af63651c4d32055b18c94` |

lilguy serves it with `llama-server -c 4096 -np 1 -ngl all` and sends each request with `temperature 0`, `seed 42`, `max_tokens 256` and `chat_template_kwargs: {"enable_thinking": false}`. Thinking must stay off: with it on, the model returns no action. These are the settings every number below was measured with. CPU-only (`-ngl 0`) also works, at a few seconds per step.

## Results

### Development suite: 51/80

lilguy's development suite has 80 tasks that run in the real sandbox on real files and are graded on exact results: files written, text answered, and originals left untouched. Each task also runs a scripted correct solution and a false "done" control, so infrastructure faults are counted separately from model misses. There were none in these runs.

| | Passed (of 80) |
|---|---|
| MiniCPM5-2B, unmodified, same harness and interface | 18 |
| **This model** | **51** (95% CI 53–73%) |

| Category | Passed | Category | Passed |
|---|---|---|---|
| Explicit single-file changes | 9/9 | Inspecting files | 8/12 |
| Deletes (with approval) | 2/2 | Read-only questions | 4/7 |
| Organising files | 7/9 | Edits in general | 16/32 |
| Permissions | 3/4 | Recovery after a failed command | 1/2 |
| Scripts | 1/3 | | |

Measured on an RTX 3090, the median task took 1.1 s end to end, of which 0.24 s was model time.

### Held-out suite: 74/100

The frozen held-out suite has 100 tasks in 10 families written apart from the development tasks. It was never used for training or tuning, and it was run once on this exact file. Scoring was adapted to interface v3 before the run, and that adaptation was checked with controls: the scripted solution passed 100/100 and an immediate "done" passed 0/100.

| | |
|---|---|
| **Completed** | **74/100** (95% CI 65–82%). The project target is ≥ 70%. |
| **Changes reaching the real folder without a commit** | **0**. The target is 0. |
| Infrastructure failures | 0 |
| Said "done" on a task it got wrong | 21 of the 26 misses |

| Family | Passed | Family | Passed |
|---|---|---|---|
| Update a setting value | 10/10 | Protected file: edit must be refused | 10/10 |
| Named file is missing: stop and say so | 8/10 | Delete outside safe paths: waits for approval | 10/10 |
| Pick the explicitly named file of two | 10/10 | Delete a build artifact (auto-approved) | 10/10 |
| Answer a question from a file | 4/10 | Find the file when the path is wrong | 10/10 |
| Append a multi-line block to a log | **0/10** | Edit only the right one of two near-identical lines | 2/10 |

The model is reliable on single-value edits, file selection, the approval and protection gates, and recovering from a wrong path. It fails multi-line appends and context-sensitive edits, and it answers only 4 of 10 read-only questions with a correct quoted value. As in development, a "done" is not proof: review the diff.

**Caveats. Please read before quoting the score:**

- **The development numbers are optimistic.** The training data was revised while watching that suite. This checkpoint is also the best of four comparable training runs of the same recipe, which scored 44, 46, 47 and 51. The held-out result above is the unbiased figure.
- **It can claim success wrongly.** It ended with `done` on 12 wrong development tasks and on 21 of its 26 held-out misses. lilguy never applies anything without you, and that is the reason.
- **Known weak spots:** multi-line appends, edits where the same text appears twice, exact quoted answers, edits that need exact text across several files, comparing file sizes, scripts, and `chmod` requests phrased in words ("only I can read it") rather than octal ("600").

## Intended use

Use it for small, explicit, reviewable jobs on your own machine:
- read a setting;
- count matching lines;
- change one value;
- append a single line;
- create a file;
- move named files into a folder.

Name the file, say what to change, and say what to leave alone.

**Out of scope:**
- unattended automation;
- anything where a wrong action is costly before review;
- use without lilguy's sandbox and review step;
- general chat or coding.

## Training

- **Base:** `openbmb/MiniCPM5-2B` at revision `42433e90dad95123ab87729fd7011e7110629556` (Apache-2.0).
- **Method:** LoRA (rank 16, alpha 32, dropout 0) on all linear layers. lr 2e-4 with 3% warmup and cosine decay; 1 epoch (405 optimizer steps); max length 4096; seed 43. Loss is weighted 5× on each action's first line, where the decision is made. Trained with torch 2.11, transformers 5.15 and peft 0.20 on one RTX 3090 in 36 minutes. The adapter was merged and converted with llama.cpp to Q8_0.
- **Data:** corpus revision 8 for interface v3: 6,465 next-action rows from 2,164 multi-turn episodes. Every episode was generated from original fixtures and **replayed in the real lilguy sandbox**, and kept only if its gold actions produced exactly the expected files or answer. No personal shell history is used. Shell usage in 1,130 examples is adapted from [tldr-pages](https://github.com/tldr-pages/tldr) (CC BY 4.0, pinned revision `2d64595`), and each one credits its page. Training, development and held-out tasks are split by template family and audited for overlap.
- **Interface:** lilguy protocol v3. It has a `run` tool plus five typed tools: `fs.list`, `fs.find`, `fs.read`, `fs.grep` and `fs.edit`. Answers to questions are quoted from the last command's output.

Recipes, data generators, evaluation tasks and every round's report are in the [GitHub repo](https://github.com/4-R-C-4-N-4/lilguy) (`dev/`, `docs/data/`, `docs/FACTORY.md`).

## Safety

The guarantees come from lilguy, not from the model:
- commands run on an overlay copy of the folder, with no network and resource limits (bubblewrap + Landlock);
- deletes, permission changes and protected paths (`.git/`, `.env`) wait for human approval;
- the model is never offered approve, commit or undo;
- commits are journaled and undoable.

The v1.0.0 runtime passed lilguy's full 18-case bypass gate. That gate tests the sandbox, not this model's judgement.

## License and attribution

Weights: Apache-2.0, as a derivative of MiniCPM5-2B by OpenBMB. Training examples adapted from tldr-pages are © the tldr-pages team and contributors, CC BY 4.0. lilguy's code is Apache-2.0.
