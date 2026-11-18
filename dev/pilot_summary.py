"""Print a side-by-side summary of SFT pilot reports (development helper)."""
import json
import sys
from pathlib import Path


def main(runs):
    for run in runs:
        report = json.loads((Path(run) / "report.json").read_text())
        for name in ("base", "tuned", "tuned_train"):
            s = report["eval"][name]["score"]
            b = s["by_gold_action"]
            print(f"{Path(run).name} {name:11s} exact {s['exact']:3d}/{s['n']:<3d} invalid {s['invalid']}"
                  f"  edit {b['fs.edit']['exact']}/{b['fs.edit']['n']}"
                  f"  ask {b['ask']['exact']}/{b['ask']['n']} (action {b['ask']['action_match']})"
                  f"  done {b['done']['exact']}/{b['done']['n']}")
        t = report["train"]
        print(f"   train {t['seconds']}s, {t['tokens_per_second']} tok/s, peak "
              f"{t['peak_memory_bytes'] / 2**30:.2f} GiB, adapter {t['adapter_bytes'] / 2**20:.1f} MiB, "
              f"trainable {t['trainable_parameters'] / 1e6:.1f}M, decision_weight "
              f"{report['config'].get('decision_weight', 1.0)}")


if __name__ == "__main__":
    main(sys.argv[1:])
