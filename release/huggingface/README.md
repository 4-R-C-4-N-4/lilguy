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

The model half of **[lilguy](https://github.com/4-R-C-4-N-4/lilguy)**: a small local assistant for everyday file tasks. It runs every command in a Linux sandbox, shows you the diff, and changes nothing until you say yes.

This is a LoRA fine-tune of [openbmb/MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B), merged and exported as a single Q8_0 GGUF for llama.cpp.

> **This is not a chat model.** It was trained to emit one action at a time in lilguy's line protocol (`run`, `tool fs.read`, `tool fs.edit`, …, `done`). lilguy supplies the tools, the sandbox and the observations. Prompted directly, it will be unhelpful. Use it through lilguy.

## Use

```bash
uv tool install git+https://github.com/4-R-C-4-N-4/lilguy@v2.0.0
lilguy probe                 # sandbox prerequisites (Linux, bubblewrap ≥ 0.11, Landlock)
lilguy setup                 # downloads the 2.0 file, checks its SHA-256, finds llama-server
lilguy demo ~/lilguy-demo    # practice folder + commands to try
cd ~/lilguy-demo
lilguy ask "What is the timeout in staging.conf?"
lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."
```

Full instructions, requirements and troubleshooting are in the [README](https://github.com/4-R-C-4-N-4/lilguy#readme).

| File | lilguy | Interface | Held-out | SHA-256 |
|---|---|---|---|---|
| **`lilguy-v2-minicpm5-2b-q8_0.gguf`** | 2.0 | v4 | v2: 83/100 | `0d90e036f52ee7890df33e877898963d9a657785e0c4cb58532538689be8f233` |
| `lilguy-v1-minicpm5-2b-q8_0.gguf` | 1.x | v3 | v1: 74/100, v2: 76/100 | `5626927a90f9981d56ab94d4bed8495c183487df818af63651c4d32055b18c94` |

Both files are 2,679,706,816 bytes (2.50 GiB). Each one only works on the interface it was trained on, and lilguy picks the right one automatically.

Serving and request settings:
- lilguy serves the model with `llama-server -c 4096 -np 1 -ngl all`.
- Each request is sent with `temperature 0`, `seed 42`, `max_tokens 256` and `chat_template_kwargs: {"enable_thinking": false}`.
- Thinking must stay off. With it on, the model returns no action.
- Every number below was measured with these settings.
- CPU-only (`-ngl 0`) also works, at a few seconds per step.

## Results (2.0 file)

### Held-out suite v2: 83/100

The held-out suite has 100 tasks in 10 families. It was frozen before this model ran on it, never used for training or tuning, and run once on this exact file. Every task ran beside two controls: a scripted correct solution, which passed 100/100, and an immediate "done", which passed 0/100.

| | 2.0 (this file) | 1.0 (v1 file), same suite |
|---|---|---|
| **Completed** | **83/100** (95% CI 75–89%) | 76/100 |
| **Changes reaching the real folder without a commit** | **0** | 0 |
| Infrastructure failures | 0 | 0 |
| Said "done" on a task it got wrong | 16 of 17 misses | 13 of 24 |

| Family | 2.0 | 1.0 |
|---|---|---|
| Move into a folder (waits for approval) | 10/10 | 10/10 |
| Protected file: edit refused | 10/10 | 10/10 |
| Find a file in a subfolder, then edit | 10/10 | 10/10 |
| Append two or three lines | 10/10 | 9/10 |
| Change one setting | 9/10 | 9/10 |
| **Change a line that also appears in another block** | **9/10** | **0/10** |
| Quote a value from a file | 8/10 | 10/10 |
| Count matching lines | 8/10 | 10/10 |
| Named file is missing: ask instead of guessing | 5/10 | 4/10 |
| Create a file with exact lines | 4/10 | 4/10 |

How to read this:
- **One skill drives the gain.** 2.0 learned the one thing it was trained for: editing a line that also occurs elsewhere, via a multi-line `old` that includes a neighbouring line.
- **The overall gap is not significant on its own.** Twelve tasks were passed only by 2.0 and five only by 1.0, which gives an exact McNemar p ≈ 0.14.
- **Questions got slightly worse.** 2.0 lost four question tasks against 1.0.

### Development suite: 53/80

There are 80 development tasks, run the same way.
- 2.0: 53/80 (95% CI 55–76%).
- 1.0 on the same code: 51/80.
- Unmodified MiniCPM5-2B: 19/80.

A second training run of the same recipe (seed 43) scored 52/80. On an RTX 3090 the median task took 0.9 s end to end, of which 0.22 s was model time.

### Caveats

- **The development numbers are optimistic.** The training data was revised while watching that suite. Held-out v2 is the unbiased figure.
- **It can claim success wrongly.** lilguy never applies anything without your yes, and that is the reason.
- **Known weak spots:**
  - creating a file with exact multi-line content;
  - noticing that a named file is missing rather than choosing a similar one;
  - appending to a file that has no final newline;
  - scripts;
  - `chmod` modes stated in words rather than in octal.

## Intended use

Use it for small, explicit, reviewable jobs on your own machine:
- read a setting;
- count matching lines;
- change one value, including one of several identical lines in different sections;
- append a few lines;
- move named files into a folder.

Name the file, say what to change, and say what to leave alone.

**Out of scope:**
- unattended automation;
- anything where a wrong action is costly before review;
- use without lilguy's sandbox and review step;
- general chat or coding.

## Training (2.0 file)

- **Base:** `openbmb/MiniCPM5-2B` at revision `42433e90dad95123ab87729fd7011e7110629556` (Apache-2.0).
- **Method:**
  - LoRA (rank 16, alpha 32, dropout 0) on all linear layers.
  - lr 2e-4 with 3% warmup and cosine decay, for 1 epoch (485 optimizer steps). Training stopped at the fit target.
  - Max length 4096, seed 42.
  - Loss is weighted 5× on each action's first line, where the decision is made.
  - torch 2.11, transformers 5.15 and peft 0.20, on one RTX 3090 in 47 minutes.
  - The adapter was merged and converted with llama.cpp to Q8_0.
- **Data:** corpus revision 10 for interface v4: 7,745 next-action rows from 2,484 multi-turn episodes.
  - Every episode was generated from original fixtures and replayed in the real lilguy sandbox. It was kept only if its scripted actions produced exactly the expected files or answer.
  - It is revision 8 re-recorded under v4, plus 320 episodes in four new families: multi-line `old <<<` edits for repeated lines, multi-line appends, appends to files without a final newline, and indented appends.
  - No personal shell history is used.
  - Shell usage in some examples is adapted from [tldr-pages](https://github.com/tldr-pages/tldr) (CC BY 4.0, pinned revision `2d64595`), and each one credits its page.
  - Training, development and held-out tasks are split by template family and audited for overlap.
- **Interface v4:** a `run` tool plus five typed tools: `fs.list`, `fs.find`, `fs.read`, `fs.grep` and `fs.edit`.
  - Command output is shown between `<<<` and `>>>`, exactly as printed.
  - `fs.edit` refusals say whether the old text is missing or repeated, and on which lines.
  - Answers to questions are quoted from the last command's output.

Recipes, data generators, evaluation tasks and every round's report are in the [GitHub repo](https://github.com/4-R-C-4-N-4/lilguy) (`dev/`, `docs/data/`, `docs/FACTORY.md`).

## Safety

The guarantees come from lilguy, not from the model:
- commands run on an overlay copy of the folder, with no network and with resource limits (bubblewrap + Landlock);
- deletes, permission changes and protected paths (`.git/`, `.env`) wait for human approval;
- the model is never offered approve, commit or undo;
- commits are journaled and undoable.

The 2.0.0 runtime passed lilguy's full 18-case bypass gate. That gate tests the sandbox, not this model's judgement.

## License and attribution

Weights: Apache-2.0, as a derivative of MiniCPM5-2B by OpenBMB. Training examples adapted from tldr-pages are © the tldr-pages team and contributors, CC BY 4.0. lilguy's code is Apache-2.0.
