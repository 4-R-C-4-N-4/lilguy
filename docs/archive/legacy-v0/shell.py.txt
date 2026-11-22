"""Command executor: one bash process per command, with cwd carried between
steps. Environment variables do not persist across steps (by design: the
explicit state lives in the scaffold, not in a hidden shell)."""
from __future__ import annotations

import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

MARK = "__LILGUY_CWD="
MAX_BYTES = 256_000


@dataclass
class Result:
    exit_code: int
    stdout: str
    stderr: str
    cwd: str
    tags: list[str]


def run(cmd: str, cwd: str, root: str, timeout: float = 20.0) -> Result:
    script = (
        f"cd {shlex.quote(cwd)} || exit 97\n"
        f"{cmd}\n"
        f"__rc=$?\nprintf '\\n{MARK}%s\\n' \"$PWD\"\nexit $__rc\n"
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": root,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "PAGER": "cat",
        "GIT_PAGER": "cat",
    }
    tags: list[str] = []
    p = subprocess.Popen(
        ["bash", "--noprofile", "--norc", "-c", script],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, start_new_session=True,
    )
    try:
        out_b, err_b = p.communicate(timeout=timeout)
        code = p.returncode
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out_b, err_b = p.communicate()
        code = 124
        tags.append(f"TIMEOUT({int(timeout)}s)")

    out = out_b[:MAX_BYTES].decode("utf-8", "replace")
    err = err_b[:MAX_BYTES].decode("utf-8", "replace")
    if len(out_b) > MAX_BYTES or len(err_b) > MAX_BYTES:
        tags.append("TRUNCATED")

    new_cwd = cwd
    idx = out.rfind(MARK)
    if idx != -1:
        new_cwd = out[idx + len(MARK):].strip() or cwd
        out = out[:idx].rstrip("\n")
        if out:
            out += "\n"

    rootp = Path(root).resolve()
    try:
        Path(new_cwd).resolve().relative_to(rootp)
    except ValueError:
        tags.append("CWD_OUTSIDE_SANDBOX")
        new_cwd = str(rootp)
    return Result(code, out, err, new_cwd, tags)
