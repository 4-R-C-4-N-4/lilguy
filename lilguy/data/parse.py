"""Static, non-executing shell command parsing via bashlex.

parse_command(cmd) -> dict with keys:
    utility: str | None        - leading simple-command word of the FIRST
                                  command (legacy single-command callers)
    flags: dict                - flags of the FIRST command (legacy)
    utilities: list[str]       - utility of every top-level/piped/chained
                                  command, in order, including repeats
    flags_by_utility: dict     - utility -> merged flag dict across all
                                  commands using that utility
    commands: list[dict]       - one {"utility": str, "flags": dict} per
                                  command node encountered (pipeline stages,
                                  && / ; chains all included)
    pipes: int                 - number of pipe operators in the command
    redirects: list            - redirect operator/target descriptors
    subshells: bool            - whether any "( ... )" subshell is present
    control_flow: bool         - whether if/for/while/case/until constructs
                                  are present
    cmd_substitution: bool     - whether a $(...) / `...` command
                                  substitution is present (dynamic expansion;
                                  not followed into `commands`)
    parse_ok: bool             - False if bashlex could not parse the input
    error: str | None          - message when parse_ok is False
    error_class: str | None    - coarse category when parse_ok is False, or
                                  when an unsupported construct was found

This module never executes the shell string: bashlex only builds an AST and
we walk it read-only.
"""
from __future__ import annotations

import bashlex

# Utilities whose short options we are willing to combine-split (e.g. "-la"
# -> {"l": True, "a": True}). Conservative allowlist only; unknown utilities
# never get their combined short flags split, since some tools (e.g. find)
# use "-name", "-type" style single-dash *long* words rather than flag
# clusters, and others accept negative numeric literals that look like flags.
#
# value_flags: short flag letters that consume the *next* token (or the rest
# of the same cluster) as a value rather than as another boolean flag, e.g.
# grep -e PATTERN, head -n10 / head -n 10.
_UTIL_SPECS = {
    "ls": {"combine_short": True},
    "grep": {"combine_short": True, "value_flags": {"e", "f", "m", "A", "B", "C"}},
    "sort": {"combine_short": True, "value_flags": {"t", "k"}},
    "head": {"combine_short": True, "value_flags": {"n", "c"}},
    "tail": {"combine_short": True, "value_flags": {"n", "c"}},
    "rm": {"combine_short": True},
    "cp": {"combine_short": True},
    "mv": {"combine_short": True},
    "tar": {"combine_short": True},
    "cat": {"combine_short": True},
    "wc": {"combine_short": True},
    "ps": {"combine_short": True},
    "du": {"combine_short": True},
    "df": {"combine_short": True},
    # find/test use single-dash *word* options ("-name", "-maxdepth"), not
    # short-flag clusters; some of those words consume the next token as a
    # value (a glob/path/number) that may itself start with "-".
    "find": {
        "word_flags": True,
        "value_flags": {"name", "path", "maxdepth", "mindepth", "size", "type", "iname"},
    },
    "test": {"word_flags": True},
}

_CONTROL_FLOW_KINDS = {"if", "for", "while", "until", "case", "select"}

# Wrappers whose argument list contains another command. The payload becomes its own entry in
# `commands` (with "via" naming the wrapper); the wrapper keeps a marker flag naming the payload
# utility, so its own flag table is not polluted by the payload's flags.
_FIND_ACTIONS = {"exec", "execdir", "ok", "okdir"}
_XARGS_VALUE = {"I", "n", "P", "d", "L", "s", "E", "a", "l"}
_SUDO_VALUE = {"u", "g", "C", "p", "U", "r", "t", "D", "h", "T", "R"}


def _split_find(words: list[str]):
    """-> (find words without payloads, {action: payload utility}, [(via, payload words)])"""
    outer, markers, payloads = [words[0]], {}, []
    i = 1
    while i < len(words):
        w = words[i]
        if w.startswith("-") and w[1:] in _FIND_ACTIONS:
            j = i + 1
            while j < len(words) and words[j] not in (";", "+"):
                j += 1
            payload = words[i + 1:j]
            markers[w[1:]] = payload[0] if payload else True
            if payload:
                payloads.append((f"find {w}", payload))
            i = j + 1
            continue
        outer.append(w)
        i += 1
    return outer, markers, payloads


def _split_options(words: list[str], value_flags: set[str], default=None):
    """xargs/sudo style: options first, then the payload command. -> (flags, payload words)"""
    flags: dict = {}
    i = 1
    while i < len(words):
        w = words[i]
        if w == "--":
            i += 1
            break
        if w.startswith("--"):
            name, _, value = w[2:].partition("=")
            flags[name] = value or True
            i += 1
            continue
        if not w.startswith("-") or w == "-":
            break
        body = w[1:]
        j = 0
        consumed = False
        while j < len(body):
            ch = body[j]
            if ch in value_flags:
                rest = body[j + 1:]
                if rest:
                    flags[ch] = rest
                elif i + 1 < len(words):
                    flags[ch] = words[i + 1]
                    consumed = True
                else:
                    flags[ch] = True
                break
            flags[ch] = True
            j += 1
        i += 2 if consumed else 1
    payload = words[i:] or ([default] if default else [])
    if payload:
        flags["payload"] = payload[0]
    return flags, payload


def _expand(words: list[str], via: str | None = None) -> list[dict]:
    """One command's words -> [{utility, flags, via}] including nested payload commands."""
    utility = words[0]
    payloads: list[tuple[str, list[str]]] = []
    if utility == "find":
        outer, markers, payloads = _split_find(words)
        flags = {**_flags_from_words(utility, outer), **markers}
    elif utility == "xargs":
        flags, payload = _split_options(words, _XARGS_VALUE, default="echo")
        payloads = [("xargs", payload)] if payload else []
    elif utility == "sudo":
        flags, payload = _split_options(words, _SUDO_VALUE)
        payloads = [("sudo", payload)] if payload else []
    else:
        flags = _flags_from_words(utility, words)
    out = [{"utility": utility, "flags": flags, "via": via}]
    for payload_via, payload in payloads:
        out.extend(_expand(payload, payload_via))
    return out


class ParseError(ValueError):
    """Raised for invalid input to parse_command (not for shell syntax errors)."""


def _empty_result(error: str | None = None, parse_ok: bool = True, error_class: str | None = None) -> dict:
    return {
        "utility": None,
        "flags": {},
        "utilities": [],
        "flags_by_utility": {},
        "commands": [],
        "pipes": 0,
        "redirects": [],
        "subshells": False,
        "control_flow": False,
        "cmd_substitution": False,
        "parse_ok": parse_ok,
        "error": error,
        "error_class": error_class,
    }


def _looks_numeric(token: str) -> bool:
    body = token[1:]
    return bool(body) and body.replace(".", "", 1).isdigit()


def _flags_from_words(utility: str | None, words: list[str]) -> dict:
    """Extract flags for one command's argv (words[0] is the utility)."""
    spec = _UTIL_SPECS.get(utility)
    flags: dict = {}
    args = words[1:]
    n = len(args)
    i = 0
    stop_flags = False

    while i < n:
        w = args[i]

        if stop_flags:
            # Everything after a literal "--" is positional, never a flag.
            i += 1
            continue

        if w == "--":
            stop_flags = True
            i += 1
            continue

        if w.startswith("--"):
            body = w[2:]
            if "=" in body:
                name, _, value = body.partition("=")
                if name:
                    flags[name] = value
            elif body:
                flags[body] = True
            i += 1
            continue

        if w.startswith("-") and len(w) > 1 and not _looks_numeric(w):
            body = w[1:]

            if spec and spec.get("word_flags"):
                flags[body] = True
                if body in spec.get("value_flags", ()):
                    if i + 1 < n:
                        flags[body] = args[i + 1]
                        i += 2
                        continue
                i += 1
                continue

            if spec and spec.get("combine_short"):
                value_flags = spec.get("value_flags", set())
                j = 0
                consumed_next = False
                while j < len(body):
                    ch = body[j]
                    if ch in value_flags:
                        rest = body[j + 1 :]
                        if rest:
                            flags[ch] = rest
                        elif i + 1 < n:
                            flags[ch] = args[i + 1]
                            consumed_next = True
                        else:
                            flags[ch] = True
                        break
                    flags[ch] = True
                    j += 1
                i += 2 if consumed_next else 1
                continue

            # Unknown utility, or known utility with no flag-shape rule:
            # conservative — keep the whole token as one unsplit flag name
            # rather than guessing (and rather than dropping it silently).
            flags[body] = True
            i += 1
            continue

        i += 1

    return flags


def _children(node) -> list:
    kind = getattr(node, "kind", None)
    if kind == "compound":
        return list(getattr(node, "list", []) or [])
    return list(getattr(node, "parts", []) or [])


def _is_subshell_compound(node) -> bool:
    if getattr(node, "kind", None) != "compound":
        return False
    items = getattr(node, "list", []) or []
    reserved = [n for n in items if getattr(n, "kind", None) == "reservedword"]
    return bool(reserved) and reserved[0].word == "("


def _word_has_substitution(word_node) -> bool:
    for part in getattr(word_node, "parts", []) or []:
        if getattr(part, "kind", None) == "commandsubstitution":
            return True
    return False


def _walk(node, out: dict, *, in_substitution: bool) -> None:
    kind = getattr(node, "kind", None)

    if kind == "pipe":
        out["pipes"] += 1
    elif kind == "redirect":
        out["redirects"].append(
            {"type": getattr(node, "type", None), "output": str(getattr(node, "output", ""))}
        )
    elif kind in _CONTROL_FLOW_KINDS:
        out["control_flow"] = True
    elif _is_subshell_compound(node):
        out["subshells"] = True
    elif kind == "command":
        parts = getattr(node, "parts", []) or []
        words = [p.word for p in parts if getattr(p, "kind", None) == "word"]
        for p in parts:
            if getattr(p, "kind", None) == "redirect":
                out["redirects"].append(
                    {"type": getattr(p, "type", None), "output": str(getattr(p, "output", ""))}
                )
            if getattr(p, "kind", None) == "word" and _word_has_substitution(p):
                out["cmd_substitution"] = True
                # Descend into the substitution's own command tree so its
                # pipes/redirects/control-flow are noticed, but never record
                # it in `commands` / utilities — it's a dynamic expansion,
                # not a statically-known command this record runs directly.
                for sub_part in getattr(p, "parts", []) or []:
                    if getattr(sub_part, "kind", None) == "commandsubstitution":
                        sub_cmd = getattr(sub_part, "command", None)
                        if sub_cmd is not None:
                            _walk(sub_cmd, out, in_substitution=True)
        if words and not in_substitution:
            for command in _expand(words):
                out["commands"].append(command)
                out["utilities"].append(command["utility"])
                out["flags_by_utility"].setdefault(command["utility"], {}).update(command["flags"])
                if out["utility"] is None:
                    out["utility"] = command["utility"]
                    out["flags"] = command["flags"]
        return  # command node's word/redirect children already handled

    for child in _children(node):
        _walk(child, out, in_substitution=in_substitution)


def parse_command(cmd: str) -> dict:
    if not isinstance(cmd, str):
        raise ParseError(f"parse_command requires a str, got {type(cmd).__name__}")

    try:
        trees = bashlex.parse(cmd)
    except Exception as exc:  # bashlex raises its own error types on bad syntax
        return _empty_result(error=str(exc), parse_ok=False, error_class="bashlex_syntax_error")

    out = _empty_result()
    for tree in trees:
        _walk(tree, out, in_substitution=False)

    if out["control_flow"]:
        out["error_class"] = out["error_class"] or "control_flow_unsupported"
    elif out["subshells"]:
        out["error_class"] = out["error_class"] or "subshell_unsupported"
    elif out["cmd_substitution"]:
        out["error_class"] = out["error_class"] or "command_substitution_unsupported"

    return out
