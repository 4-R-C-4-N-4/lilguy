# Changelog

## 1.1.0

- **One question instead of a commit workflow.** `lilguy do` shows the diff and then asks `Apply …? [y/N]`. For a change that crossed an approval threshold it asks `Approve and apply …? [y/N]`: one yes approves exactly the shown change and writes it, bound to its diff hash. Anything else leaves it staged. Use `--stage-only`, or run without a terminal, to never be asked.
- `lilguy diff`, `commit`, `approve` and `deny` with no session argument act on the latest session with staged changes for the current folder. Printed hints drop the session path when you are in that folder.
- `lilguy commit` of a change waiting for approval shows why it needed approval, then asks once and approves and writes on yes; `lilguy approve` first is no longer required.
- Fixed: the guarded server's stderr went to whatever `sys.stderr` was when the MCP client was imported.
- Held-out result for the 1.0.0 model: 74/100 on the frozen suite (run once). It is now in the README and model card. Added the `factory held-out` job and the v3 held-out recalibration.

## 1.0.0 — first release

The first version of lilguy meant for people other than its author.

**Assistant**
- `lilguy setup` downloads the released model from Hugging Face ([`4rc4n4/lilguy-minicpm5-2b-GGUF`](https://huggingface.co/4rc4n4/lilguy-minicpm5-2b-GGUF)) and checks its SHA-256. It finds `llama-server` and lets you pin a GPU by name (`--gpu 4070`) or run on the CPU (`--cpu`).
- `lilguy ask` and `lilguy do` start the model on demand. They use the same server flags and request settings the evaluation used, and refuse to drive any other model found on their port. `lilguy stop` frees the GPU.
- `lilguy demo` creates a practice folder and prints a walkthrough.
- Sessions, records and commit journals go to one state directory (`~/.local/state/lilguy/sessions`), so `diff`, `commit`, `undo` and `sessions` work without extra flags.
- `lilguy --version`.

**Model.** MiniCPM5-2B, fine-tuned with LoRA on corpus revision 8 (interface v3) and exported as Q8_0 GGUF. On the 80-task development suite it passes 51/80; unmodified MiniCPM5-2B passes 18/80. These are development numbers, not a held-out score. The model card covers the caveats.

**Safety.** The unsandboxed v0.1 runner (`run --unsafe-legacy`, `eval`) is removed. The served tool set is frozen to `run` plus `fs.list`, `fs.find`, `fs.read`, `fs.grep` and `fs.edit`. The full factory safety gate passes, including all 18 bypass cases.

**Fixes.** Requests disable the chat template's thinking mode. With thinking on, the model returned no action. The wheel now ships `toolset.yaml`.
