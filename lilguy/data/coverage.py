"""Coverage reporting over parsed command records against a toolset mapping.

The toolset mapping is the single source of truth owned by the parent
(toolset.yaml, IMPLEMENTATION §7.1 / §8.3): a dict shaped like

    {"tools": {"<tool-name>": {"bash": {"utility": "find",
                                          "flags": ["name", "type"]}}, ...},
     "pipe": {"stages": ["grep", "sort", ...]}}

This module also accepts the flat legacy shape {utility: [flag, ...]} for
test fixtures/back-compat; it is translated internally and pipes are always
allowed under that shape. This module only consumes whatever mapping it is
given and never writes or invents toolset.yaml.

A record is **covered** only if every command in it uses a supported
utility with only supported flags, AND its structure is permitted: pipes
are fine only when every stage utility+flags is itself supported; subshells,
control-flow and command substitution are never covered (IMPLEMENTATION
§8.3); redirects don't block coverage on their own. A pipeline like
`grep foo | rm -rf x` is NOT covered even though `grep` alone is supported,
because `rm` is not -- counting per-flag instead of per-record would wrongly
call that 100% covered.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from lilguy.data.parse import parse_command


def _normalize_toolset(toolset: dict) -> tuple[dict[str, set], bool, set | None]:
    """Return (utility flags, pipe enabled, stage allowlist)."""
    if "tools" in toolset:
        util_flags: dict[str, set] = {}
        for _tool_name, spec in toolset["tools"].items():
            if not isinstance(spec, dict):
                continue
            bash = spec.get("bash")
            if not bash:
                continue
            utility = bash.get("utility")
            if not utility:
                continue
            flags = bash.get("flags", [])
            if isinstance(flags, dict):
                flags = list(flags.keys())
            util_flags.setdefault(utility, set()).update(str(flag).lstrip("-") for flag in flags or [])
        pipe = toolset["tools"].get("pipe", toolset.get("pipe"))
        return util_flags, pipe is not None, set(pipe.get("stages", [])) if pipe is not None else set()

    # Legacy flat shape: {utility: [flags]}. Pipes are allowed as long as
    # every stage's own utility+flags are supported (test fixtures assume
    # no separate pipe gate).
    util_flags = {u: set(f) for u, f in toolset.items()}
    return util_flags, True, None


def _command_supported(cmd: dict, util_flags: dict[str, set]) -> bool:
    utility = cmd["utility"]
    if utility not in util_flags:
        return False
    allowed = util_flags[utility]
    return all(flag in allowed for flag in cmd["flags"])


def coverage(records: list[dict], toolset: dict) -> dict:
    if not isinstance(toolset, dict):
        raise ValueError("coverage() requires a toolset mapping of {utility: [flags]}")
    if not isinstance(records, list):
        raise ValueError("coverage() requires a list of records")

    util_flags, pipe_allowed, pipe_stages = _normalize_toolset(toolset)

    utility_frequency: Counter = Counter()
    flag_frequency: dict = defaultdict(Counter)
    per_source: dict = defaultdict(
        lambda: {
            "utility_frequency": Counter(),
            "flag_frequency": defaultdict(Counter),
            "total": 0,
            "parse_failures": 0,
            "covered": 0,
        }
    )

    total = 0
    parse_failures = 0
    covered_count = 0
    uncovered_count = 0
    uncovered: Counter = Counter()
    unsupported_structures: Counter = Counter()

    for rec in records:
        if "cmd" not in rec:
            raise ValueError("each record requires a 'cmd' field")
        source = rec.get("source", "unknown")
        total += 1
        per_source[source]["total"] += 1

        parsed = parse_command(rec["cmd"])
        if not parsed["parse_ok"]:
            parse_failures += 1
            per_source[source]["parse_failures"] += 1
            continue

        for cmd in parsed["commands"]:
            utility_frequency[cmd["utility"]] += 1
            per_source[source]["utility_frequency"][cmd["utility"]] += 1
            for flag in cmd["flags"]:
                flag_frequency[cmd["utility"]][flag] += 1
                per_source[source]["flag_frequency"][cmd["utility"]][flag] += 1

        structure_ok = not (parsed["subshells"] or parsed["control_flow"] or parsed["cmd_substitution"])
        if not structure_ok:
            if parsed["subshells"]:
                unsupported_structures["subshell"] += 1
            if parsed["control_flow"]:
                unsupported_structures["control_flow"] += 1
            if parsed["cmd_substitution"]:
                unsupported_structures["cmd_substitution"] += 1

        pipeline_ok = parsed["pipes"] == 0 or (pipe_allowed and
            (pipe_stages is None or all(cmd["utility"] in pipe_stages for cmd in parsed["commands"])))
        all_commands_supported = bool(parsed["commands"]) and all(
            _command_supported(cmd, util_flags) for cmd in parsed["commands"]
        )

        record_covered = structure_ok and pipeline_ok and all_commands_supported

        if record_covered:
            covered_count += 1
            per_source[source]["covered"] += 1
        else:
            uncovered_count += 1
            if not parsed["commands"]:
                uncovered[("<none>", None)] += 1
            else:
                for cmd in parsed["commands"]:
                    if not _command_supported(cmd, util_flags):
                        if cmd["utility"] not in util_flags:
                            uncovered[(cmd["utility"], None)] += 1
                        else:
                            allowed = util_flags[cmd["utility"]]
                            for flag in cmd["flags"]:
                                if flag not in allowed:
                                    uncovered[(cmd["utility"], flag)] += 1

    parse_failure_rate = (parse_failures / total) if total else 0.0
    covered_percent = (covered_count / total) if total else 0.0

    top_uncovered = [pair for pair, _ in uncovered.most_common() if pair[1] is not None]

    return {
        "total_records": total,
        "parse_failures": parse_failures,
        "parse_failure_rate": parse_failure_rate,
        "utility_frequency": dict(utility_frequency),
        "flag_frequency": {u: dict(c) for u, c in flag_frequency.items()},
        "unsupported_structures": dict(unsupported_structures),
        "per_source": {
            src: {
                "total": d["total"],
                "parse_failures": d["parse_failures"],
                "covered": d["covered"],
                "utility_frequency": dict(d["utility_frequency"]),
                "flag_frequency": {u: dict(c) for u, c in d["flag_frequency"].items()},
            }
            for src, d in per_source.items()
        },
        "covered_count": covered_count,
        "uncovered_count": uncovered_count,
        "covered_percent": covered_percent,
        "top_uncovered": top_uncovered,
    }


def _missing_items(parsed: dict, util_flags: dict[str, set], pipe_allowed: bool,
                   pipe_stages: set | None) -> frozenset | None:
    """Items a record still needs ("util:U", "flag:U:F", "pipe:U"), or None if never coverable."""
    if (not parsed["parse_ok"] or not parsed["commands"] or parsed["subshells"]
            or parsed["control_flow"] or parsed["cmd_substitution"]):
        return None
    if parsed["pipes"] and not pipe_allowed:
        return None
    items = set()
    for cmd in parsed["commands"]:
        utility = cmd["utility"]
        if utility not in util_flags:
            items.add(f"util:{utility}")
        allowed = util_flags.get(utility, set())
        items.update(f"flag:{utility}:{flag}" for flag in cmd["flags"] if flag not in allowed)
        if parsed["pipes"] and pipe_stages is not None and utility not in pipe_stages:
            items.add(f"pipe:{utility}")
    return frozenset(items)


def greedy_curve(records: list[dict], toolset: dict, *, rounds: int = 60, max_items: int = 6) -> dict:
    """Greedy toolset growth (guide §8.3). Each round adds the set of utilities/flags/pipe stages that
    completes the most records per item added (ties: more records, then fewer items). Candidates are
    the exact sets some uncovered record still needs, up to ``max_items`` items."""
    from itertools import combinations
    util_flags, pipe_allowed, pipe_stages = _normalize_toolset(toolset)
    need: Counter = Counter()
    total = never = base = 0
    for rec in records:
        total += 1
        missing = _missing_items(parse_command(rec["cmd"]), util_flags, pipe_allowed, pipe_stages)
        if missing is None:
            never += 1
        elif not missing:
            base += 1
        else:
            need[missing] += 1

    added: set = set()
    covered = base
    steps = []
    for _ in range(rounds):
        remaining: Counter = Counter()
        for missing, count in need.items():
            remaining[frozenset(missing - added)] += count
        best = None
        for candidate in remaining:
            if not candidate or len(candidate) > max_items:
                continue
            gain = sum(remaining.get(frozenset(sub), 0)
                       for k in range(1, len(candidate) + 1) for sub in combinations(candidate, k))
            key = (gain / len(candidate), gain, -len(candidate), sorted(candidate))
            if best is None or key[:3] > best[0][:3] or (key[:3] == best[0][:3] and key[3] < best[0][3]):
                best = (key, candidate, gain)
        if best is None:
            break
        _, candidate, gain = best
        added |= candidate
        covered += gain
        need = Counter({m: c for m, c in need.items() if not m <= added})
        steps.append({"added": sorted(candidate), "gain": gain, "covered": covered,
                      "covered_percent": covered / total if total else 0.0, "items_total": len(added)})
    too_large = sum(c for m, c in need.items() if len(m - added) > max_items)
    return {"total_records": total, "base_covered": base, "never_coverable": never,
            "too_large_to_add": too_large, "steps": steps}
