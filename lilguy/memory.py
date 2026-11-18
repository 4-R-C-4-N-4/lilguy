"""Convention store + retrieval. Deliberately dumb: keyed token overlap.

Two sources, merged:
  - global knowledge   lilguy/data/conventions.jsonl  (tldr-style command snippets)
  - project conventions <sandbox>/.lilguy/conventions.jsonl  (how *this* project works)

Project entries win ties and get a score boost, because a wrong guess about
a project convention is what a tiny model cannot recover from.

Entry format (one JSON object per line):
  {"keys": ["test", "tests"], "text": "Run tests with `make check`.", "scope": "project"}
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).parent / "data"
_TOK = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "to", "of", "in", "and", "or", "for", "into", "with", "all", "every",
        "each", "this", "that", "it", "its", "is", "are", "be", "under", "on", "one", "per", "just",
        "file", "files", "directory", "dir", "txt", "line"}


def toks(s: str) -> set[str]:
    out = set()
    for t in _TOK.findall(s.lower()):
        if t in STOP:
            continue
        out.add(t)
        if len(t) > 3 and t.endswith("s"):
            out.add(t[:-1])  # crude plural folding: files -> file
    return out


@dataclass
class Entry:
    keys: set[str]
    text: str
    scope: str = "global"


class ConventionStore:
    def __init__(self, entries: list[Entry] | None = None):
        self.entries = entries or []

    @staticmethod
    def _read(path: Path, default_scope: str) -> list[Entry]:
        if not path.exists():
            return []
        out = []
        for ln in path.read_text().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            d = json.loads(ln)
            keys = set()
            for k in d.get("keys", []):
                keys |= toks(k)
            out.append(Entry(keys, d["text"], d.get("scope", default_scope)))
        return out

    @classmethod
    def load(cls, project_dir: str | Path | None = None, global_path: Path | None = None) -> "ConventionStore":
        entries = cls._read(global_path or DATA / "conventions.jsonl", "global")
        if project_dir:
            entries += cls._read(Path(project_dir) / ".lilguy" / "conventions.jsonl", "project")
        return cls(entries)

    def retrieve(self, query: str, k: int = 4) -> list[Entry]:
        q = toks(query)
        scored = []
        for e in self.entries:
            s = 2.0 * len(q & e.keys) + 0.5 * len(q & toks(e.text))
            if e.scope == "project":
                s *= 1.5
            if s > 0:
                scored.append((s, e))
        scored.sort(key=lambda x: (-x[0], x[1].scope != "project"))
        if not scored:
            return []
        # Relative cutoff: tiny models copy whatever is in context, so weak matches are
        # worse than nothing.
        floor = max(2.0, 0.5 * scored[0][0])
        return [e for s, e in scored[:k] if s >= floor]
