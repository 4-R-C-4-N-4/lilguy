# Public data sources and provenance

Licence status for all six public sources below (declared licence, verified upstream licence,
obligations, per-source verdict) is tracked in [LICENCE-AUDIT.md](./LICENCE-AUDIT.md); do not
treat source labels in this file as settled licence findings.

No commands from these sources have been executed for training. Local history analysis is separate and aggregate-only. Source-card counts below are publisher claims, not completed local verification counts.

## NL2SH-ALFA

- Source: https://huggingface.co/datasets/westenfelder/NL2SH-ALFA
- Card inspected: https://huggingface.co/datasets/westenfelder/NL2SH-ALFA/raw/main/README.md
- Original project linked by card: https://github.com/westenfelder/NL2SH
- Card declares 40,639 unverified training pairs and 600 manually verified test pairs.
- `name="train"` / `name="test"` selects the configuration. Both use `split="train"`; choosing a test split instead is incorrect.
- Raw fields: train `nl`, `bash`; test additionally `bash2`, `difficulty`.
- Card declares MIT. Because the card explicitly identifies upstream tldr-pages content among its sources, upstream attribution/license obligations need a separate provenance audit before SFT redistribution. A dataset-card label alone does not settle all underlying content rights.
- Publisher verification does not replace our P6 sandbox execution-equivalence checks.

## neulab/tldr

- Source: https://huggingface.co/datasets/neulab/tldr
- Card inspected: https://huggingface.co/datasets/neulab/tldr/raw/main/README.md
- Original project linked by card: https://github.com/shuyanzhou/docprompting
- Card declares train 6,414 / validation 1,845 / test 928 rows.
- Raw fields include `question_id`, `nl`, `cmd`, `oracle_man`, `cmd_name`, `tldr_cmd_name`, `manual_exist`, `matching_info`.
- These are actual dataset splits, not ALFA-style configuration names.
- The mirror card says MIT, but upstream tldr-pages content is CC BY 4.0. Do not propagate the mirror's MIT label as settled content provenance.

## tldr-pages knowledge base

- Source/license: https://raw.githubusercontent.com/tldr-pages/tldr/main/LICENSE.md
- Page content is Creative Commons Attribution 4.0 International; the scripts directory is MIT. Preserve attribution to the tldr-pages team and contributors.
- Freeze a specific upstream commit before building new eval tasks (D6). That snapshot has not yet been frozen; no neutral-KB or de-leaked-eval claim is made.

## Additional sources (coverage and use-case analysis only)

Fetched with `python -m lilguy.data.fetch --source <name>` from raw files using the installed json/parquet builders; no remote loader script is run. Records stay `license: unverified`; none may become training data until provenance is checked.

- `cli-explained` → b-mc2/cli-commands-explained (Hub tag CC0-1.0). Built from commandlinefu.com and github.com/cheat/cheatsheets; the upstream terms for both still need checking before any training use. 16,090 rows with a command.
- `nl2bash-custom` → AnishJoshi/nl2bash-custom (no licence declared on the Hub; derives from NL2Bash and Magnum-NLC2CMD; see audit for the data/code licence distinction). Ships a `dataset.py` loader that is **never** executed. 24,569 rows.
- `bash6k` → emirkaanozdemr/bash_command_data_6K (Apache-2.0 declared; creation method undisclosed). 6,153 rows.
- Considered, not fetched: SALT-NLP/SWE-chat (ODC-BY, gated: the account owner must accept the terms), scraped public `.bash_history` files (credentials; not collected), SEA/Greenberg (no arguments), KYPO training commands, The Stack shell subset.

## Local shell history (D9)

`lilguy/data/history.py` reads bash/zsh/atuin history for coverage only. Its output is an aggregate in which unknown names, unlisted flags and every argument are suppressed. It can only be written under `reports/private/` (gitignored, mode 0600). History is never training data or a fixture, and is never committed.

## Current gate

P4 tooling is being corrected against these real schemas. Cache records remain `license: unverified` until provenance is attached explicitly. No SFT data, final toolset, or model-family decision follows automatically from a successful download.
