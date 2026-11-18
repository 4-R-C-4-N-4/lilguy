"""Deterministic output pre-digester.

Turns raw (exit, stdout, stderr) into a short, structured observation so a
tiny model reacts to `exit=1 tags=ENOENT(path=build)` instead of a wall of text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import groupby

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# (tag, regex, name of the capture group to surface as tag detail or None)
PATTERNS: list[tuple[str, re.Pattern, str | None]] = [
    ("CMD_NOT_FOUND", re.compile(r"(?:^|: )(?P<cmd>[\w.+-]+): (?:command )?not found", re.M), "cmd"),
    ("ENOENT", re.compile(r"'?(?P<path>[^'\s:]+)'?: No such file or directory"), "path"),
    ("EACCES", re.compile(r"'?(?P<path>[^'\s:]+)'?: Permission denied"), "path"),
    ("EEXIST", re.compile(r"'?(?P<path>[^'\s:]+)'?: File exists"), "path"),
    ("ENOTDIR", re.compile(r"'?(?P<path>[^'\s:]+)'?: Not a directory"), "path"),
    ("EISDIR", re.compile(r"'?(?P<path>[^'\s:]+)'?: Is a directory"), "path"),
    ("USAGE", re.compile(r"(?:invalid|unrecognized|illegal|unknown) option|^usage:|Try '.*--help'", re.M | re.I), None),
    ("SYNTAX", re.compile(r"syntax error"), None),
    ("MAKE_ERR", re.compile(r"make: \*\*\* (?P<msg>.+)"), "msg"),
    ("PY_EXC", re.compile(r"^(?P<exc>\w+(?:Error|Exception)): ", re.M), "exc"),
]

MAX_LINE = 200
STDOUT_HEAD, STDOUT_TAIL, STDOUT_FULL = 12, 12, 30
STDERR_TAIL = 10


@dataclass
class Digest:
    exit_code: int
    outcome: str                     # ok | output | fail  (comparable to Action.expect)
    tags: list[str] = field(default_factory=list)
    text: str = ""                   # full observation for recent history
    oneline: str = ""                # compressed form for older history


def _clean(s: str) -> list[str]:
    lines = [ANSI.sub("", ln).rstrip()[:MAX_LINE] for ln in s.replace("\r", "\n").splitlines()]
    # collapse consecutive duplicates: "x" x 50 -> "x  (x50)"
    out: list[str] = []
    for line, repeats in groupby(lines):
        count = sum(1 for _ in repeats)
        out.append(f"{line}  (x{count})" if count > 1 else line)
    while out and not out[-1]:
        out.pop()
    return out


def _clip(lines: list[str]) -> list[str]:
    if len(lines) <= STDOUT_FULL:
        return lines
    hidden = len(lines) - STDOUT_HEAD - STDOUT_TAIL
    return lines[:STDOUT_HEAD] + [f"... ({hidden} lines hidden) ..."] + lines[-STDOUT_TAIL:]


def tag_errors(stderr: str, stdout: str = "") -> list[str]:
    blob = stderr + "\n" + stdout
    tags: list[str] = []
    for tag, rx, grp in PATTERNS:
        m = None
        for m in rx.finditer(blob):  # keep the last match: usually the root cause
            pass
        if m:
            detail = (m.group(grp) or "").strip()[:60] if grp else ""
            tags.append(f"{tag}({detail})" if detail else tag)
    return tags


def digest(exit_code: int, stdout: str, stderr: str, extra_tags: list[str] | None = None) -> Digest:
    out_lines, err_lines = _clean(stdout), _clean(stderr)
    tags = list(extra_tags or [])
    if exit_code != 0 or err_lines:
        tags += tag_errors(stderr, stdout if exit_code != 0 else "")

    if exit_code != 0:
        outcome = "fail"
    elif out_lines:
        outcome = "output"
    else:
        outcome = "ok"

    head = f"exit={exit_code}" + (f" tags={','.join(tags)}" if tags else "")
    parts = [head]
    if err_lines:
        shown = err_lines[-STDERR_TAIL:]
        parts.append(f"stderr ({len(err_lines)} lines):")
        parts += ["  " + ln for ln in shown]
    if out_lines:
        parts.append(f"stdout ({len(out_lines)} lines):")
        parts += ["  " + ln for ln in _clip(out_lines)]
    if not out_lines and not err_lines:
        parts.append("(no output)")

    first = (err_lines or out_lines or [""])[-1 if err_lines else 0]
    oneline = head + (f" | {first[:80]}" if first else "")
    return Digest(exit_code, outcome, tags, "\n".join(parts), oneline)
