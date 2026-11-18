#!/usr/bin/env python3
"""Minimal Landlock launcher: restrict filesystem writes (and optionally TCP) then exec.

usage: landlock_shim.py --rw DIR [--rw DIR ...] [--ro DIR ...] [--no-tcp] -- CMD ARGS...

Everything not granted is denied for the handled rights. Read/exec is granted on --ro and --rw
paths; write/remove/create/truncate only on --rw paths. Rights apply to the whole hierarchy
beneath each path, so Landlock can't carve a read-only hole out of a writable tree; use a
read-only bind mount for that.
"""
import ctypes
import os
import sys

SYS_CREATE, SYS_ADD, SYS_RESTRICT = 444, 445, 446  # same on x86_64 and aarch64
PR_SET_NO_NEW_PRIVS = 38
RULE_PATH_BENEATH, RULE_NET_PORT = 1, 2

EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
REMOVE_DIR, REMOVE_FILE, MAKE_CHAR, MAKE_DIR = 1 << 4, 1 << 5, 1 << 6, 1 << 7
MAKE_REG, MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM = 1 << 8, 1 << 9, 1 << 10, 1 << 11, 1 << 12
REFER, TRUNCATE, IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15
NET_BIND_TCP, NET_CONNECT_TCP = 1 << 0, 1 << 1

READ = EXECUTE | READ_FILE | READ_DIR
WRITE = (WRITE_FILE | REMOVE_DIR | REMOVE_FILE | MAKE_CHAR | MAKE_DIR | MAKE_REG | MAKE_SOCK
         | MAKE_FIFO | MAKE_BLOCK | MAKE_SYM | REFER | TRUNCATE)

libc = ctypes.CDLL(None, use_errno=True)


class RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]


class PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _chk(r, what):
    if r < 0:
        e = ctypes.get_errno()
        raise OSError(e, f"{what}: {os.strerror(e)}")
    return r


def abi() -> int:
    return libc.syscall(SYS_CREATE, None, 0, 1)


def restrict(rw: list[str], ro: list[str], no_tcp: bool) -> int:
    v = abi()
    if v < 1:
        raise OSError("Landlock unavailable")
    fs = READ | WRITE
    if v < 2:
        fs &= ~REFER
    if v < 3:
        fs &= ~TRUNCATE
    net = (NET_BIND_TCP | NET_CONNECT_TCP) if (no_tcp and v >= 4) else 0
    attr = RulesetAttr(fs, net)
    size = ctypes.sizeof(attr) if v >= 4 else 8  # ABI<4 only knows the fs field
    rfd = _chk(libc.syscall(SYS_CREATE, ctypes.byref(attr), size, 0), "create_ruleset")
    file_only = EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE | IOCTL_DEV
    for paths, access in ((ro, READ), (rw, READ | WRITE)):
        for p in paths:
            if not os.path.exists(p):
                continue  # e.g. /lib64 on aarch64
            fd = os.open(p, os.O_PATH | os.O_CLOEXEC)
            # directory rights on a regular file are EINVAL
            granted = access if os.path.isdir(p) else access & file_only
            rule = PathBeneath(granted & fs, fd)
            _chk(libc.syscall(SYS_ADD, rfd, RULE_PATH_BENEATH, ctypes.byref(rule), 0), f"add_rule {p}")
            os.close(fd)
    _chk(libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0), "no_new_privs")
    _chk(libc.syscall(SYS_RESTRICT, rfd, 0), "restrict_self")
    os.close(rfd)
    return v


def main(argv: list[str]) -> None:
    rw, ro, no_tcp = [], [], False
    i = 0
    while i < len(argv) and argv[i] != "--":
        if argv[i] in ("--rw", "--ro"):
            (rw if argv[i] == "--rw" else ro).append(argv[i + 1])
            i += 2
        elif argv[i] == "--no-tcp":
            no_tcp, i = True, i + 1
        else:
            sys.exit(f"unknown arg {argv[i]}")
    cmd = argv[i + 1:]
    if not cmd:
        sys.exit(__doc__)
    restrict(rw, ro, no_tcp)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main(sys.argv[1:])
