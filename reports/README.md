# reports/

Run evidence. Everything here except this file is gitignored and local to the machine that ran it. The current summary is in [docs/STATUS.md](../docs/STATUS.md).

| Folder | Contents |
|---|---|
| `factory/` | Live factory output. Each job writes a new `check-*`, `fast12-*` or `trial-*` directory here. Grouped result sets live in named subfolders, e.g. `baselines-2026-11-19/` (runs, `baselines.tsv`, `report.md`). |
| `coverage/` | Command-coverage analysis of public sources (coverage only, not training data). |
| `benchmarks/` | Sandbox performance and liveness benchmark outputs, JUnit snapshots. |
| `private/` | Owner-only aggregates from local shell history. Never committed; never training data. |
| `archive/pilots/` | Pre-interface-v1 pilot corpora, SFT pilot adapters and logs, and evaluation traces. Historical. |
| `archive/factory-superseded/` | Factory runs whose results were invalidated or superseded: wrong GPU, older graders, killed partial runs. Kept for audit; do not compare against current runs. |

A run is comparable to another only when `identity.json` shows the same `evaluation_sha256` and `device`; `dev.factory compare` and `dev.baseline_report` enforce this.
