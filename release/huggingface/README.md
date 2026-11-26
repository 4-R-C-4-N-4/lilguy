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

> **This is not a chat model.** It was trained to emit one action at a time in lilguy's line protocol (`run`, `tool fs.read`, `tool archive.unpack`, …, `done`). lilguy supplies the tools, the sandbox and the observations. Prompted directly, it will be unhelpful. Use it through lilguy.

## Use

```bash
uv tool install git+https://github.com/4-R-C-4-N-4/lilguy@v3.0.0
lilguy probe                 # sandbox prerequisites (Linux, bubblewrap ≥ 0.11, Landlock)
lilguy setup                 # downloads the 3.0 file, checks its SHA-256, finds llama-server
lilguy demo ~/lilguy-demo    # practice folder + commands to try
cd ~/lilguy-demo
lilguy ask "What is the timeout in staging.conf?"
lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."
```

Full instructions, requirements and troubleshooting are in the [README](https://github.com/4-R-C-4-N-4/lilguy#readme).

| File | lilguy | Interface | Held-out | SHA-256 |
|---|---|---|---|---|
| **`lilguy-v3-minicpm5-2b-q8_0.gguf`** | 3.0 | v6 | v3: 86/100 | `2557103c7a05bfbbc320ffdcabeda882ec782f9815f6583cd1dce89938d2bf4d` |
| `lilguy-v2-minicpm5-2b-q8_0.gguf` | 2.0 | v4 | v2: 83/100, v3: 76/100 | `0d90e036f52ee7890df33e877898963d9a657785e0c4cb58532538689be8f233` |
| `lilguy-v1-minicpm5-2b-q8_0.gguf` | 1.x | v3 | v1: 74/100, v2: 76/100 | `5626927a90f9981d56ab94d4bed8495c183487df818af63651c4d32055b18c94` |

All three files are 2,679,706,816 bytes (2.50 GiB). Each one only works on the interface it was trained on, and lilguy picks the right one automatically.

Serving and request settings:
- lilguy serves the model with `llama-server -c 4096 -np 1 -ngl all`.
- Each request is sent with `temperature 0`, `seed 42`, `max_tokens 256` and `chat_template_kwargs: {"enable_thinking": false}`.
- Thinking must stay off. With it on, the model returns no action.
- Every number below was measured with these settings.
- CPU-only (`-ngl 0`) also works, at a few seconds per step.

## Results (3.0 file)

### Held-out suite v3: 86/100

The held-out suite has 100 tasks in 10 families. It was frozen before any model ran on it, never used for training or tuning, and run once on this exact file. Every task ran beside two controls: a scripted correct solution, which passed 100/100, and an immediate "done", which passed 0/100.

| | 3.0 (this file, v6) | 2.0 (v2 file, v4), same suite |
|---|---|---|
| **Completed** | **86/100** (95% CI 78–92%) | 76/100 (67–83%) |
| **Changes reaching the real folder without a commit** | **0** | 0 |
| Infrastructure failures | 0 | 0 |
| Said "done" on a task it got wrong | 11 of 14 misses | 23 of 24 |

| Family | 3.0 | 2.0 |
|---|---|---|
| Delete waits for approval | 10/10 | 10/10 |
| Protected folder: change refused | 10/10 | 10/10 |
| **Count exact lines among near matches** | **10/10** | 6/10 |
| **Named file is missing: ask, don't substitute** | **10/10** | 6/10 |
| Copy, keeping source and destination | 9/10 | 9/10 |
| Two changes, third field kept | 9/10 | 9/10 |
| **Pick the record named by a following field** | **8/10** | 4/10 |
| Create a file with exact content | 8/10 | 8/10 |
| Extract one field from a table | 8/10 | 8/10 |
| Append exact lines (with or without a final newline) | **4/10** | 6/10 |

How to read this:
- **The gains are in noticing and reading.** 3.0 asks about a missing named file instead of editing a similar one, counts exact matches among near-misses, and picks the right record.
- **The gap is likely but not conclusive.** On the same 100 tasks, seventeen were passed only by 3.0 and seven only by 2.0, which gives an exact two-sided sign test p ≈ 0.06.
- **Appends got worse** (4/10 against 6/10). That is the one family where 3.0 scores lower.
- **False completions halved.** 3.0 says "done" on a wrong task 11 times, against 23 for 2.0.

### Development suite: 73/106

There are 106 development tasks, run the same way and on the same code, at each model's interface:
- 3.0: 73/106;
- 2.0: 67/106;
- unmodified MiniCPM5-2B: 27/106.

On archives, 3.0 scores 9/10 against 2.0's 6/10. On an RTX 3090 the median task took 1.0 s end to end, of which 0.24 s was model time.

### Caveats

- **The development number is optimistic.** It was chosen among four artifacts: three seeds and their average. Held-out v3 is the unbiased figure.
- **It can claim success wrongly.** lilguy never applies anything without your yes, and that is the reason.
- **Known weak spots:**
  - appending exact lines;
  - requests with two steps where the second is a delete (for example "pack this folder, then delete it");
  - `chmod` modes stated in words rather than in octal;
  - scripts.

## Intended use

Use it for small, explicit, reviewable jobs on your own machine:
- read a setting;
- count matching lines;
- change one value;
- move named files into a folder;
- list, pack, add to or unpack tar and gzip archives.

Name the file, say what to change, and say what to leave alone.

**Out of scope:**
- unattended automation;
- anything where a wrong action is costly before review;
- use without lilguy's sandbox and review step;
- general chat or coding.

## Training (3.0 file)

- **Base:** `openbmb/MiniCPM5-2B` at revision `42433e90dad95123ab87729fd7011e7110629556` (Apache-2.0).
- **Method:** three LoRA runs, averaged into one model.
  - LoRA (rank 16, alpha 32, dropout 0) on all linear layers.
  - lr **1e-4** with 3% warmup and cosine decay, for **2 epochs** (1,302 optimizer steps).
  - Max length 4096, at seeds 42, 43 and 44. Each run took 171 minutes on one RTX 3090.
  - Loss is weighted 5× on each action's first line, where the decision is made.
  - torch 2.11, transformers 5.15 and peft 0.20.
  - **Averaged ("model soup"):** the three runs' full weight changes (`B·A·α/r` per module) are averaged and added to the base, then converted with llama.cpp to Q8_0.
  - Why averaging: the slower recipe made the seeds agree (they scored 65, 70 and 68 on development, against 59–70 for the earlier recipe), and the average scored above each of them.
- **Data:** corpus revision 14 for interface v6: 10,416 next-action rows from 3,221 multi-turn episodes.
  - Every episode was generated from original fixtures and replayed in the real lilguy sandbox. It was kept only if its scripted actions produced exactly the expected files or answer.
  - It is revision 13 re-recorded under v6, with its archive episodes on the new archive tools, plus 120 new episodes:
    - packing, gzip, adding to and unpacking archives, and comparing an archive with a folder;
    - permission requests stated in words.
  - No personal shell history is used.
  - Shell usage in some examples is adapted from [tldr-pages](https://github.com/tldr-pages/tldr) (CC BY 4.0, pinned revision `2d64595`), and each one credits its page.
  - Training, development and held-out tasks are split by template family and audited for overlap.
- **Interface v6:** a `run` tool plus nine typed tools.
  - The file tools are `fs.list`, `fs.find`, `fs.read`, `fs.grep` and `fs.edit`.
  - The archive tools are `archive.list` (which can compare members with the workspace), `archive.pack`, `archive.add` and `archive.unpack` (which keeps existing files unless told otherwise, and can take out one member).
  - Command output is shown between `<<<` and `>>>`, exactly as printed. A missing final newline is marked.
  - A named file that does not exist is a reason to ask.

Recipes, data generators, evaluation tasks and every round's report are in the [GitHub repo](https://github.com/4-R-C-4-N-4/lilguy) (`dev/`, `docs/data/`, `docs/FACTORY.md`).

## Safety

The guarantees come from lilguy, not from the model:
- commands and typed tools run on an overlay copy of the folder, with no network and with resource limits (bubblewrap + Landlock);
- deletes, permission changes and protected paths (`.git/`, `.env`) wait for human approval;
- the model is never offered approve, commit or undo;
- commits are journaled and undoable.

The 3.0.0 runtime passed lilguy's full 18-case bypass gate. That gate tests the sandbox, not this model's judgement.

## License and attribution

Weights: Apache-2.0, as a derivative of MiniCPM5-2B by OpenBMB. Training examples adapted from tldr-pages are © the tldr-pages team and contributors, CC BY 4.0. lilguy's code is Apache-2.0.
