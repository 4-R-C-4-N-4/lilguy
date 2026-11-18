"""Read files in the host's private session layers even if a command removed read permission.

Only for regular files owned by the current user inside the private session
directory. The workspace and anything reached through a symlink are never
touched: unreadable files there still fail closed.

Every check and every permission change acts on one file handle opened without
following symlinks, never on the path again, so swapping the file for a symlink
after the check cannot redirect the chmod to another file.
"""
from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path


def _proc(fd: int) -> str:
    # /proc/self/fd/N always refers to the exact inode behind fd (even an O_PATH fd).
    return f"/proc/self/fd/{fd}"


@contextlib.contextmanager
def open_private(path: Path, private_root: Path | None):
    path = Path(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except PermissionError:
        if private_root is None:
            raise
        handle = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise
            real = Path(os.readlink(_proc(handle)))
            root = Path(private_root).resolve(strict=True)
            if not real.is_relative_to(root):
                raise
            original = stat.S_IMODE(info.st_mode)
            os.chmod(_proc(handle), original | stat.S_IRUSR)
            try:
                fd = os.open(_proc(handle), os.O_RDONLY | os.O_CLOEXEC)
            finally:
                # The fd stays readable; the file gets its exact original mode back at once.
                os.chmod(_proc(handle), original)
        finally:
            os.close(handle)
    with os.fdopen(fd, "rb") as stream:
        yield stream
