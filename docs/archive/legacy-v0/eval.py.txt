"""Eval harness: each task runs in a fresh temp dir.

  python -m lilguy.eval --backend scripted                 # validate harness + tasks
  python -m lilguy.eval --backend llamacpp --url http://127.0.0.1:8080
  python -m lilguy.eval --backend llamacpp --only mkdir_recover,ask_destructive -v

Writes one JSON line per task (full trajectory included) to --out. Successful
trajectories from a strong model are training data for a small one.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .agent import Agent
from .backends import LlamaCpp, Scripted
from .memory import ConventionStore

DATA = Path(__file__).parent / "data"


def sh(script: str, cwd: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "--noprofile", "--norc", "-c", "set -e\n" + script], cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)


def run_task(task: dict, make_backend, verbose: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"lilguy-{task['id']}-") as root:
        root = str(Path(root).resolve())
        setup = sh(task.get("setup", ""), root)
        if setup.returncode != 0:
            return {"id": task["id"], "pass": False, "error": f"setup failed: {setup.stderr.strip()}"}

        allow = set(task.get("allow", []))
        agent = Agent(
            backend=make_backend(task),
            root=root,
            store=ConventionStore.load(root),
            confirm=lambda cmd, why: why in allow,
            ask=lambda q: None,  # evals have no human: an ask ends the episode
            max_steps=task.get("max_steps", 10),
            log=print if verbose else None,
        )
        if verbose:
            print(f"\n== {task['id']}: {task['goal']}")
        traj = agent.run(task["goal"])

        chk = sh(task["check"], root)
        want_final = task.get("expect_final", "done")
        passed = chk.returncode == 0 and traj.final == want_final
        return {
            "id": task["id"],
            "pass": passed,
            "check_ok": chk.returncode == 0,
            "final": traj.final,
            "want_final": want_final,
            "steps": len(traj.steps),
            "mismatches": traj.mismatches,
            "invalid": traj.invalid_actions,
            "blocked": traj.policy_blocks,
            "seconds": traj.seconds,
            "trajectory": traj.to_dict(),
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["scripted", "llamacpp"], default="scripted")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--model", default=None, help="model name, for servers that need one")
    ap.add_argument("--no-grammar", action="store_true", help="for OpenAI-compatible servers without GBNF")
    ap.add_argument("--tasks", default=str(DATA / "tasks.json"))
    ap.add_argument("--only", default="", help="comma-separated task ids")
    ap.add_argument("--repeat", type=int, default=1, help="runs per task (for temperature > 0)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    tasks = json.loads(Path(a.tasks).read_text())
    if a.only:
        keep = set(a.only.split(","))
        tasks = [t for t in tasks if t["id"] in keep]

    if a.backend == "scripted":
        def make_backend(t):
            return Scripted(t.get("oracle", []))
    else:
        def make_backend(t):
            return LlamaCpp(a.url, use_grammar=not a.no_grammar,
                            temperature=a.temperature, model=a.model)

    results = []
    t0 = time.time()
    with open(a.out, "w") as f:
        for t in tasks:
            for r in range(a.repeat):
                res = run_task(t, make_backend, a.verbose)
                res["run"] = r
                results.append(res)
                f.write(json.dumps(res) + "\n")

    w = max(len(r["id"]) for r in results) + 2
    print(f"\n{'task':<{w}} pass  final      steps  mism  inval  block   sec")
    for r in results:
        if "error" in r:
            print(f"{r['id']:<{w}} ERR   {r['error']}")
            continue
        fin = r["final"] + ("" if r["final"] == r["want_final"] else f"≠{r['want_final']}")
        print(f"{r['id']:<{w}} {'✓' if r['pass'] else '✗':<5} {fin:<10} {r['steps']:>5} {r['mismatches']:>5} "
              f"{r['invalid']:>6} {r['blocked']:>6} {r['seconds']:>5}")
    n = len(results)
    p = sum(r["pass"] for r in results)
    print(f"\n{p}/{n} passed ({100 * p / n:.0f}%)  in {time.time() - t0:.1f}s  -> {a.out}")
    return 0 if p == n else 1


if __name__ == "__main__":
    sys.exit(main())
