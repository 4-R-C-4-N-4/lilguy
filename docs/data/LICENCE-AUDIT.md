# Licence audit — public shell-command sources

Reviewed 2026-11-19 for lilguy fine-tuning, including possible publication of a derived dataset or model. This is an engineering risk assessment, not a legal opinion. “Conditional” describes a possible route to admission, not permission to import a cache as-is. Re-execution proves sandbox effects, not provenance or permission.

| Source | Evidence and judgement | Training admission |
|---|---|---|
| NL2SH-ALFA | The card declares MIT but describes a combined corpus drawn from nl2bash, LinuxCommands, NL2CMD, InterCode-Bash and tldr-pages. Its published fields do not identify upstream origin per row.[1] | **Unresolved for bulk use.** Use a row only if its upstream origin and applicable notices can be verified independently. A row is not cleared merely because it did not match a known restricted source. |
| neulab/tldr | The card labels the mirror MIT and says it was “harvested from the English subset” of tldr.[2] The upstream pages are CC BY 4.0.[3] | **Conditional.** Prefer upstream directly. For mirror rows, trace `nl`/`cmd` to the upstream page and retain the upstream credit; don't ingest manual/cross-reference fields on this basis. Keep the publisher's validation/test splits out of training. |
| tldr-pages | The upstream licence states “This work is licensed under the Creative Commons Attribution 4.0 International License (CC-BY).” MIT applies separately to `scripts/`.[3] | **Conditional; recommended starting source.** Pin the upstream revision and page per example. Retain contributor credit and supplied notices, provide the licence and source link, and indicate modifications when sharing adapted material.[4] |
| b-mc2/cli-commands-explained | The CC0-labelled card identifies Commandlinefu and `cheat/cheatsheets` as upstream, plus AI-generated descriptions for some rows.[5] GitHub's repository licence endpoint returns 404; the claimed cheatsheets README/CC0 statement could not be verified.[6] The reported Commandlinefu republication permission is secondhand and does not establish its scope or contributor rights. | **Unresolved.** Coverage only. No blanket or subset clearance based on the mirror's label; require an upstream grant and traceable rows first. |
| AnishJoshi/nl2bash-custom | The mirror describes reformatting two upstream datasets without declaring its own licence.[7] TellinaTool provides an explicit MIT licence for `data/bash`, independent of the repository code.[8] Magnum has a repository MIT licence, which does not verify the provenance of every mirror row.[9] | **Conditional for verified upstream rows only.** Prefer TellinaTool's original `data/bash` data; preserve MIT copyright and permission notices. Keep mirror rows blocked until matched to covered upstream data. Do not import upstream code. |
| emirkaanozdemr/bash_command_data_6K | The card states “This dataset is shared under the Apache 2.0 License”, but does not identify how the pairs were created or their original sources.[10] | **Unresolved.** Coverage only pending publisher clarification. Duplicate checks alone do not establish licence provenance. |

## Admission rule

Start with a pinned tldr-pages revision; consider the explicitly MIT-licensed TellinaTool `data/bash` release as a second source. Retain upstream revision, file or row locator, licence, and attribution per accepted example. Capture attribution in any derived dataset release and credit the sources in the model card as a project practice; this audit does not decide whether model weights are legally derivative. Leave unresolved cache records `license: unverified`. Licence review does not bypass split checks, command safety review, or independent sandbox-effect verification. No source was admitted and no training episodes were made by this audit.

## Sources

[1] https://huggingface.co/datasets/westenfelder/NL2SH-ALFA/raw/main/README.md
[2] https://huggingface.co/datasets/neulab/tldr/raw/main/README.md
[3] https://raw.githubusercontent.com/tldr-pages/tldr/main/LICENSE.md
[4] https://creativecommons.org/licenses/by/4.0/legalcode.en
[5] https://huggingface.co/datasets/b-mc2/cli-commands-explained/raw/main/README.md
[6] https://api.github.com/repos/cheat/cheatsheets/license
[7] https://huggingface.co/datasets/AnishJoshi/nl2bash-custom/raw/main/README.md
[8] https://raw.githubusercontent.com/TellinaTool/nl2bash/master/data/bash/LICENSE
[9] https://raw.githubusercontent.com/magnumresearchgroup/Magnum-NLC2CMD/master/LICENSE
[10] https://huggingface.co/datasets/emirkaanozdemr/bash_command_data_6K/raw/main/README.md
