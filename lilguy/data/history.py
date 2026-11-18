"""Local shell history for coverage only (guide §8, decision D9).

History never becomes training data, fixtures, or committed reports. What leaves this module is an
aggregate: utility names that are known from public data or installed on this machine, flag names
seen for that utility in public data, wrapper/structure counts and coverage numbers. Arguments,
values and unrecognised names are never emitted (they are where secrets live).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

from .coverage import greedy_curve
from .parse import parse_command

_ZSH = re.compile(r"^: \d+:\d+;")
_BASH_TS = re.compile(r"^#\d+$")
OTHER, UNLISTED = "<other>", "<unlisted>"


def parse_history(text: str) -> list[str]:
    """bash (optionally with #timestamps) or zsh extended history -> commands."""
    lines = text.splitlines()
    if any(_ZSH.match(line) for line in lines[:50]):
        out: list[str] = []
        for line in lines:
            if _ZSH.match(line):
                out.append(line.split(";", 1)[1])
            elif out and out[-1].endswith("\\"):
                out[-1] += "\n" + line
        return [c for c in out if c.strip()]
    return [line for line in lines if line.strip() and not _BASH_TS.match(line)]


def read_atuin(path: Path) -> list[str]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [row[0] for row in con.execute("select command from history order by timestamp")]
    finally:
        con.close()


def default_sources() -> list[Path]:
    home = Path.home()
    candidates = [home / ".bash_history", home / ".zsh_history", home / ".histfile",
                  home / ".local/share/atuin/history.db"]
    if os.environ.get("HISTFILE"):
        candidates.insert(0, Path(os.environ["HISTFILE"]))
    return [p for p in dict.fromkeys(candidates) if p.is_file()]


def load(paths) -> list[str]:
    commands: list[str] = []
    for path in paths:
        path = Path(path)
        if path.suffix == ".db":
            commands += read_atuin(path)
        else:
            commands += parse_history(path.read_text(errors="replace"))
    return commands


def safe_summary(commands: list[str], *, toolset: dict, public_vocab: dict[str, set],
                 is_known_utility=None, rounds: int = 30) -> dict:
    """Aggregate that is safe to show: see module docstring."""
    is_known = is_known_utility or (lambda u: u in public_vocab or shutil.which(u) is not None)
    known_cache: dict[str, bool] = {}

    def name(utility: str) -> str:
        if utility not in known_cache:
            known_cache[utility] = bool(re.fullmatch(r"[A-Za-z0-9._+-]{1,40}", utility)) and is_known(utility)
        return utility if known_cache[utility] else OTHER

    def flag(utility: str, value: str) -> str:
        return value if name(utility) != OTHER and value in public_vocab.get(utility, ()) else UNLISTED

    utilities: Counter = Counter()
    flags: dict[str, Counter] = {}
    wrappers: Counter = Counter()
    structures: Counter = Counter()
    parse_failures = 0
    for command in commands:
        parsed = parse_command(command)
        if not parsed["parse_ok"]:
            parse_failures += 1
            continue
        for key in ("subshells", "control_flow", "cmd_substitution"):
            structures[key] += bool(parsed[key])
        structures["pipelines"] += parsed["pipes"] > 0
        for cmd in parsed["commands"]:
            shown = name(cmd["utility"])
            utilities[shown] += 1
            if cmd.get("via"):
                wrappers[cmd["via"]] += 1
            if shown != OTHER:
                for f in cmd["flags"]:
                    if f != "payload":
                        flags.setdefault(shown, Counter())[flag(cmd["utility"], f)] += 1

    curve = greedy_curve([{"cmd": c} for c in commands], toolset, rounds=rounds)

    def safe_item(item: str) -> str:
        kind, _, rest = item.partition(":")
        if kind == "flag":
            utility, _, value = rest.partition(":")
            return f"flag:{name(utility)}:{flag(utility, value)}"
        return f"{kind}:{name(rest)}"

    steps = [{**s, "added": sorted({safe_item(i) for i in s["added"]})} for s in curve["steps"]]
    return {
        "commands": len(commands),
        "parse_failures": parse_failures,
        "utilities": dict(utilities.most_common()),
        "flags": {u: dict(c.most_common()) for u, c in sorted(flags.items())},
        "wrappers": dict(wrappers),
        "structures": dict(structures),
        "covered": curve["base_covered"],
        "never_coverable": curve["never_coverable"],
        "curve": steps,
    }


def write_private_report(summary: dict, path: Path) -> None:
    """Write only under a reports/private/ directory (gitignored), owner-only."""
    path = Path(path)
    parts = path.resolve().parts
    if not any(a == "reports" and b == "private" for a, b in zip(parts, parts[1:])):
        raise ValueError("history reports may only be written under reports/private/")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(summary, f, indent=2)
