# lilguy

A small local model that does everyday file tasks for you — read a setting, count matching lines, edit a config, append to a list, tidy files into a folder, rename a folder's files — inside a Linux sandbox. **Nothing it does reaches your files until you've seen the diff and said yes.**

```text
$ lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."
[done]
Executed plan: 2 steps run in the sandbox (commands proposed by the model, recorded by lilguy):
   1. [ok, exit 0] $ fs.read path=staging.conf
   2. [ok, exit 0] $ fs.edit path=staging.conf old=<10 chars> new=<10 chars>

Changes are staged (no approval threshold was crossed); nothing has reached your workspace.

   --- a/staging.conf
   +++ b/staging.conf
   @@ -1,2 +1,2 @@
   -timeout=30
   +timeout=45
    retry=2

Review: lilguy diff
Commit: lilguy commit

Apply this change to /home/you/project? [y/N] y
Applied 1 change(s). Undo with: lilguy undo 1795399978803-24d821c70069
```

lilguy is two halves that only make sense together:

- **The model** — [`lilguy-minicpm5-2b-GGUF`](https://huggingface.co/4rc4n4/lilguy-minicpm5-2b-GGUF), a 2.5 GiB fine-tune of [MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B) that proposes one action at a time in lilguy's protocol. On its own it is not a chat model.
- **The runtime** — this repo. It serves eleven typed tools (file reads and edits, archives, bulk renames), runs every command in a [bubblewrap](https://github.com/containers/bubblewrap) + overlay + [Landlock](https://landlock.io/) sandbox, applies an effect policy (deletes, permission changes and protected files wait for your approval), and keeps a journaled, undoable commit path.

## Requirements

- **Linux** with kernel ≥ 5.11, unprivileged user namespaces, and Landlock. Arch and Fedora work out of the box. On **Ubuntu 24.04+** AppArmor blocks unprivileged user namespaces for bubblewrap; see [Troubleshooting](#troubleshooting).
- **bubblewrap** with `--overlay` support (0.11 or newer) and **python3** at `/usr/bin/python3`.
- **Python ≥ 3.11** and [uv](https://docs.astral.sh/uv/) (or pipx).
- **llama.cpp's `llama-server`** on your `PATH` ([install options](https://github.com/ggml-org/llama.cpp#quick-start)).
- **A GPU is optional.** An NVIDIA GPU with ~3 GB free VRAM answers in about a second; CPU-only works too, at a few seconds per step.

## Install

```bash
uv tool install git+https://github.com/4-R-C-4-N-4/lilguy@v4.0.0
lilguy probe          # checks the sandbox prerequisites; every "required" row must pass
```

## Set up

```bash
lilguy setup          # downloads the model (2.5 GiB, SHA-256 checked) and finds llama-server
```

Options:

| | |
|---|---|
| `lilguy setup --gpu 4070` | pin one NVIDIA GPU by name (recommended on multi-GPU machines) |
| `lilguy setup --cpu` | no GPU; slower but works anywhere |
| `lilguy setup --model FILE.gguf` | use a GGUF you already downloaded |
| `lilguy setup --llama-server PATH` | if `llama-server` is not on `PATH` |

The model server starts by itself on the first `ask`/`do` (port 18088, loopback only) and keeps running until `lilguy stop`. lilguy refuses to talk to any other model it finds on that port.

## Try it

```bash
lilguy demo ~/lilguy-demo     # makes a practice folder and prints these commands
cd ~/lilguy-demo
```

**Ask** — read-only. The answer is quoted from the output of a command that actually ran, never the model's own words; anything that would change a file is refused.

```bash
lilguy ask "What is the timeout in staging.conf?"
lilguy ask "How many lines in access.log contain 404?"
lilguy ask "Which reports are in the reports folder?"
```

**Do** — the change is made in the sandbox and shown as a diff, then lilguy asks once:

```text
$ lilguy do "Change timeout from 30 to 45 in staging.conf. Leave retry unchanged."
...
   -timeout=30
   +timeout=45
    retry=2

Apply this change to /home/you/lilguy-demo? [y/N] y
Applied 1 change(s). Undo with: lilguy undo 1795399978803-24d821c70069
```

Anything but `y` leaves your folder untouched and the change staged.

**Approval** — deleting, moving or renaming files, `chmod`, and protected paths (`.git/`, `.env`, …) cross an approval threshold. The output says why, and the same single prompt becomes `Approve and apply …? [y/N]`:

```bash
lilguy do "Move reports/2024-q1.csv into a new folder reports/archive."
```

**Later** — said no, or want another look? Run these from the same folder. They act on the latest staged change there, so you don't need a session path:

```bash
lilguy diff               # look again
lilguy commit             # apply it after all (one confirmation; approves it too if needed)
lilguy deny               # throw it away
lilguy undo               # list applied changes; `lilguy undo ID` reverses one
```

`lilguy do --stage-only` never prompts. Without a terminal (scripts, pipes) lilguy never prompts either, and `lilguy commit --diff-hash HASH` applies a change only if it still matches the hash you reviewed.

When you're done: `lilguy stop` frees the GPU or CPU.

## What to expect

Use it for **small, explicit, reviewable jobs**: name the file, say what to change, and say what to leave alone. It is a 2B model.

On lilguy's **frozen held-out suite v4**, the 4.0 model completes **95/100 tasks**. Those are 100 tasks it was never trained or tuned on, frozen before it ran and run once. **None** of its changes reached the real folder without a commit. The 3.0 model scores 87/100 on the same suite: nine tasks only 4.0 passed, one only 3.0 passed (exact sign test p ≈ 0.02).

| Held-out v4 family | 4.0 | 3.0 |
|---|---|---|
| Append lines (with or without a final newline) | 10/10 | 9/10 |
| Change a setting next to a near-duplicate key | 10/10 | 10/10 |
| Quote a value from a named section | 5/10 | 2/10 |
| Count exact lines | 10/10 | 9/10 |
| List archive contents | 10/10 | 10/10 |
| Take one member out of an archive | 10/10 | 10/10 |
| Pack a folder into a tar.gz | 10/10 | 10/10 |
| Named file is missing: ask | 10/10 | 10/10 |
| Move two named files (waits for approval) | 10/10 | 7/10 |
| Create a file with exact lines | 10/10 | 10/10 |

**New in 4.0: bulk renames.** `lilguy do "In photos/, replace spaces in the file names with dashes."` or `"... pad the page numbers to 3 digits"`. The model picks the folder, the rule (spaces to dashes, or zero-padding the last number) and optionally which files; lilguy works out every new name, refuses the whole batch if two names would collide, and shows the full `OLD -> NEW` list before anything is renamed. On a 20-task development probe the 4.0 model gets 19/20. Held-out v4 has no rename family, so that number is development evidence.

Read these numbers with care:

- **"Done" is not proof.** On held-out v4, the model said "done" on 3 of its 5 misses. That is why lilguy shows you the diff and asks before applying anything.
- **Weak spots:**
  - quoting a value from a named section of a config file;
  - two-step requests where the second step is a delete ("pack this folder, then delete it");
  - shell quoting of literal `$` text, and per-key sums in tables;
  - scripts.
- **Coming from 3.x, 2.x or 1.x:** run `lilguy setup` again to download the 4.0 model. An older config keeps working: lilguy runs each model on the interface it was trained on (4.0 on v8, 3.0 on v6, 2.0 on v4, 1.x on v3).

## Safety model

- The model never touches your files. Commands run against an overlay copy of the folder in a sandbox with no network, no access outside the folder, and resource limits.
- lilguy, not the model, decides what needs approval. The model cannot approve, commit or undo — those tools are not offered to it.
- Every `do` is recorded (`~/.local/state/lilguy/`), and every commit is journaled and undoable.
- The release passed lilguy's full safety gate: all 18 bypass cases (attempts to escape, write protected files, exhaust disk, smuggle effects through pipes, …) stay contained. That is a statement about the sandbox, not about the model being right.

Run it on folders you can afford to get a wrong suggestion for, and read the diff before you commit.

## Troubleshooting

- **`lilguy probe` fails `unprivileged_userns` on Ubuntu 24.04+**: AppArmor restricts user namespaces. Either allow them for bubblewrap with an AppArmor profile, or (system-wide) `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0`.
- **`bwrap_overlay` fails**: your bubblewrap is older than 0.11; update it.
- **`port 18088 is serving … not lilguy's model`**: another program uses that port. Stop it, or change `port` in `~/.config/lilguy/config.toml`.
- **The model doesn't start**: the server log is `~/.local/state/lilguy/server.log`. On NVIDIA, a driver update needs a reboot before CUDA works again.
- **Multi-GPU machine picks the wrong card**: `lilguy setup --gpu NAME` pins by name (it uses PCI order, which matches `nvidia-smi`).

## How it was made

The model was trained in this repo's model factory: verified episodes replayed in the real sandbox, LoRA fine-tuning, Q8_0 GGUF export, and matched stock-vs-tuned comparisons on named tasks. The developer guide is [docs/FACTORY.md](docs/FACTORY.md); current status and evidence are in [docs/STATUS.md](docs/STATUS.md); the model card is on [Hugging Face](https://huggingface.co/4rc4n4/lilguy-minicpm5-2b-GGUF).

## License

Code: Apache-2.0 ([LICENSE](LICENSE)). Model weights: Apache-2.0, inherited from MiniCPM5-2B. Training examples adapted from [tldr-pages](https://github.com/tldr-pages/tldr) are CC BY 4.0 (see [docs/data/CORPUS-V2.md](docs/data/CORPUS-V2.md)).
