"""Summarise guarded evaluation JSONL files (development helper).

Collapses exact-duplicate (fixture, context, formatting) episodes, which can only arise from
a repeated command-line filter, and reports what each episode did.
"""
import json
import sys
from pathlib import Path


def summarise(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    unique = {}
    for row in rows:
        unique.setdefault((row["fixture"], row["context"], row["formatting"]), row)
    model = rows[0]["config"].get("ollama_version", rows[0]["config"]["backend"]) if rows else "?"
    passed = sum(r["pass"] for r in unique.values())
    print(f"{Path(path).name}: {passed}/{len(unique)} pass ({len(rows)} rows) — {model}")
    for (fixture, context, _), r in unique.items():
        actions = [t.get("action", "INVALID") for t in r["trace"]]
        print(f"   {'PASS' if r['pass'] else 'fail'} {fixture:28s} {context:7s} effects_ok={r['effects_ok']!s:5s} "
              f"end={r['termination']:16s} writes={r['write_attempts']} originals_ok={r['originals_ok']} "
              f"actions={actions}")


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        summarise(argument)
