"""List what a pilot's mistakes were, by kind (development helper)."""
import collections
import json
import sys
from pathlib import Path


def mistakes(run, corpus, split, key, show):
    report = json.loads((Path(run) / "report.json").read_text())
    rows = [json.loads(line)["messages"] for line in (Path(corpus) / f"{split}.jsonl").read_text().splitlines()]
    kinds = collections.Counter()
    for row, predicted in zip(rows, report["eval"][key]["predictions"], strict=True):
        gold = json.loads(row[-1]["content"])
        try:
            guess = json.loads(predicted)
        except ValueError:
            guess = {"action": "INVALID"}
        if guess == gold:
            continue
        if gold["action"] == guess.get("action") == "fs.edit":
            wrong = [k for k in ("path", "old", "new") if gold["arguments"][k] != guess["arguments"].get(k)]
            kind = "edit with wrong " + ",".join(wrong)
        else:
            kind = f"{gold['action']} -> {guess.get('action')}"
        kinds[kind] += 1
        if show:
            print(f"   {kind:28s} | {row[1]['content'].splitlines()[0]}")
            if kind.startswith("edit with wrong"):
                print(f"   {'':28s}   gold {gold['arguments']}\n   {'':28s}   got  {guess['arguments']}")
    print(f"{split}: {dict(kinds)}")


if __name__ == "__main__":
    run, corpus = sys.argv[1], sys.argv[2]
    mistakes(run, corpus, "validation", "tuned", True)
    mistakes(run, corpus, "train", "tuned_train", False)
