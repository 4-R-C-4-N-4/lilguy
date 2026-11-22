"""The action space: run | ask | done, plus a predicted outcome."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

ACTIONS = ("run", "ask", "done")
EXPECTS = ("ok", "output", "fail")


@dataclass
class Action:
    action: str
    arg: str = ""
    expect: str = "ok"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


class InvalidAction(ValueError):
    pass


_OBJ = re.compile(r"\{.*\}", re.S)


def parse_action(text: str) -> Action:
    """Tolerant parse: works with grammar-constrained output and with chatty
    models that wrap the JSON in prose or code fences."""
    m = _OBJ.search(text or "")
    if not m:
        raise InvalidAction(f"no JSON object in: {text[:120]!r}")
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise InvalidAction(f"bad JSON: {e}") from e
    act = d.get("action")
    if act not in ACTIONS:
        raise InvalidAction(f"unknown action {act!r}")
    arg = d.get("arg", d.get("cmd", ""))  # accept "cmd" as an alias
    if not isinstance(arg, str):
        raise InvalidAction("arg must be a string")
    if act == "run" and not arg.strip():
        raise InvalidAction("run with empty command")
    exp = d.get("expect", "ok")
    if exp not in EXPECTS:
        exp = "ok"
    return Action(act, arg, exp)
