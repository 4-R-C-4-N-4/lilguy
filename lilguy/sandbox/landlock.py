"""Landlock-restrict-self shim, run *inside* the bwrap sandbox.

This module is intentionally stdlib-only and import-free of the rest of
``lilguy`` so the single file can be read-only bound into the sandbox and
executed there even though the rest of the package/venv is not bound in.

Two jobs, both performed inside the sandbox mount/user namespace before the
user's command ever runs:

1. Apply an ABI-aware Landlock ruleset restricting filesystem access (and,
   where the running kernel's ABI supports it, TCP bind/connect) to an
   explicit allow-list of writable paths plus a read-only root. Rights
   actually requested are masked down to what the detected ABI understands
   (ABI1 base rights; REFER added at ABI>=2; TRUNCATE added at ABI>=3;
   network TCP handling added at ABI>=4) -- asking for an unsupported right
   makes ``landlock_create_ruleset`` fail outright, so silently trying the
   full set unconditionally would break every pre-ABI4 kernel.
2. Receive the real RunSpec over an inherited fd (never via argv, so a
   crafted command string can't masquerade as shell/argv parsing), apply
   rlimits, run it, and report a bounded JSON result ({"exit_code", "cwd",
   "error"}) back over a dedicated result fd (never via stdout, which
   stays exactly what the user's program printed).

Fails closed: if Landlock is unavailable (ABI < 1), the architecture's
syscall numbers are unknown, or a requested writable path would create a
hole inside a protected mount, this refuses to run anything rather than
silently skipping containment.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import select
import stat
import subprocess
import sys

# landlock_create_ruleset / landlock_add_rule / landlock_restrict_self syscall
# numbers. Landlock is Linux-specific and syscall numbers are
# architecture-dependent; an unknown architecture must fail closed, never
# guess.
_SYSCALL_NRS: dict[str, tuple[int, int, int]] = {
    "x86_64": (444, 445, 446),
    "aarch64": (444, 445, 446),
    "arm64": (444, 445, 446),
}

_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
_LANDLOCK_RULE_PATH_BENEATH = 1
_LANDLOCK_RULE_NET_PORT = 2

_ACCESS_FS_EXECUTE = 1 << 0
_ACCESS_FS_WRITE_FILE = 1 << 1
_ACCESS_FS_READ_FILE = 1 << 2
_ACCESS_FS_READ_DIR = 1 << 3
_ACCESS_FS_REMOVE_DIR = 1 << 4
_ACCESS_FS_REMOVE_FILE = 1 << 5
_ACCESS_FS_MAKE_CHAR = 1 << 6
_ACCESS_FS_MAKE_DIR = 1 << 7
_ACCESS_FS_MAKE_REG = 1 << 8
_ACCESS_FS_MAKE_SOCK = 1 << 9
_ACCESS_FS_MAKE_FIFO = 1 << 10
_ACCESS_FS_MAKE_BLOCK = 1 << 11
_ACCESS_FS_MAKE_SYM = 1 << 12
_ACCESS_FS_REFER = 1 << 13          # ABI >= 2
_ACCESS_FS_TRUNCATE = 1 << 14       # ABI >= 3
_ACCESS_FS_IOCTL_DEV = 1 << 15      # ABI >= 5 (harmless to omit otherwise)

_ACCESS_NET_BIND_TCP = 1 << 0       # ABI >= 4
_ACCESS_NET_CONNECT_TCP = 1 << 1    # ABI >= 4

# Rights that only make sense on a regular file (used to mask what we
# request on non-directory paths -- directory-only rights on a regular
# file make landlock_add_rule fail with EINVAL).
_FILE_ONLY_RIGHTS = (
    _ACCESS_FS_EXECUTE | _ACCESS_FS_WRITE_FILE | _ACCESS_FS_READ_FILE
    | _ACCESS_FS_TRUNCATE | _ACCESS_FS_IOCTL_DEV
)

_ALL_FS_ABI1 = (
    _ACCESS_FS_EXECUTE | _ACCESS_FS_WRITE_FILE | _ACCESS_FS_READ_FILE | _ACCESS_FS_READ_DIR
    | _ACCESS_FS_REMOVE_DIR | _ACCESS_FS_REMOVE_FILE | _ACCESS_FS_MAKE_CHAR | _ACCESS_FS_MAKE_DIR
    | _ACCESS_FS_MAKE_REG | _ACCESS_FS_MAKE_SOCK | _ACCESS_FS_MAKE_FIFO | _ACCESS_FS_MAKE_BLOCK
    | _ACCESS_FS_MAKE_SYM
)
_READ_ONLY_BASE = _ACCESS_FS_EXECUTE | _ACCESS_FS_READ_FILE | _ACCESS_FS_READ_DIR
_WRITE_FILE_ONLY = _ACCESS_FS_WRITE_FILE

# Mounts that must never be handed a writable rule even if the caller's
# writable list (by misconfiguration or a path-traversal bug upstream)
# contains something beneath them. apply_landlock does not trust "the
# writable list has no hole" as an invariant enforced elsewhere; it
# re-checks here.
_PROTECTED_PREFIXES = ("/proc", "/sys", "/dev/cgroup")


class LandlockError(RuntimeError):
    pass


class LimitsError(RuntimeError):
    """Raised when a configured resource limit cannot be applied inside the
    sandbox. Mirrors lilguy.sandbox.limits.LimitsError but this module is
    kept stdlib-only and import-free of the rest of lilguy (it is
    bind-mounted into the sandbox on its own), so the logic is
    duplicated here rather than imported."""


def _syscall_nrs() -> tuple[int, int, int]:
    arch = platform.machine()
    nrs = _SYSCALL_NRS.get(arch)
    if nrs is None:
        raise LandlockError(f"unknown Landlock syscall numbers for arch {arch!r}; refusing to run unconfined")
    return nrs


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64),
                ("scoped", ctypes.c_uint64)]


# ABI >= 6: keep abstract unix sockets and signals inside this Landlock domain. With a shared
# network namespace (a step that was allowed network), abstract sockets of the host session
# (D-Bus, X11, ...) would otherwise be reachable.
_SCOPE_ABSTRACT_UNIX_SOCKET = 1 << 0
_SCOPE_SIGNAL = 1 << 1


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _layout_ = "ms"
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def landlock_abi() -> int:
    create_nr, _, _ = _syscall_nrs()
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(create_nr, None, 0, _LANDLOCK_CREATE_RULESET_VERSION)
    return abi


def _fs_rights_for_abi(abi: int) -> int:
    rights = _ALL_FS_ABI1
    if abi >= 2:
        rights |= _ACCESS_FS_REFER
    if abi >= 3:
        rights |= _ACCESS_FS_TRUNCATE
    if abi >= 5:
        rights |= _ACCESS_FS_IOCTL_DEV
    return rights


def _net_rights_for_abi(abi: int) -> int:
    if abi >= 4:
        return _ACCESS_NET_BIND_TCP | _ACCESS_NET_CONNECT_TCP
    return 0


def _is_protected(path: str) -> bool:
    real = os.path.realpath(path)
    return any(real == p or real.startswith(p + "/") for p in _PROTECTED_PREFIXES)


def apply_landlock(*, writable: list[str], read_only_root: str = "/", allow_tcp: bool = False) -> None:
    """Restrict this process (and all its future children) via Landlock.

    ``writable`` paths get the full set of rights this kernel's Landlock
    ABI understands (read/write/create/remove/refer/truncate as
    available). ``read_only_root`` (default ``/``) gets read+execute
    only. Rights actually granted to each path are additionally masked
    by ``lstat`` of that path: directory-only rights are never requested
    on a regular file (or a symlink to one), which would otherwise make
    the underlying syscall fail with EINVAL. Any writable path that
    resolves inside a protected mount (``/proc``, ``/sys``, a cgroupfs)
    is rejected outright rather than silently granted -- callers must
    not assume the caller-supplied writable list is hole-free.

    Raises LandlockError (fail closed) if the ABI is unavailable, the
    architecture's syscall numbers are unknown, a writable path is
    protected, or any syscall fails; callers must treat that as "do not
    proceed".
    """
    create_nr, add_rule_nr, restrict_self_nr = _syscall_nrs()
    abi = landlock_abi()
    if abi < 1:
        raise LandlockError(f"Landlock unavailable on this host (abi={abi})")
    if allow_tcp and abi < 6:
        raise LandlockError(f"network needs Landlock ABI >= 6 to keep host IPC sockets out (abi={abi})")

    for path in writable:
        if _is_protected(path):
            raise LandlockError(f"refusing to grant write access inside protected mount: {path}")

    libc = ctypes.CDLL(None, use_errno=True)

    PR_SET_NO_NEW_PRIVS = 38
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise LandlockError("prctl(PR_SET_NO_NEW_PRIVS) failed")

    fs_rights = _fs_rights_for_abi(abi)
    # A step allowed network: TCP is simply not handled (allowed); everything else stays.
    net_rights = 0 if allow_tcp else _net_rights_for_abi(abi)
    scoped = (_SCOPE_ABSTRACT_UNIX_SOCKET | _SCOPE_SIGNAL) if abi >= 6 else 0
    attr = _RulesetAttr(handled_access_fs=fs_rights, handled_access_net=net_rights, scoped=scoped)
    # ABI < 4 kernels only know the fs field; passing the net field's
    # bytes to a kernel that doesn't understand them makes
    # landlock_create_ruleset fail, so the struct size passed must match
    # what this ABI understands.
    attr_size = (ctypes.sizeof(attr) if abi >= 6 else 2 * ctypes.sizeof(ctypes.c_uint64) if abi >= 4
                 else ctypes.sizeof(ctypes.c_uint64))
    ruleset_fd = libc.syscall(create_nr, ctypes.byref(attr), attr_size, 0)
    if ruleset_fd < 0:
        errno = ctypes.get_errno()
        raise LandlockError(f"landlock_create_ruleset failed (errno={errno})")

    try:
        if os.path.exists(read_only_root):
            _add_rule(libc, add_rule_nr, ruleset_fd, read_only_root, _READ_ONLY_BASE, fs_rights)
        for path in writable:
            if not os.path.exists(path):
                continue
            _add_rule(libc, add_rule_nr, ruleset_fd, path, fs_rights, fs_rights)
        for dev in ("/dev/null", "/dev/zero"):
            if os.path.exists(dev):
                _add_rule(libc, add_rule_nr, ruleset_fd, dev,
                          _WRITE_FILE_ONLY | _ACCESS_FS_READ_FILE, fs_rights)

        ret = libc.syscall(restrict_self_nr, ruleset_fd, 0)
        if ret != 0:
            errno = ctypes.get_errno()
            raise LandlockError(f"landlock_restrict_self failed (errno={errno})")
    finally:
        os.close(ruleset_fd)


def _add_rule(libc, add_rule_nr: int, ruleset_fd: int, path: str, requested: int, fs_rights: int) -> None:
    # lstat (not stat): a symlink itself must not be treated as "whatever
    # it points to" when deciding directory-vs-file rights, and O_PATH
    # below with O_NOFOLLOW-free open still resolves the link for the
    # actual rule target, which is the intended behaviour for Landlock
    # (rules apply to the resolved path); the masking decision uses the
    # resolved target's type.
    try:
        st = os.stat(path)
    except OSError as exc:
        raise LandlockError(f"cannot stat {path}: {exc}") from exc
    granted = requested if stat.S_ISDIR(st.st_mode) else (requested & _FILE_ONLY_RIGHTS)
    granted &= fs_rights
    parent_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        rule = _PathBeneathAttr(allowed_access=granted, parent_fd=parent_fd)
        ret = libc.syscall(add_rule_nr, ruleset_fd, _LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule), 0)
        if ret != 0:
            errno = ctypes.get_errno()
            raise LandlockError(f"landlock_add_rule({path}) failed (errno={errno})")
    finally:
        os.close(parent_fd)


# ---------------------------------------------------------------------------
# In-sandbox entrypoint: apply landlock + rlimits, run the real RunSpec from
# an inherited fd, report a bounded JSON result over a dedicated result fd.
# Never trust argv for the command (it is passed as JSON over a pipe
# instead) and never trust stdout for cwd (a dedicated cwd pipe, inherited
# only to the shell process, carries that).
# ---------------------------------------------------------------------------

_MAX_SPEC_BYTES = 1024 * 1024


class _CfgLimits:
    __slots__ = ("max_processes", "max_file_bytes", "memory_bytes")

    def __init__(self, max_processes: int, max_file_bytes: int, memory_bytes: int) -> None:
        self.max_processes = max_processes
        self.max_file_bytes = max_file_bytes
        self.memory_bytes = memory_bytes


def _rlimit_preexec_fn(cfg: "_CfgLimits"):
    """Return a preexec_fn applying rlimits to the about-to-exec child.

    Runs inside the sandbox's own pid namespace, where RLIMIT_NPROC
    counts only processes within that namespace, so an absolute cap
    here is meaningful rather than colliding with unrelated host
    processes. Raises LimitsError instead of swallowing failures --
    a cap we were told to enforce must either land or the step must
    not proceed.
    """
    import resource

    def _apply() -> None:
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_CORE: {exc}") from exc
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (cfg.max_processes, cfg.max_processes))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_NPROC: {exc}") from exc
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (cfg.max_file_bytes, cfg.max_file_bytes))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_FSIZE: {exc}") from exc
        try:
            resource.setrlimit(resource.RLIMIT_AS, (cfg.memory_bytes, cfg.memory_bytes))
        except OSError as exc:
            raise LimitsError(f"failed to set RLIMIT_AS: {exc}") from exc

    return _apply



def _read_bounded(fd: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, max_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise LandlockError(f"input on fd {fd} exceeds {max_bytes} byte bound")
        chunks.append(chunk)
    return b"".join(chunks)


def _drain_nonblocking(fd: int, max_bytes: int) -> bytes:
    """Read whatever is already buffered on fd without blocking.

    Called only after the child that could write to it has already
    exited, so a crafted grandchild holding the fd open can't make this
    block forever; any data it still wrote before the child reaped is
    read, but this never waits on it.
    """
    os.set_blocking(fd, False)
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
            chunk = os.read(fd, 65536)
        except (BlockingIOError, OSError):
            break
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            chunks.append(chunk[: max_bytes - (total - len(chunk))])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _run_spec(spec: dict, cfg_limits, max_output_bytes: int) -> dict:
    """Run the RunSpec; returns {"exit_code", "cwd", "error"}.

    ``shell`` RunSpecs run under ``bash --noprofile --norc -c`` (never a
    bare ``/bin/sh`` whose profile/rc files are outside our control) with
    a *separate* cwd pipe inherited only to that bash process -- the
    shell prints its final ``pwd`` onto that dedicated fd as its very
    last statement so a `cd` in the middle of the script is reflected
    afterward, without needing to trust stdout (which stays exactly what
    the user's script printed) or this process's own cwd (a `cd` inside
    a forked child never propagates back to the parent).

    ``argv`` and ``pipe`` RunSpecs are never routed through a shell:
    ``argv`` is a single direct ``Popen``; ``pipe`` builds a real
    pipeline of direct ``Popen`` stages connected by OS pipes (not
    ``" | ".join(...)`` fed to a shell), and only the last stage's exit
    code is reported, matching normal pipeline semantics. Neither has a
    meaningful "final cwd" beyond what chdir already set, so ``cwd`` is
    left as ``None`` for them.

    The cwd pipe (and no other fd) is passed to the shell child; argv
    and pipe stages never receive it, and none of the three paths pass
    the result fd itself to any untrusted argv -- that fd only exists in
    this process.
    """
    timeout_s = spec.get("timeout_s")
    preexec = _rlimit_preexec_fn(cfg_limits) if cfg_limits is not None else None
    try:
        if spec.get("shell") is not None:
            cwd_r, cwd_w = os.pipe()
            try:
                os.set_inheritable(cwd_w, True)
                script = (
                    f"{spec['shell']}\n__lilguy_rc=$?\n"
                    f"printf '%s' \"$(pwd)\" >&{cwd_w} 2>/dev/null || true\n"
                    f"exit $__lilguy_rc\n"
                )
                proc = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-c", script],
                    timeout=timeout_s,
                    pass_fds=(cwd_w,),
                    stdin=subprocess.DEVNULL,
                    preexec_fn=preexec,
                )
                os.close(cwd_w)
                cwd_w = -1
                cwd_bytes = _drain_nonblocking(cwd_r, 65536)
                cwd = cwd_bytes.decode("utf-8", "replace") or None
                return {"exit_code": proc.returncode, "cwd": cwd, "error": None}
            finally:
                os.close(cwd_r)
                if cwd_w >= 0:
                    os.close(cwd_w)
        elif spec.get("argv") is not None:
            proc = subprocess.run(
                spec["argv"], timeout=timeout_s, stdin=subprocess.DEVNULL, preexec_fn=preexec,
            )
            return {"exit_code": proc.returncode, "cwd": None, "error": None}
        elif spec.get("pipe") is not None:
            stages = spec["pipe"]
            procs = []
            prev_stdout = None
            for i, stage in enumerate(stages):
                is_last = i == len(stages) - 1
                p = subprocess.Popen(
                    stage,
                    stdin=prev_stdout if prev_stdout is not None else subprocess.DEVNULL,
                    stdout=None if is_last else subprocess.PIPE,
                    preexec_fn=preexec,
                )
                if prev_stdout is not None:
                    prev_stdout.close()
                prev_stdout = p.stdout
                procs.append(p)
            last_rc = None
            for p in procs:
                try:
                    p.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:
                    for proc_ in procs:
                        proc_.kill()
                    return {"exit_code": 124, "cwd": None, "error": None}
                last_rc = p.returncode
            return {"exit_code": last_rc, "cwd": None, "error": None}
        else:
            raise LandlockError("RunSpec has none of shell/argv/pipe set")
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "cwd": None, "error": None}
    except LimitsError as exc:
        return {"exit_code": 125, "cwd": None, "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="append", default=[], dest="writable")
    parser.add_argument("--chdir", default=".")
    parser.add_argument("--allow-net", action="store_true")
    parser.add_argument("--spec-fd", type=int, required=True)
    parser.add_argument("--result-fd", type=int, required=True)
    parser.add_argument("--max-output-bytes", type=int, default=256_000)
    parser.add_argument("--max-file-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--memory-bytes", type=int, default=1024 * 1024 * 1024)
    parser.add_argument("--max-processes", type=int, default=64)
    args = parser.parse_args(argv)

    try:
        os.chdir(args.chdir)
    except OSError as exc:
        _report_result(args.result_fd, {"exit_code": 126, "cwd": None, "error": f"chdir failed: {exc}"})
        return 126

    try:
        apply_landlock(writable=args.writable, allow_tcp=args.allow_net)
    except LandlockError as exc:
        _report_result(args.result_fd, {"exit_code": 125, "cwd": None, "error": str(exc)})
        return 125

    try:
        spec_bytes = _read_bounded(args.spec_fd, _MAX_SPEC_BYTES)
        spec = json.loads(spec_bytes.decode("utf-8"))
    except (LandlockError, ValueError) as exc:
        _report_result(args.result_fd, {"exit_code": 125, "cwd": None, "error": f"bad spec: {exc}"})
        return 125
    finally:
        os.close(args.spec_fd)

    cfg_limits = _CfgLimits(
        max_processes=args.max_processes,
        max_file_bytes=args.max_file_bytes,
        memory_bytes=args.memory_bytes,
    )
    result = _run_spec(spec, cfg_limits, args.max_output_bytes)
    _report_result(args.result_fd, result)
    return result["exit_code"]


def _report_result(result_fd: int, result: dict) -> None:
    payload = json.dumps(result).encode("utf-8")
    with os.fdopen(result_fd, "wb") as result_f:
        result_f.write(payload)
        result_f.flush()


if __name__ == "__main__":
    sys.exit(main())
