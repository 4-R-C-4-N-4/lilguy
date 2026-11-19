"""Explicit, bounded dataset fetch for the P4 ingest slice.

Supported sources (HuggingFace Hub, lazily imported):
    nl2sh-alfa -> westenfelder/NL2SH-ALFA
        load_dataset(repo, name=config, split="train")
        config selects which NL2SH-ALFA config ("train" or "test"); the
        config's own split is always literally "train". Raw columns: nl,
        bash, bash2 (alternative gold command, test config only), difficulty.
    tldr       -> neulab/tldr
        load_dataset(repo, split=config)
        config selects the dataset's own split name directly (it has
        train/test/validation). Raw columns: question_id, nl, cmd,
        oracle_man, ...

source="history" is explicitly refused: no personal shell history is ever
read or ingested by this module. No shell command from any dataset row is
ever executed — rows are treated as opaque strings for parsing/coverage only.

Normalized record shape:
    id, source, orig_split, verified, nl, cmd, alt_cmds, difficulty, license

license is always "unverified" here (pending explicit upstream lookup by the
parent); verified is only set true when the source's own test-split ground
truth marks a row as validated, and this module makes no SFT training claim.

Caching: JSONL is an accepted first-slice cache format (no parquet/pyarrow
dependency required for this slice); this is a documented gap, not parity
with a prospective parquet-backed cache.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Iterable, Iterator

_SOURCES = {
    "nl2sh-alfa": "westenfelder/NL2SH-ALFA",
    "tldr": "neulab/tldr",
    # Coverage / use-case analysis only until licences are audited (docs/data/DATA-SOURCES.md).
    "cli-explained": "b-mc2/cli-commands-explained",   # commandlinefu + cheat/cheatsheets
    "nl2bash-custom": "AnishJoshi/nl2bash-custom",      # ships a loader script: never run it
    "bash6k": "emirkaanozdemr/bash_command_data_6K",
}
_CONFIGS = {"train", "test", "validation"}
_SINGLE_SPLIT = {"cli-explained", "bash6k"}
# Raw file per (source, config), read with the installed json/parquet builders.
_RAW_FILES = {
    ("cli-explained", "train"): ("json", "cli_commands_explained.json"),
    ("nl2bash-custom", "train"): ("json", "data/train.json"),
    ("nl2bash-custom", "validation"): ("json", "data/dev.json"),
    ("nl2bash-custom", "test"): ("json", "data/test.json"),
    ("bash6k", "train"): ("parquet", "data/train-00000-of-00001.parquet"),
}
# Scraped sources contain rows that are not commands (keyboard shortcuts, empty code): skip them.
_SKIP_EMPTY = {"cli-explained", "nl2bash-custom", "bash6k"}

# Raw command field per source: nl2sh-alfa calls it "bash", tldr calls it
# "cmd". Normalizing these onto the single output field "cmd" is the whole
# point of fetch.py -- treating them as identical during load would silently
# break tldr ingestion (there is no "bash" column there).
_CMD_FIELD = {
    "nl2sh-alfa": "bash",
    "tldr": "cmd",
    "cli-explained": "code",
    "nl2bash-custom": "bash_code",
    "bash6k": "completion",
}
# NL field(s) in order of preference (first non-empty wins).
_NL_FIELDS = {
    "nl2sh-alfa": ("nl",),
    "tldr": ("nl",),
    "cli-explained": ("title", "description"),
    "nl2bash-custom": ("nl_command",),
    "bash6k": ("prompt",),
}
_ALT_CMD_FIELD = {
    "nl2sh-alfa": "bash2",
    "tldr": None,
    "cli-explained": None,
    "nl2bash-custom": None,
    "bash6k": None,
}
_REQUIRED_RAW_COLUMNS = {
    "nl2sh-alfa": {"nl", "bash"},
    "tldr": {"nl", "cmd"},
    "cli-explained": {"code"},
    "nl2bash-custom": {"bash_code", "nl_command"},
    "bash6k": {"prompt", "completion"},
}


def _load_raw_rows(source: str, config: str) -> Iterable[dict]:
    """Lazily import `datasets` and return a lazy iterable of raw rows.

    Returns an iterable (not necessarily a list) so callers can bound memory
    with itertools.islice instead of materializing the entire split. Isolated
    so tests can monkeypatch it without requiring the optional
    `datasets`/`pyarrow` dependency to be installed.
    """
    try:
        import datasets  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "the 'datasets' package is required for lilguy.data.fetch; "
            "install the optional extra with `pip install lilguy[data]`"
        ) from exc

    hub_name = _SOURCES[source]
    if source == "nl2sh-alfa":
        # config selects the NL2SH-ALFA *config* (train/test); its own split
        # is always literally "train".
        return datasets.load_dataset(hub_name, name=config, split="train")
    if source == "tldr":
        # The Hub repository has an obsolete remote Python loader. Never run
        # it: use the installed, trusted JSON reader on verified raw data URLs.
        names = {"train": "tldr-train.jsonl", "test": "tldr-test.jsonl", "validation": "tldr-dev.jsonl"}
        url = f"https://huggingface.co/datasets/neulab/tldr/resolve/main/{names[config]}"
        return datasets.load_dataset("json", data_files={config: url}, split=config)
    if (source, config) in _RAW_FILES:
        builder, name = _RAW_FILES[(source, config)]
        url = f"https://huggingface.co/datasets/{hub_name}/resolve/main/{name}"
        return datasets.load_dataset(builder, data_files={config: url}, split=config)
    raise ValueError(f"unknown source {source!r}; no loader strategy defined")


def _non_empty_str(value, field: str, idx: int, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"row {idx} from source={source!r} has an empty/invalid '{field}' field")
    return value


def _normalize_row(idx: int, source: str, config: str, row: dict) -> dict | None:
    required = _REQUIRED_RAW_COLUMNS[source]
    missing = required - set(row.keys())
    if missing:
        raise ValueError(f"row {idx} from source={source!r} missing required columns: {sorted(missing)}")

    cmd_field = _CMD_FIELD[source]
    alt_field = _ALT_CMD_FIELD[source]

    if source in _SKIP_EMPTY:
        raw_cmd = row.get(cmd_field)
        nl_value = next((row[f] for f in _NL_FIELDS[source]
                         if isinstance(row.get(f), str) and row[f].strip()), None)
        if not isinstance(raw_cmd, str) or not raw_cmd.strip() or nl_value is None:
            return None
        nl, cmd = nl_value.strip(), raw_cmd.strip()
    else:
        nl = _non_empty_str(row["nl"], "nl", idx, source)
        cmd = _non_empty_str(row[cmd_field], cmd_field, idx, source)

    alt_cmds: list[str] = []
    if alt_field:
        alt_value = row.get(alt_field)
        if isinstance(alt_value, str) and alt_value.strip():
            alt_cmds.append(alt_value)
        elif isinstance(alt_value, (list, tuple)):
            alt_cmds.extend(v for v in alt_value if isinstance(v, str) and v.strip())

    orig_split = row.get("split", config)
    verified = bool(row.get("verified", False)) if config == "test" else False

    record = {
        "id": f"{source}:{config}:{idx}",
        "source": source,
        "orig_split": orig_split,
        "verified": verified,
        "nl": nl,
        "cmd": cmd,
        "alt_cmds": alt_cmds,
        "difficulty": row.get("difficulty"),
        "license": "unverified",
    }
    if source == "tldr" and "oracle_man" in row:
        record["oracle_man"] = row.get("oracle_man")
    return record


def fetch_records(*, source: str, config: str, limit: int) -> list[dict]:
    if source == "history":
        raise ValueError("source='history' is refused: no personal history ingestion is permitted")
    if source not in _SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {sorted(_SOURCES)}")
    if config not in _CONFIGS:
        raise ValueError(f"unknown config {config!r}; expected one of {sorted(_CONFIGS)}")
    if source == "nl2sh-alfa" and config == "validation":
        raise ValueError("NL2SH-ALFA has only train/test configurations")
    if source in _SINGLE_SPLIT and config != "train":
        raise ValueError(f"{source} has only a train split")
    if limit <= 0:
        raise ValueError("limit must be a positive integer")

    raw_rows: Iterator[dict] = iter(_load_raw_rows(source, config))
    records = []
    for idx, row in enumerate(itertools.islice(raw_rows, limit)):
        record = _normalize_row(idx, source, config, row)
        if record is not None:
            records.append(record)
    return records


def write_jsonl(records: list[dict], out_path: Path | str) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lilguy.data.fetch",
        description="Explicit, bounded fetch of nl2sh-alfa/tldr command datasets to a JSONL cache.",
    )
    parser.add_argument("--source", required=True, choices=sorted(_SOURCES) + ["history"])
    parser.add_argument("--config", required=True, choices=sorted(_CONFIGS))
    parser.add_argument("--limit", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        records = fetch_records(source=args.source, config=args.config, limit=args.limit)
    except (ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    write_jsonl(records, args.out)
    print(f"wrote {len(records)} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
