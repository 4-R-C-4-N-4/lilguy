"""lilguy interface v1: the one definition of what the model writes and what it sees back.

Everything that talks to the model imports this module: the agent loop, the tool server's
descriptions, the training-data generator, the evaluator, the trainer and the model server. A
model trained on version N is only valid against version N. Any change to the rendered system
prompt, action syntax or observation format must bump INTERFACE_VERSION, regenerate the golden
prompt in tests/unit/ and regenerate every dataset.

Action syntax: one action per model turn, line-oriented, so shell text is never escaped:

    run                      tool fs.edit              ask                done
    <command or script>      path: cfg/app.ini         <one question>     <what changed / answer>
                             old: retry=2
                             new: retry=5

A value of several lines is written `name <<<`, the lines, then a `>>>` line; its value is those
lines each ending in a newline, so `old` and `new` should both be blocks or both single lines.

Only the first line decides the action. Everything after it is that action's text or arguments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import yaml

from .digest import digest

INTERFACE_VERSION = 1
TOOLSET = Path(__file__).resolve().parent.parent / "toolset.yaml"
# Typed tools served in v1. The text tools in toolset.yaml are thin wrappers that `run` already
# covers; whether typed tools earn their place is measured later (plan step 5/7 ablation).
TOOLS_V1 = ("fs.list", "fs.find", "fs.read", "fs.grep", "fs.edit")
KINDS = ("run", "tool", "ask", "done")
POLICIES = ("ok", "pending", "rejected")
MAX_ACTION_CHARS = 16_384
MAX_CHANGES_SHOWN = 20
BLOCK_OPEN, BLOCK_CLOSE = "<<<", ">>>"
_ARG_LINE = re.compile(r"([a-z_]+): ?(.*)")
_BLOCK_LINE = re.compile(r"([a-z_]+) <<<")


class ProtocolError(ValueError):
    """An action or value that interface v1 cannot accept or express."""


@dataclass(frozen=True)
class ArgSpec:
    type: str                      # path | string | int | bool | enum
    required: bool
    default: object = None
    values: tuple = ()
    minimum: int | None = None
    maximum: int | None = None
    min_length: int | None = None
    max_length: int | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, ArgSpec]


@dataclass(frozen=True)
class Action:
    kind: str
    text: str = ""
    tool: str | None = None
    args: dict = field(default_factory=dict)

    @classmethod
    def run(cls, command):
        return cls("run", text=command)

    @classmethod
    def ask(cls, question):
        return cls("ask", text=question)

    @classmethod
    def done(cls, summary):
        return cls("done", text=summary)

    @classmethod
    def call(cls, name, **args):
        return cls("tool", tool=name, args=args)


def load_tools(toolset=TOOLSET, names=TOOLS_V1):
    """The served tools, in interface order, from the trusted toolset.yaml."""
    definitions = yaml.safe_load(Path(toolset).read_text(encoding="utf8"))["tools"]
    tools = {}
    for name in names:
        definition = definitions[name]
        args = {}
        for arg, spec in definition["args"].items():
            args[arg] = ArgSpec(
                type=spec["type"], required="default" not in spec and not spec.get("optional"),
                default=spec.get("default"), values=tuple(spec.get("values", ())),
                minimum=spec.get("min"), maximum=spec.get("max"),
                min_length=spec.get("min_length"), max_length=spec.get("max_length"))
        tools[name] = ToolSpec(name, definition["description"], args)
    return tools


# --- actions ------------------------------------------------------------------------------------

def parse_action(text, tools):
    """Parse one model turn into an Action, or raise ProtocolError with a reason the model can read."""
    if len(text) > MAX_ACTION_CHARS:
        raise ProtocolError(f"action is too long (over {MAX_ACTION_CHARS} characters)")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
    header, body = lines[0].strip(), lines[1:]
    if not header:
        raise ProtocolError("empty action")
    keyword, _, rest = header.partition(" ")
    if keyword in ("run", "ask", "done"):
        content = "\n".join(([rest] if rest.strip() else []) + body).strip("\n").rstrip()
        if not content.strip():
            raise ProtocolError(f"empty {keyword}: write the {_WHAT[keyword]} on the next line")
        return Action(keyword, text=content)
    if keyword == "tool":
        name = rest.strip()
        if not name:
            raise ProtocolError("missing tool name: write `tool <name>`")
        if name not in tools:
            raise ProtocolError(f"unknown tool {name!r}; tools: {', '.join(tools)}")
        return Action("tool", tool=name, args=_parse_args(tools[name], body))
    raise ProtocolError("the first line must be run, tool <name>, ask or done")


_WHAT = {"run": "command", "ask": "question", "done": "summary"}


def _parse_args(spec, lines):
    raw, index = {}, 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip():
            continue
        block = _BLOCK_LINE.fullmatch(line)
        if block:
            key, collected = block.group(1), []
            while index < len(lines) and lines[index] != BLOCK_CLOSE:
                collected.append(lines[index])
                index += 1
            if index == len(lines):
                raise ProtocolError(f"{key}: unterminated {BLOCK_OPEN} block (end it with a {BLOCK_CLOSE} line)")
            index += 1
            value = "".join(item + "\n" for item in collected)
        else:
            match = _ARG_LINE.fullmatch(line)
            if not match:
                raise ProtocolError(f"not an argument line: {line[:60]!r} (use `name: value`)")
            key, value = match.groups()
        if key in raw:
            raise ProtocolError(f"{key}: given twice")
        if key not in spec.args:
            raise ProtocolError(f"{spec.name}: unknown argument {key!r}; arguments: {', '.join(spec.args)}")
        raw[key] = value
    missing = [k for k, a in spec.args.items() if a.required and k not in raw]
    if missing:
        raise ProtocolError(f"{spec.name}: missing argument {', '.join(missing)}")
    # Canonical order (the tool's argument order) so a re-render matches the grammar.
    return {key: _convert(key, arg, raw[key]) for key, arg in spec.args.items() if key in raw}


def _convert(key, arg, value):
    if arg.type == "int":
        if not re.fullmatch(r"-?[0-9]+", value.strip()):
            raise ProtocolError(f"{key}: expected an integer, got {value[:40]!r}")
        number = int(value)
        if arg.minimum is not None and number < arg.minimum:
            raise ProtocolError(f"{key}: must be at least {arg.minimum}")
        if arg.maximum is not None and number > arg.maximum:
            raise ProtocolError(f"{key}: must be at most {arg.maximum}")
        return number
    if arg.type == "bool":
        if value.strip() not in ("true", "false"):
            raise ProtocolError(f"{key}: expected true or false")
        return value.strip() == "true"
    if arg.type == "enum":
        if value.strip() not in arg.values:
            raise ProtocolError(f"{key}: must be one of {', '.join(map(str, arg.values))}")
        return value.strip()
    if arg.type == "path":
        if not value.strip() or "\0" in value or len(value) > 4096:
            raise ProtocolError(f"{key}: empty or invalid path")
        return value.strip()
    if arg.min_length is not None and len(value) < arg.min_length:
        raise ProtocolError(f"{key}: must not be empty")
    if arg.max_length is not None and len(value) > arg.max_length:
        raise ProtocolError(f"{key}: longer than {arg.max_length} characters")
    return value


def render_action(action, tools=None):
    """The canonical text of an action: what training targets and conversation history contain.

    With `tools`, tool arguments are checked and put in the tool's argument order, which is the
    order the grammar accepts. Data generators must pass `tools`.
    """
    if action.kind in ("run", "ask", "done"):
        if not action.text.strip():
            raise ProtocolError(f"empty {action.kind}")
        return f"{action.kind}\n{action.text}"
    if action.kind != "tool":
        raise ProtocolError(f"unknown action kind {action.kind!r}")
    args = action.args
    if tools is not None:
        if action.tool not in tools:
            raise ProtocolError(f"unknown tool {action.tool!r}")
        spec = tools[action.tool]
        unknown = [key for key in args if key not in spec.args]
        if unknown:
            raise ProtocolError(f"{action.tool}: unknown argument {', '.join(unknown)}")
        args = {key: args[key] for key in spec.args if key in args}
    lines = [f"tool {action.tool}"]
    for key, value in args.items():
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        elif "\n" in value:
            if not value.endswith("\n") or BLOCK_CLOSE in value.split("\n"):
                raise ProtocolError(f"{key}: a multi-line value must end with a newline and "
                                    f"contain no {BLOCK_CLOSE} line")
            lines += [f"{key} {BLOCK_OPEN}", value.rstrip("\n") if value != "\n" else "", BLOCK_CLOSE]
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


# --- observations -------------------------------------------------------------------------------

def render_observation(*, exit_code, stdout="", stderr="", tags=(), changes=(), policy="ok", reason=""):
    """What the model sees after a step: digested output, the step's file changes, the policy outcome."""
    if policy not in POLICIES:
        raise ProtocolError(f"policy must be one of {', '.join(POLICIES)}")
    parts = [digest(exit_code, stdout, stderr, list(tags)).text]
    changes = list(changes)
    if changes:
        shown = "; ".join(f"{op} {path}" for op, path in changes[:MAX_CHANGES_SHOWN])
        extra = len(changes) - MAX_CHANGES_SHOWN
        parts.append(f"changes: {shown}" + (f"; and {extra} more" if extra > 0 else ""))
    else:
        parts.append("changes: none")
    parts.append(f"policy: {policy}" + (f" ({reason})" if reason else ""))
    return "\n".join(parts)


def observation_message(text):
    """The user turn that carries an observation back to the model."""
    return f"Observation:\n{text}"


def invalid_action_message(reason):
    return observation_message(f"invalid action: {reason}\nWrite exactly one action: run, tool <name>, ask or done.")


# --- prompt and grammar -------------------------------------------------------------------------

_HEADER = """\
You are lilguy, a careful shell assistant. You work in a sandboxed copy of the user's workspace: \
nothing you do reaches their real files until they approve it. Paths are relative to the workspace.

Reply with exactly one action per turn. Its first line says which action it is.

run, then the shell command on the next line (several lines for a short script). For example:
run
ls -la src

tool <name>, then one argument per line. For example:
tool fs.read
path: notes.md
For a value of several lines, write the argument name and <<<, then the lines, then a line with >>>.

ask, then your question for the user on the next line.

done, then on the next line what you changed, or the answer to the user's question.

After each action you get an observation: the exit code, the output, the files that changed, \
and the policy result (ok; pending: waiting for the user's approval; rejected: not allowed).

Habits:
- Look before you act: list, find or read before you change anything.
- Use a tool below when it fits; otherwise use run.
- Read the observation before saying done. If a step failed, find out why before going on.
- If the policy says pending, stop: say done and summarise what is waiting for approval.
- If the policy says rejected, do not try the same thing again.
- If the request could mean more than one file or target, ask.

Tools:"""


def _describe(arg):
    if arg.type == "enum":
        kind = "|".join(map(str, arg.values))
    else:
        kind = arg.type
    if arg.required:
        return f"{kind}, required"
    if arg.default is not None:
        default = str(arg.default).lower() if isinstance(arg.default, bool) else arg.default
        return f"{kind}, default {default}"
    return f"{kind}, optional"


def system_prompt(tools):
    lines = [_HEADER]
    for spec in tools.values():
        lines.append(f"- {spec.name}: {spec.description}")
        lines.append("    " + "; ".join(f"{k} ({_describe(a)})" for k, a in spec.args.items()))
    return "\n".join(lines) + "\n"


def _rule(*parts):
    return "-".join(re.sub(r"[^a-zA-Z0-9]+", "-", part) for part in parts)


def grammar(tools):
    """GBNF for llama.cpp: only well-formed v1 actions, tool arguments in canonical order."""
    rules = [
        "root ::= run | tool | ask | done",
        'run ::= "run\\n" text',
        'ask ::= "ask\\n" text',
        'done ::= "done\\n" text',
        "text ::= [^\\n]+ (\"\\n\" [^\\n]*)*",
        "line ::= [^\\n]*",
        "nonempty ::= [^\\n]+",
        'block ::= " <<<\\n" ((([^>\\n] [^\\n]*)?) "\\n")* ">>>"',
        'int ::= "-"? [0-9]+',
        'bool ::= "true" | "false"',
        "tool ::= \"tool \" (" + " | ".join(_rule(name) for name in tools) + ")",
    ]
    for name, spec in tools.items():
        body = [f'"{name}"']
        for arg, a in spec.args.items():
            rule = _rule(name, arg)
            body.append(f"{rule}{'' if a.required else '?'}")
            if a.type == "int":
                value = '": " int'
            elif a.type == "bool":
                value = '": " bool'
            elif a.type == "enum":
                value = '": " (' + " | ".join(f'"{v}"' for v in a.values) + ")"
            elif a.type == "path":
                value = '": " nonempty'
            else:
                value = '(": " line | block)'
            rules.append(f'{rule} ::= "\\n{arg}" {value}')
        rules.append(f"{_rule(name)} ::= " + " ".join(body))
    return "\n".join(rules) + "\n"
