"""lilguy P0 capability probe.

Checks whether the host can run lilguy's sandbox (P1): unprivileged user
namespaces, overlayfs inside a userns, stacked overlays with whiteouts,
bubblewrap >= 0.11 non-setuid with working ``--overlay``, Landlock, cgroup
delegation (best-effort) and Python runnable inside the sandbox.

Usage::

    python3 -m lilguy.probe [--json]

Exits non-zero iff any *required* check fails.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Literal

Status = Literal["pass", "warn", "fail"]
_VALID_STATUSES = {"pass", "warn", "fail"}

# Syscall numbers for landlock_create_ruleset, per architecture. Landlock is
# Linux-specific and syscall numbers are architecture-dependent; an unknown
# architecture must not guess a number and call it.
_LANDLOCK_SYSCALL_NRS: dict[str, int] = {
    "x86_64": 444,
    "aarch64": 444,
    "arm64": 444,
}

_DEFAULT_TIMEOUT_S = 15


@dataclass(frozen=True)
class CheckResult:
    name: str
    required: bool
    status: Status
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"invalid status {self.status!r}; must be one of {_VALID_STATUSES}")


def _current_arch() -> str:
    return platform.machine()


def _landlock_abi_raw(nr: int) -> int:
    """Raw landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)."""
    libc = ctypes.CDLL(None, use_errno=True)
    return libc.syscall(nr, None, 0, 1)


def _run(argv: list[str], *, timeout: int = _DEFAULT_TIMEOUT_S, input: str | None = None):
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input,
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_kernel_version() -> CheckResult:
    release = os.uname().release
    core = release.split("-")[0]
    try:
        parts = [int(p) for p in core.split(".")[:3]]
        while len(parts) < 2:
            parts.append(0)
        major, minor = parts[0], parts[1]
    except ValueError:
        return CheckResult("kernel_version", True, "fail", f"unparseable release {release!r}")

    ok = (major, minor) >= (5, 11)
    status: Status = "pass" if ok else "fail"
    detail = f"release={release} (need >= 5.11)"
    return CheckResult("kernel_version", True, status, detail)


def check_unprivileged_userns() -> CheckResult:
    try:
        r = _run(["unshare", "-Ur", "true"])
    except FileNotFoundError:
        return CheckResult("unprivileged_userns", True, "fail", "unshare binary not found")
    except subprocess.TimeoutExpired:
        return CheckResult("unprivileged_userns", True, "fail", "unshare -Ur true timed out")
    if r.returncode == 0:
        return CheckResult("unprivileged_userns", True, "pass", "unshare -Ur true succeeded")
    return CheckResult(
        "unprivileged_userns", True, "fail",
        f"unshare -Ur true exit={r.returncode} stderr={r.stderr.strip()[:200]}",
    )


_UNSHARE_OVERLAY_SCRIPT = r"""
set -e
BASE="$1"
mkdir -p "$BASE"/lower "$BASE"/upper "$BASE"/work "$BASE"/merged
echo base_content > "$BASE"/lower/f.txt
mount -t overlay overlay -o userxattr,lowerdir="$BASE"/lower,upperdir="$BASE"/upper,workdir="$BASE"/work "$BASE"/merged
rm -f "$BASE"/merged/f.txt
python3 - "$BASE" <<'PY'
import os, stat, sys
base = sys.argv[1]
whiteout = os.path.join(base, "upper", "f.txt")
st = os.lstat(whiteout)
ok = stat.S_ISCHR(st.st_mode) and st.st_rdev == 0
print("WHITEOUT_OK" if ok else "WHITEOUT_FAIL")
PY
umount "$BASE"/merged
"""


def check_overlay_userns() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="lilguy-probe-ovl-") as tmp:
        try:
            r = _run(
                ["unshare", "-Urm", "bash", "-c", _UNSHARE_OVERLAY_SCRIPT, "bash", tmp],
                timeout=30,
            )
        except FileNotFoundError:
            return CheckResult("overlay_userns", True, "fail", "unshare/bash not found")
        except subprocess.TimeoutExpired:
            return CheckResult("overlay_userns", True, "fail", "overlay-in-userns probe timed out")

        if r.returncode == 0 and "WHITEOUT_OK" in r.stdout.splitlines():
            return CheckResult("overlay_userns", True, "pass", "userxattr overlay + 0:0 whiteout confirmed")
        return CheckResult(
            "overlay_userns", True, "fail",
            f"exit={r.returncode} stdout={r.stdout.strip()[:200]} stderr={r.stderr.strip()[:200]}",
        )


_STACKED_OVERLAY_SCRIPT = r"""
set -e
BASE="$1"
mkdir -p "$BASE"/base "$BASE"/up1 "$BASE"/work1 "$BASE"/merged1
mkdir -p "$BASE"/up2 "$BASE"/work2 "$BASE"/merged2
echo base_content > "$BASE"/base/shared.txt

# Step 1: mount base as lower, delete the file in up1.
mount -t overlay overlay -o userxattr,lowerdir="$BASE"/base,upperdir="$BASE"/up1,workdir="$BASE"/work1 "$BASE"/merged1
rm -f "$BASE"/merged1/shared.txt
umount "$BASE"/merged1

# Step 2: stack up1 as a lower layer (on top of base), with a fresh upper.
mount -t overlay overlay -o userxattr,lowerdir="$BASE"/up1:"$BASE"/base,upperdir="$BASE"/up2,workdir="$BASE"/work2 "$BASE"/merged2
if [ -e "$BASE"/merged2/shared.txt ]; then
  echo STACKED_FAIL
else
  echo STACKED_OK
fi
umount "$BASE"/merged2
"""


def check_stacked_overlay() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="lilguy-probe-stack-") as tmp:
        try:
            r = _run(
                ["unshare", "-Urm", "bash", "-c", _STACKED_OVERLAY_SCRIPT, "bash", tmp],
                timeout=30,
            )
        except FileNotFoundError:
            return CheckResult("stacked_overlay", True, "fail", "unshare/bash not found")
        except subprocess.TimeoutExpired:
            return CheckResult("stacked_overlay", True, "fail", "stacked overlay probe timed out")

        if r.returncode == 0 and "STACKED_OK" in r.stdout.splitlines():
            return CheckResult("stacked_overlay", True, "pass", "previous upper as lower hides base file")
        return CheckResult(
            "stacked_overlay", True, "fail",
            f"exit={r.returncode} stdout={r.stdout.strip()[:200]} stderr={r.stderr.strip()[:200]}",
        )


def _bwrap_path() -> str:
    return os.environ.get("LILGUY_BWRAP") or shutil.which("bwrap") or "bwrap"


def check_bwrap_version() -> CheckResult:
    bwrap = _bwrap_path()
    try:
        r = _run([bwrap, "--version"])
    except FileNotFoundError:
        return CheckResult("bwrap_version", True, "fail", f"bwrap not found ({bwrap})")
    if r.returncode != 0:
        return CheckResult("bwrap_version", True, "fail", f"bwrap --version exit={r.returncode}")

    out = (r.stdout or "") + (r.stderr or "")
    version = None
    for tok in out.split():
        parts = tok.split(".")
        if len(parts) >= 2 and all(p.isdigit() for p in parts[:3] if p):
            version = tok
            break
    if version is None:
        return CheckResult("bwrap_version", True, "fail", f"could not parse version from {out!r}")

    try:
        vparts = [int(p) for p in version.split(".")[:3]]
    except ValueError:
        return CheckResult("bwrap_version", True, "fail", f"unparseable version {version!r}")
    while len(vparts) < 2:
        vparts.append(0)

    try:
        st = os.stat(bwrap if os.path.isabs(bwrap) else (shutil.which(bwrap) or bwrap))
        is_setuid = bool(st.st_mode & stat.S_ISUID)
    except OSError as exc:
        return CheckResult("bwrap_version", True, "fail", f"cannot inspect bwrap executable: {exc}")

    if is_setuid:
        return CheckResult("bwrap_version", True, "fail", f"bwrap {version} is setuid; need non-setuid >=0.11")

    if (vparts[0], vparts[1]) < (0, 11):
        return CheckResult("bwrap_version", True, "fail", f"bwrap {version} < 0.11 (needs --overlay support)")

    return CheckResult("bwrap_version", True, "pass", f"bwrap {version}, non-setuid")


def check_bwrap_overlay() -> CheckResult:
    bwrap = _bwrap_path()
    with tempfile.TemporaryDirectory(prefix="lilguy-probe-bwrap-") as tmp:
        src = os.path.join(tmp, "src")
        upper = os.path.join(tmp, "upper")
        work = os.path.join(tmp, "work")
        dest = os.path.join(tmp, "dest")
        for d in (src, upper, work, dest):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(src, "f.txt"), "w") as f:
            f.write("hi")

        argv = [
            bwrap,
            "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
            "--die-with-parent", "--new-session",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind-try", "/bin", "/bin",
            "--ro-bind-try", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--overlay-src", src,
            "--overlay", upper, work, dest,
            "/usr/bin/true" if os.path.exists("/usr/bin/true") else "true",
        ]
        try:
            r = _run(argv, timeout=20)
        except FileNotFoundError:
            return CheckResult("bwrap_overlay", True, "fail", f"bwrap not found ({bwrap})")
        except subprocess.TimeoutExpired:
            return CheckResult("bwrap_overlay", True, "fail", "bwrap overlay probe timed out")

        if r.returncode == 0:
            return CheckResult("bwrap_overlay", True, "pass", "bwrap --overlay ran successfully")
        return CheckResult(
            "bwrap_overlay", True, "fail",
            f"exit={r.returncode} stderr={r.stderr.strip()[:300]}",
        )


def check_python_in_sandbox() -> CheckResult:
    bwrap = _bwrap_path()
    # Must be a python3 that actually lives under a path bound into the
    # sandbox (/usr). shutil.which() can resolve to an interpreter installed
    # outside /usr (e.g. a user-local toolchain), which would be invisible
    # inside the sandbox and produce a false failure.
    python = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else (shutil.which("python3") or "python3")
    argv = [
        bwrap,
        "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts",
        "--die-with-parent", "--new-session",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/etc", "/etc",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        python, "-c", "print('lilguy-probe-ok')",
    ]
    try:
        r = _run(argv, timeout=20)
    except FileNotFoundError:
        return CheckResult("python_in_sandbox", True, "fail", f"bwrap or {python} not found")
    except subprocess.TimeoutExpired:
        return CheckResult("python_in_sandbox", True, "fail", "python-in-sandbox probe timed out")

    if r.returncode == 0 and "lilguy-probe-ok" in r.stdout:
        return CheckResult("python_in_sandbox", True, "pass", f"{python} runs inside bwrap sandbox")
    return CheckResult(
        "python_in_sandbox", True, "fail",
        f"exit={r.returncode} stdout={r.stdout.strip()[:200]} stderr={r.stderr.strip()[:200]}",
    )


def check_landlock() -> CheckResult:
    arch = _current_arch()
    nr = _LANDLOCK_SYSCALL_NRS.get(arch)
    if nr is None:
        return CheckResult(
            "landlock_abi", True, "fail",
            f"unknown landlock syscall number for arch {arch!r}; skipping raw syscall",
        )

    try:
        abi = _landlock_abi_raw(nr)
    except Exception as exc:  # noqa: BLE001 - defensive: raw syscall via ctypes
        return CheckResult("landlock_abi", True, "fail", f"landlock syscall raised {exc!r}")

    if abi < 1:
        return CheckResult("landlock_abi", True, "fail", f"Landlock unavailable (abi={abi})")
    if abi < 3:
        return CheckResult("landlock_abi", True, "warn", f"Landlock ABI {abi} < 3: no truncate control or TCP rules")
    if abi < 4:
        return CheckResult("landlock_abi", True, "warn", f"Landlock ABI {abi} < 4: no TCP rules")
    return CheckResult("landlock_abi", True, "pass", f"Landlock ABI {abi}")


def check_cgroup_delegation() -> CheckResult:
    try:
        r = _run(
            ["systemd-run", "--user", "--scope", "-p", "MemoryMax=64M", "true"],
            timeout=20,
        )
    except FileNotFoundError:
        return CheckResult("cgroup_delegation", False, "warn", "systemd-run not found; falling back to rlimits")
    except subprocess.TimeoutExpired:
        return CheckResult("cgroup_delegation", False, "warn", "systemd-run probe timed out; falling back to rlimits")

    if r.returncode == 0:
        return CheckResult("cgroup_delegation", False, "pass", "systemd-run --user --scope cgroup limits work")
    return CheckResult(
        "cgroup_delegation", False, "warn",
        f"systemd-run cgroup delegation unavailable (exit={r.returncode}); falling back to rlimits",
    )


_ALL_CHECKS = (
    check_kernel_version,
    check_unprivileged_userns,
    check_overlay_userns,
    check_stacked_overlay,
    check_bwrap_version,
    check_bwrap_overlay,
    check_python_in_sandbox,
    check_landlock,
    check_cgroup_delegation,
)


def run_probe() -> list[CheckResult]:
    """Run every capability check and return the results in a stable order."""
    results: list[CheckResult] = []
    for check in _ALL_CHECKS:
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - a crashing check is a fail, not a crash
            results.append(CheckResult(check.__name__, True, "fail", f"check raised {exc!r}"))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_table(results: list[CheckResult]) -> None:
    name_w = max((len(r.name) for r in results), default=4)
    for r in results:
        req = "required" if r.required else "optional"
        print(f"{r.name:<{name_w}}  {r.status:<4}  {req:<8}  {r.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable check results")
    args = parser.parse_args(argv)

    results = run_probe()

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        _print_table(results)

    required_failures = [r for r in results if r.required and r.status == "fail"]
    return 1 if required_failures else 0


if __name__ == "__main__":
    sys.exit(main())
