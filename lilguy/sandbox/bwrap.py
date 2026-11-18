"""Build bwrap argv for a single sandboxed step.

No execution here -- purely argv construction plus the workspace-root
safety checks that gate it. Keeping this separate from runner.py makes the
mount-order and bind-list logic independently testable without actually
forking bwrap.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from lilguy.sandbox.backend import SessionConfig

# Roots that must never be used as a sandbox workspace: overlaying them
# would either be nonsensical (/) or risk shadowing/exposing live system or
# user state outside the intended workspace tree.
_DANGEROUS_WORKSPACE_ROOTS = frozenset(
    {
        "/", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/proc", "/sys",
        "/dev", "/boot", "/opt", "/var", "/home", "/root", "/tmp", "/run", "/srv",
        "/mnt", "/media",
    }
)

_RO_SYSTEM_BINDS = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
_RO_ETC_FILES = ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ld.so.cache", "/etc/localtime")

_SANDBOX_HOME = "/home/sandbox"


def bwrap_path() -> str:
    return os.environ.get("LILGUY_BWRAP") or shutil.which("bwrap") or "bwrap"


def validate_workspace(workspace: Path, state_dir: Path | None = None) -> Path:
    """Reject dangerous or overlapping workspace roots. Returns the resolved path."""
    if not workspace.is_absolute():
        raise ValueError(f"workspace must be an absolute path, got {workspace}")
    real = Path(os.path.realpath(workspace))
    if str(real) in _DANGEROUS_WORKSPACE_ROOTS:
        raise ValueError(f"refusing to use {real} as a sandbox workspace root")
    if not real.exists() or not real.is_dir():
        raise ValueError(f"workspace {real} does not exist or is not a directory")
    if state_dir is not None:
        real_state = Path(os.path.realpath(state_dir))
        if real == real_state or real_state in (real, *real.parents) or real in (real_state, *real_state.parents):
            raise ValueError("workspace and session state_dir must not overlap")
    return real


def dest_path(workspace: Path, cfg: SessionConfig) -> str:
    """Where the overlayed workspace is mounted inside the sandbox."""
    return "/ws" if cfg.mount_path == "short" else str(workspace)


def build_argv(
    *,
    workspace: Path,
    cfg: SessionConfig,
    lowers: list[Path],
    upper: Path,
    work: Path,
    entry_argv: list[str],
    bwrap: str | None = None,
    network: bool = False,
) -> list[str]:
    """Build the full bwrap command. ``lowers`` must be oldest-first.

    Empirically (bwrap 0.12), multiple --overlay-src entries must list the
    pristine workspace first and progressively newer upper-turned-lower
    layers after it for a later whiteout to mask an earlier layer's file --
    the opposite of raw overlayfs ``lowerdir=`` priority order. Verified
    directly against bwrap in tests/sandbox, never assumed.
    """
    bwrap = bwrap or bwrap_path()
    dest = dest_path(workspace, cfg)

    argv: list[str] = [
        bwrap,
        "--unshare-user", "--unshare-pid", *(() if network else ("--unshare-net",)),
        "--unshare-ipc", "--unshare-uts",
        "--die-with-parent", "--new-session",
        "--clearenv",
        "--setenv", "HOME", _SANDBOX_HOME,
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "LC_ALL", "C.UTF-8",
        "--setenv", "TERM", "dumb",
    ]

    for d in _RO_SYSTEM_BINDS:
        if os.path.exists(d):
            argv += ["--ro-bind-try", d, d]
    # Minimal /etc: a fresh empty dir plus only the handful of read-only
    # files below, never the whole host /etc.
    argv += ["--dir", "/etc"]
    for f in _RO_ETC_FILES:
        if os.path.exists(f):
            argv += ["--ro-bind-try", f, f]

    argv += ["--proc", "/proc"]
    argv += ["--dev", "/dev"]

    # Mount a fresh /tmp before the workspace overlay. If the workspace
    # happens to live under /tmp (as disposable test fixtures do), binding
    # /tmp first and the overlay dest after means the overlay mount point
    # survives on top of (not underneath) the tmpfs.
    argv += ["--tmpfs", "/tmp"]
    argv += ["--dir", _SANDBOX_HOME]

    for src in lowers:
        argv += ["--overlay-src", str(src)]
    argv += ["--overlay", str(upper), str(work), dest]

    # Protected paths stay read-only inside the sandbox no matter what the
    # session policy says, layered back on top of the overlay.
    for rel in cfg.protected:
        _bind_protected(argv, workspace, dest, rel)

    argv += entry_argv
    return argv


def _bind_protected(argv: list[str], workspace: Path, dest: str, rel: str) -> None:
    if "*" in rel:
        # Glob-style protected patterns (e.g. "**/.env") are handled at the
        # runner layer by walking the workspace; build_argv only takes
        # concrete relative paths it's told about.
        return
    host_path = workspace / rel
    if not host_path.exists():
        return
    try:
        host_real = Path(os.path.realpath(host_path))
        ws_real = Path(os.path.realpath(workspace))
        if host_real != ws_real and ws_real not in (host_real, *host_real.parents):
            # A symlink inside the workspace pointed outside of it -- do not
            # bind whatever it resolves to; just skip protecting it. The
            # path is still readable (or not) only via the overlay itself.
            return
    except OSError:
        return
    argv.extend(["--ro-bind-try", str(host_path), f"{dest}/{rel}"])


def find_env_files(workspace: Path) -> list[str]:
    """Relative paths of every ``.env`` file anywhere under workspace.

    Supports the ``**/.env`` protected pattern without shelling out to
    glob inside the (not-yet-mounted) sandbox.
    """
    out: list[str] = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in (".git",)]
        if ".env" in files:
            rel = os.path.relpath(os.path.join(root, ".env"), workspace)
            out.append(rel)
    return out


# BwrapBackend lives in runner.py (needs threading/limits/subprocess
# orchestration this module intentionally stays free of so argv-building
# stays independently testable without forking anything). Re-exported here
# because the integration/bypass corpus imports it from this module name.
def __getattr__(name: str):
    if name == "BwrapBackend":
        from lilguy.sandbox.runner import BwrapBackend
        return BwrapBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
