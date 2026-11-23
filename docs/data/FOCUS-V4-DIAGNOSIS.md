# v4 focus diagnosis (2026-11-23)

Fifteen fresh development fixtures (`dev/dev_focus.py`) were run on the 1.0 model (r8, seed 43) and on stock MiniCPM5-2B, both under interface v3 on the RTX 3090. Every task ran beside its two controls (the scripted solution passes, an immediate "done" fails), and there were zero infrastructure failures. Evidence: `reports/factory/focus-v4-20261123-0741/`. No held-out trace was read.

| Group | Stock | 1.0 (r8) |
|---|---|---|
| Multi-line append | 1/5 | 2/5 |
| Edit when the target line occurs twice | 0/5 | **0/5** |
| Exact quoted answer | 2/5 | 5/5 |

Training fixed the questions. On these fixtures, the held-out 4/10 for questions did not reproduce. Edits and appends fail for three separate reasons.

## 1. The model doesn't know how to write a multi-line `old` (data)

This failure appears in all five 1.0 misses on repeated-text edits.

The model tries `fs.edit` with `old` set to a line that occurs twice, and lilguy refuses. It then tries to express "this line plus the next" by typing `\n` inside a one-line value:

```
tool fs.edit
path: orders.txt
old:   order B-2
new:   order B-2\n  status: shipped
```

The protocol already has a syntax for multi-line values (`old <<<` … `>>>`), and the system prompt mentions it. **None of the 6,465 r8 training rows use it.** The model has never seen a multi-line edit.

## 2. Observations indent file contents by two spaces (interface)

lilguy prints command output indented by two spaces. The model copies that whitespace into literals:

- `jobs.yaml` was appended with 4-space items instead of 2, because the model copied `    - name: rotate` as it was displayed.
- Several edits used `old: " [prod]"` and `old: "  order B-2"`. Those strings, with the leading spaces, do not occur in the file.

Whitespace-exact work, such as YAML, Python or matching indentation, needs the file's own bytes.

## 3. The refusal does not say what went wrong (interface)

`Expected UTF-8 text and exactly one literal match` reads the same whether the text is missing or occurs twice. After it, the model repeated the identical call in 4 of 5 cases.

## Newline arithmetic on appends (data)

- **No final newline:** the model appended to `guests.txt`, which has no final newline, without adding one first. The result was `TomasOmar`. It then noticed the problem, but its fix used a literal `\n` again.
- **Signature block:** it wrote `\n\n` where one blank line was asked for.

All 130 appends in the training data are single lines to files that end in a newline.

## Proposal

**Interface v4:** two changes to what the model sees, both version-gated so v1–v3 stay reproducible.
- Print command output unindented between clear delimiters, so copied text is byte-exact.
- Make `fs.edit` refusals specific: `old text not found`, or `old text occurs 2 times (lines 2 and 5); include a neighbouring line using old <<< … >>>`.

**Corpus r10:** four new families.
- Edits that use `old <<<` / `new <<<` blocks to target one of several identical lines.
- Multi-line appends with `printf '%s\n' line1 line2 >> file`.
- Appends to files without a final newline, checking with `tail -c 1` first.
- Whitespace-exact appends to indented formats.

**Check:** first run r8 under v4 with no retraining, on the focus set and the 80-task roster. That separates what the interface alone fixes. Then retrain r10 on v4 at two seeds. Promotion needs a new held-out suite (v2); v1 is spent on the 1.0 model.
