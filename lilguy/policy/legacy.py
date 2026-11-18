"""Safety policy, kept outside the model.

deny    -> never run
confirm -> run only if the confirm callback approves (a human in interactive
           mode, the task's `allow` list in evals)
allow   -> run

This is a guardrail, not a sandbox. For real isolation run the executor inside
a container or VM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DENY: list[tuple[str, str]] = [
    (r"\bsudo\b|\bsu\s", "privilege escalation"),
    (r"\bmkfs\b|\bfdisk\b|\bparted\b", "disk formatting"),
    (r"\bdd\b.*\bof=/dev/", "raw device write"),
    (r">\s*/dev/(sd|nvme|hd)", "raw device write"),
    (r":\(\)\s*\{", "fork bomb"),
    (r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe download to shell"),
    (r"\brm\s+(-\w+\s+)*(/|~|\$HOME|/\*)(\s|$)", "rm on / or home"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "power control"),
    (r"\bchmod\s+(-\w+\s+)*[0-7]*777\s+/(\s|$)", "chmod 777 /"),
]

CONFIRM: list[tuple[str, str]] = [
    (r"(^|[;&|]\s*)rm\b|\bfind\b.*\s-delete\b|\bshred\b", "delete"),
    (r"\bgit\s+(push|reset\s+--hard|clean|checkout\s+--\s)", "git-destructive"),
    (r"\bchmod\s+-R|\bchown\s+-R", "recursive-permissions"),
    (r"\b(curl|wget|scp|rsync|ssh|nc)\b", "network"),
    (r"\b(pip|npm|apt|apt-get|brew|cargo)\s+(install|add)\b", "install"),
    (r"\bkill(all)?\b|\bpkill\b", "process-control"),
]


@dataclass
class Verdict:
    level: str  # allow | confirm | deny
    reason: str = ""


def check(cmd: str) -> Verdict:
    for rx, why in DENY:
        if re.search(rx, cmd):
            return Verdict("deny", why)
    for rx, why in CONFIRM:
        if re.search(rx, cmd):
            return Verdict("confirm", why)
    return Verdict("allow")
