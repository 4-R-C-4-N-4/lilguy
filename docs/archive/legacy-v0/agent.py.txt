"""The loop: retrieve -> prompt -> action -> policy -> execute -> digest -> repeat."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Callable

from . import policy, shell
from .actions import InvalidAction, parse_action
from .backends import Backend
from .digest import digest
from .memory import ConventionStore

SYSTEM = """You operate a bash shell to accomplish a GOAL. Reply with exactly one JSON action:
{"action":"run","arg":"<one bash command>","expect":"ok|output|fail"}
{"action":"ask","arg":"<question for the user>","expect":"ok"}
{"action":"done","arg":"<one-line summary>","expect":"ok"}
Rules:
- One command per step. Read the observation before the next step.
- Follow CONVENTIONS over your own guesses.
- If unsure of a flag or path, check first (ls, --help).
- If the goal is ambiguous or would destroy data, ask.
- expect = your prediction: ok (succeeds, no output), output (succeeds, prints), fail.
- When the goal is met, reply done."""

FULL_HISTORY = 4  # most recent steps shown in full; older ones as one-liners


@dataclass
class Step:
    action: dict
    verdict: str = "allow"
    observation: str = ""
    oneline: str = ""
    outcome: str = ""
    mismatch: bool = False
    retrieved: list[str] = field(default_factory=list)


@dataclass
class Trajectory:
    goal: str
    steps: list[Step] = field(default_factory=list)
    final: str = ""          # done | ask | max_steps | invalid
    final_arg: str = ""
    invalid_actions: int = 0
    policy_blocks: int = 0
    seconds: float = 0.0

    @property
    def mismatches(self) -> int:
        return sum(s.mismatch for s in self.steps)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mismatches"] = self.mismatches
        return d


ConfirmFn = Callable[[str, str], bool]   # (cmd, reason) -> approved?
AskFn = Callable[[str], str | None]      # question -> answer, or None to end episode


class Agent:
    def __init__(self, backend: Backend, root: str, store: ConventionStore | None = None,
                 confirm: ConfirmFn | None = None, ask: AskFn | None = None,
                 max_steps: int = 12, cmd_timeout: float = 20.0, log: Callable[[str], None] | None = None):
        self.backend = backend
        self.root = root
        self.store = store or ConventionStore.load(root)
        self.confirm = confirm or (lambda cmd, why: False)
        self.ask = ask or (lambda q: None)
        self.max_steps = max_steps
        self.cmd_timeout = cmd_timeout
        self.log = log or (lambda s: None)

    # ---- prompt -----------------------------------------------------------
    def _query(self, goal: str, traj: Trajectory) -> str:
        q = goal
        if traj.steps:
            last = traj.steps[-1]
            q += " " + last.action.get("arg", "") + " " + " ".join(t for t in last.oneline.split() if t.isupper())
        return q

    def _prompt(self, goal: str, traj: Trajectory, cwd: str, notes: list[str]) -> tuple[str, list[str]]:
        conv = self.store.retrieve(self._query(goal, traj))
        lines = [f"GOAL: {goal}"]
        if conv:
            lines.append("CONVENTIONS:")
            lines += [f"- {e.text}" for e in conv]
        rel = cwd[len(self.root):] or "/"
        lines.append(f"STATE: cwd=.{rel if rel != '/' else ''} step={len(traj.steps) + 1}/{self.max_steps}")
        if traj.steps:
            lines.append("HISTORY:")
            cut = len(traj.steps) - FULL_HISTORY
            for i, s in enumerate(traj.steps):
                a = s.action
                head = f"[{i + 1}] {a['action']}: {a.get('arg', '')}"
                if a["action"] == "run":
                    head += f"  (expect={a.get('expect')})"
                lines.append(head)
                body = s.oneline if i < cut else s.observation
                lines += ["    " + ln for ln in body.splitlines()]
                if s.mismatch:
                    lines.append(f"    NOTE: you expected {a.get('expect')}, got {s.outcome}.")
        lines += notes
        lines.append("Next action (JSON):")
        return "\n".join(lines), [e.text for e in conv]

    # ---- loop -------------------------------------------------------------
    def run(self, goal: str) -> Trajectory:
        t0 = time.time()
        traj = Trajectory(goal)
        cwd = self.root
        notes: list[str] = []
        consecutive_invalid = 0

        while len(traj.steps) < self.max_steps:
            prompt, retrieved = self._prompt(goal, traj, cwd, notes)
            notes = []
            raw = self.backend.complete(SYSTEM, prompt)
            try:
                act = parse_action(raw)
                consecutive_invalid = 0
            except InvalidAction as e:
                traj.invalid_actions += 1
                consecutive_invalid += 1
                self.log(f"  ! invalid action: {e}")
                if consecutive_invalid >= 3:
                    traj.final = "invalid"
                    break
                notes = [f"NOTE: your last reply was not a valid action ({e}). Reply with JSON only."]
                continue

            step = Step(action=vars(act).copy(), retrieved=retrieved)
            self.log(f"  > {act.action}: {act.arg}" + (f"  [expect={act.expect}]" if act.action == "run" else ""))

            if act.action == "done":
                traj.steps.append(step)
                traj.final, traj.final_arg = "done", act.arg
                break

            if act.action == "ask":
                answer = self.ask(act.arg)
                if answer is None:
                    traj.steps.append(step)
                    traj.final, traj.final_arg = "ask", act.arg
                    break
                step.observation = step.oneline = f"USER: {answer}"
                traj.steps.append(step)
                continue

            v = policy.check(act.arg)
            step.verdict = v.level
            if v.level == "deny" or (v.level == "confirm" and not self.confirm(act.arg, v.reason)):
                traj.policy_blocks += 1
                tag = "POLICY_DENIED" if v.level == "deny" else "POLICY_NEEDS_APPROVAL"
                step.observation = step.oneline = f"not run: {tag}({v.reason}). Use a different approach or ask."
                step.outcome = "blocked"
                self.log(f"    {step.observation}")
                traj.steps.append(step)
                continue

            res = shell.run(act.arg, cwd, self.root, timeout=self.cmd_timeout)
            d = digest(res.exit_code, res.stdout, res.stderr, res.tags)
            cwd = res.cwd
            step.observation, step.oneline, step.outcome = d.text, d.oneline, d.outcome
            # 'output' vs 'ok' confusion is mild; only flag success/failure mispredictions
            step.mismatch = (act.expect == "fail") != (d.outcome == "fail")
            self.log("    " + d.oneline)
            traj.steps.append(step)
        else:
            traj.final = "max_steps"

        traj.seconds = round(time.time() - t0, 2)
        return traj
