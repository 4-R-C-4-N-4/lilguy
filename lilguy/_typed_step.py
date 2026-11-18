"""Fixed program run by the sandbox runner for the P3 tracer."""
import fnmatch
import itertools
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

EDIT_LIMIT = 1024 * 1024


def checked_path(value):
    root = Path.cwd()
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Expected a workspace-relative path")
    path = root / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Path leaves the workspace")
    return path, resolved


def candidates(path, depth):
    yield path
    if depth == 0 or path.is_symlink() or not path.is_dir():
        return
    for directory, dirs, files in os.walk(path):
        parent = Path(directory)
        dirs.sort()
        for name in sorted(dirs + files):
            yield parent / name
        if depth is not None and len(parent.relative_to(path).parts) + 1 >= depth:
            dirs.clear()


def find(path, name_glob=None, type=None, max_depth=None, max_results=200):
    start, _ = checked_path(path)
    if not start.exists() and not start.is_symlink():
        raise ValueError("Path does not exist")
    matches = {"f": stat.S_ISREG, "d": stat.S_ISDIR, "l": stat.S_ISLNK}
    paths = (
        entry.relative_to(Path.cwd()).as_posix()
        for entry in candidates(start, max_depth)
        if (name_glob is None or fnmatch.fnmatchcase(entry.name, name_glob))
        and (type is None or matches[type](entry.lstat().st_mode))
    )
    for entry in itertools.islice(paths, max_results):
        print(entry)


def read(path, offset, limit):
    _, target = checked_path(path)
    if not target.is_file():
        raise ValueError("Expected a regular file")
    with target.open("rb") as stream:
        for line in itertools.islice(stream, offset - 1, offset - 1 + limit):
            sys.stdout.buffer.write(line)


def edit(path, old, new):
    _, target = checked_path(path)
    if not target.is_file():
        raise ValueError("Expected a regular file")
    with target.open("rb") as stream:
        mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
        original = stream.read(EDIT_LIMIT + 1)
    if len(original) > EDIT_LIMIT:
        raise ValueError("File exceeds the 1 MiB literal edit limit")
    text = original.decode("utf8")
    if "\0" in text or not old or text.count(old) != 1:
        raise ValueError("Expected UTF-8 text and exactly one literal match")
    updated = text.replace(old, new, 1).encode("utf8")
    if updated == original:
        return

    # Stage inside the sandbox on the same filesystem, then publish atomically.
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            stream.write(updated)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)


def main():
    name, _, arguments = sys.argv[1:]
    try:
        {"fs.find": find, "fs.read": read, "fs.edit": edit}[name](**json.loads(arguments))
    except (UnicodeError, OSError, OverflowError, RuntimeError):
        print("Unable to access workspace text", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
