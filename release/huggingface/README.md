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

> **This is not a chat model.** It was trained to emit one action at a time in lilguy's line protocol (`run`, `tool fs.read`, `tool fs.rename`, …, `done`). lilguy supplies the tools, the sandbox and the observations. Prompted directly, it will be unhelpful. Use it through lilguy.

## Use

```bash
uv tool install git+https://github.com/4-R-C-4-N-4/lilguy@v4.0.0
lilguy probe                 # sandbox prerequisites (Linux, bubblewrap ≥ 0.11, Landlock)
lilguy setup                 # downloads the 4.0 file, checks its SHA-256, finds llama-server
lilguy demo ~/lilguy-demo    # practice folder + commands to try
cd ~/lilguy-demo
lilguy ask "What is the timeout in staging.conf?"
lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."
lilguy do "In scans/, pad the page numbers to 3 digits."
```

Full instructions, requirements and troubleshooting are in the [README](https://github.com/4-R-C-4-N-4/lilguy#readme).

| File | lilguy | Interface | Held-out | SHA-256 |
|---|---|---|---|---|
| **`lilguy-v4-minicpm5-2b-q8_0.gguf`** | 4.0 | v8 | v4: 95/100 | `3f777732ed8d35b2ac744c87e7333cbeada8e3fa5531f05eb789f9ab0da48cf5` |
| `lilguy-v3-minicpm5-2b-q8_0.gguf` | 3.0 | v6 | v3: 86/100, v4: 87/100 | `2557103c7a05bfbbc320ffdcabeda882ec782f9815f6583cd1dce89938d2bf4d` |
| `lilguy-v2-minicpm5-2b-q8_0.gguf` | 2.0 | v4 | v2: 83/100, v3: 76/100 | `0d90e036f52ee7890df33e877898963d9a657785e0c4cb58532538689be8f233` |
| `lilguy-v1-minicpm5-2b-q8_0.gguf` | 1.x | v3 | v1: 74/100, v2: 76/100 | `5626927a90f9981d56ab94d4bed8495c183487df818af63651c4d32055b18c94` |

All four files are 2,679,706,816 bytes (2.50 GiB). Each one only works on the interface it was trained on, and lilguy picks the right one automatically.

Serving and request settings:
- lilguy serves the model with `llama-server -c 4096 -np 1 -ngl all`.
- Each request is sent with `temperature 0`, `seed 42`, `max_tokens 256` and `chat_template_kwargs: {"enable_thinking": false}`.
- Thinking must stay off. With it on, the model returns no action.
- Every number below was measured with these settings.
- CPU-only (`-ngl 0`) also works, at a few seconds per step.

## What's new in 4.0: bulk renames

`fs.rename` renames the files directly inside one folder by one of two rules: **spaces to dashes** (`my photo.jpg` → `my-photo.jpg`) or **zero-padding** the last number in each name to a width (`page7.txt` → `page007.txt`), optionally scoped by a glob on the current names. The model picks the folder, rule and scope; lilguy computes every new name, refuses the whole batch if any two names would collide or a target already exists, and shows the exact `OLD -> NEW` list for approval. Nothing is renamed until you say yes.

On a 20-task development probe of these renames: **19/20** for this file, against 4/20 for 3.0 given the same tool untrained. All 7 zero-padding tasks and all 3 collision tasks pass (on a collision it stops and asks which file should keep the name). The miss is a copy-with-dashes request, where `fs.rename` is not the right tool.

## Results (4.0 file)

### Held-out suite v4: 95/100

The held-out suite has 100 tasks in 10 families. It was frozen before any model ran on it, never used for training or tuning, and run once on this exact file. Every task ran beside two controls: a scripted correct solution, which passed 100/100, and an immediate "done", which passed 0/100, at both interfaces measured.

| | 4.0 (this file, v8) | 3.0 (v3 file, v6), same suite |
|---|---|---|
| **Completed** | **95/100** | 87/100 |
| **Changes reaching the real folder without a commit** | **0** | 0 |
| Infrastructure failures | 0 | 0 |
| Said "done" on a task it got wrong | 3 of 5 misses | 6 of 13 |

| Family | 4.0 | 3.0 |
|---|---|---|
| Append lines (with or without a final newline) | 10/10 | 9/10 |
| Change a setting next to a near-duplicate key | 10/10 | 10/10 |
| **Quote a value from a named section** | **5/10** | 2/10 |
| Count exact lines | 10/10 | 9/10 |
| List archive contents | 10/10 | 10/10 |
| Take one member out of an archive | 10/10 | 10/10 |
| Pack a folder into a tar.gz | 10/10 | 10/10 |
| Named file is missing: ask | 10/10 | 10/10 |
| **Move two named files (waits for approval)** | **10/10** | 7/10 |
| Create a file with exact lines | 10/10 | 10/10 |

How to read this:
- On the same 100 tasks, nine were passed only by 4.0 and one only by 3.0: an exact two-sided sign test gives p ≈ 0.02.
- Held-out v4 has no rename family. It shows the renames training cost nothing elsewhere; the rename evidence is the development probe above.
- Quoting a value from a named section is the weakest family for both models.

### Development suite: 72/106

106 development tasks, run the same way on one RTX 3090: 4.0 72/106 (v8), 3.0 73/106 (v6). The three seeds averaged into this file scored 73, 73 and 74. The project's development rule required the averaged file to reach 73; it missed by one task and was sent to held-out v4 anyway, by a recorded decision, so held-out v4 is the figure that decided this release.

### Caveats

- **It can claim success wrongly.** lilguy never applies anything without your yes, and that is the reason.
- **Known weak spots:**
  - quoting a value from a named section of a config file;
  - requests with two steps where the second is a delete (for example "pack this folder, then delete it");
  - shell quoting of literal `$` text, and per-key sums in tables;
  - scripts.

## Intended use

Use it for small, explicit, reviewable jobs on your own machine:
- read a setting;
- count matching lines;
- change one value;
- move named files into a folder;
- rename a folder's files from spaces to dashes, or zero-pad their numbers;
- list, pack, add to or unpack tar and gzip archives.

Name the file, say what to change, and say what to leave alone.

**Out of scope:**
- unattended automation;
- anything where a wrong action is costly before review;
- use without lilguy's sandbox and review step;
- general chat or coding.

## Training (4.0 file)

- **Base:** `openbmb/MiniCPM5-2B` at revision `42433e90dad95123ab87729fd7011e7110629556` (Apache-2.0).
- **Method:** three LoRA runs, averaged into one model.
  - LoRA (rank 16, alpha 32, dropout 0) on all linear layers.
  - lr **1e-4** with 3% warmup and cosine decay, for up to **2 epochs** (1,390 optimizer steps).
  - Max length 4096, at seeds 42, 43 and 44. Each run took about 197 minutes on one RTX 3090.
  - Loss is weighted 5× on each action's first line, where the decision is made.
  - torch 2.11, transformers 5.15 and peft 0.20.
  - **Averaged ("model soup"):** the three runs' full weight changes (`B·A·α/r` per module) are averaged and added to the base, then converted with llama.cpp to Q8_0.
- **Data:** corpus revision 16 for interface v8: 11,106 next-action rows from 3,451 multi-turn episodes.
  - Every episode was generated from original fixtures and replayed in the real lilguy sandbox. It was kept only if its scripted actions produced exactly the expected files or answer.
  - It is revision 14 (3.0's data) re-recorded under v8, plus 230 rename episodes: spaces to dashes (by extension or by leading word), zero-padding at widths 2–4, collisions that end in a question, recovering from a glob written in the new form, and near-misses where `fs.rename` is not the right tool (one file, a copy, lowercasing, stripping a prefix).
  - No personal shell history is used.
  - Shell usage in some examples is adapted from [tldr-pages](https://github.com/tldr-pages/tldr) (CC BY 4.0, pinned revision `2d64595`), and each one credits its page.
  - Training, development and held-out tasks are split by template family and audited for overlap.
- **Interface v8:** v6 (a `run` tool plus nine typed tools: `fs.list`, `fs.find`, `fs.read`, `fs.grep`, `fs.edit`, `archive.list`, `archive.pack`, `archive.add`, `archive.unpack`) plus `fs.rename`.

Recipes, data generators, evaluation tasks and every round's report are in the [GitHub repo](https://github.com/4-R-C-4-N-4/lilguy) (`dev/`, `docs/data/`, `docs/FACTORY.md`).

## Safety

The guarantees come from lilguy, not from the model:
- commands and typed tools run on an overlay copy of the folder, with no network and with resource limits (bubblewrap + Landlock);
- deletes, renames, permission changes and protected paths (`.git/`, `.env`) wait for human approval;
- the model is never offered approve, commit or undo;
- commits are journaled and undoable.

The 4.0.0 runtime passed lilguy's full 18-case bypass gate. That gate tests the sandbox, not this model's judgement.

## License and attribution

Weights: Apache-2.0, as a derivative of MiniCPM5-2B by OpenBMB. Training examples adapted from tldr-pages are © the tldr-pages team and contributors, CC BY 4.0. lilguy's code is Apache-2.0.
