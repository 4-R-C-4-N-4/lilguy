"""Fixed program run by the sandbox runner for the P3 tracer."""
import fnmatch
import itertools
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

EDIT_LIMIT = 1024 * 1024


def _missing(path, target):
    """Interface v5 names a path that does not exist instead of calling it the wrong type."""
    if INTERFACE >= 5:
        if not target.exists() and not target.is_symlink():
            return f"No such file: {path}"
        if target.is_dir():
            return f"{path} is a directory, not a file"
    return "Expected a regular file"


def _absent(path):
    return f"No such file or directory: {path}" if INTERFACE >= 5 else "Path does not exist"


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
        raise ValueError(_absent(path))
    matches = {"f": stat.S_ISREG, "d": stat.S_ISDIR, "l": stat.S_ISLNK}
    paths = (
        entry.relative_to(Path.cwd()).as_posix()
        for entry in candidates(start, max_depth)
        if (name_glob is None or fnmatch.fnmatchcase(entry.name, name_glob))
        and (type is None or matches[type](entry.lstat().st_mode))
    )
    for entry in itertools.islice(paths, max_results):
        print(entry)


LIST_RESULT_CAP = 2000  # not in the schema; internal safety cap so list can't dump huge trees


def _listable(path, depth):
    """Children of `path` up to `depth` levels, skipping symlinked directories."""
    if depth is not None and depth <= 0:
        return
    for directory, dirs, files in os.walk(path):
        parent = Path(directory)
        level = len(parent.relative_to(path).parts) + 1
        dirs.sort()
        for name in sorted(dirs + files):
            yield parent / name
        if (depth is not None and level >= depth) or (parent / "").is_symlink():
            dirs.clear()
        dirs[:] = [d for d in dirs if not (parent / d).is_symlink()]


def list_(path, depth=1, show_hidden=False, detailed=True):
    start, _ = checked_path(path)
    if not start.exists() and not start.is_symlink():
        raise ValueError(_absent(path))
    if start.is_symlink() or not start.is_dir():
        entries = [start]
    else:
        entries = _listable(start, depth)
    root = Path.cwd()
    count = 0
    for entry in entries:
        if not show_hidden and any(part.startswith(".") for part in entry.relative_to(start).parts):
            continue
        if count >= LIST_RESULT_CAP:
            break
        count += 1
        relative = entry.relative_to(root).as_posix()
        if not detailed:
            print(relative)
            continue
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode):
            kind = "l"
        elif stat.S_ISDIR(info.st_mode):
            kind = "d"
        else:
            kind = "f"
        print(f"{kind} {info.st_size:>10} {relative}")


_TEXT_SUFFIX_ERROR = (UnicodeDecodeError,)


def grep(pattern, path=".", glob=None, regex=False, ignore_case=False, line_numbers=False,
          invert=False, recursive=True, filenames_only=False, max_results=200):
    start, _ = checked_path(path)
    if not start.exists() and not start.is_symlink():
        raise ValueError(_absent(path))
    if start.is_symlink():
        raise ValueError("Path does not exist")
    if start.is_dir():
        if recursive:
            targets = (
                entry for entry in candidates(start, None) if entry != start and entry.is_file()
                and not entry.is_symlink()
                and not any(part.startswith(".") for part in entry.relative_to(start).parts)
            )
        else:
            targets = (
                entry for entry in sorted(start.iterdir())
                if entry.is_file() and not entry.is_symlink() and not entry.name.startswith(".")
            )
    else:
        if not start.is_file():
            raise ValueError(_missing(path, start))
        targets = iter([start])
    if glob is not None:
        targets = (entry for entry in targets if fnmatch.fnmatchcase(entry.name, glob))

    flags = re.IGNORECASE if ignore_case else 0
    matcher = re.compile(pattern, flags) if regex else None

    def line_matches(line):
        if matcher is not None:
            found = matcher.search(line) is not None
        else:
            found = (pattern.casefold() in line.casefold()) if ignore_case else (pattern in line)
        return found != invert

    root = Path.cwd()
    seen_files = set()
    emitted = 0
    for entry in targets:
        if emitted >= max_results:
            break
        relative = entry.relative_to(root).as_posix()
        try:
            with entry.open("r", encoding="utf8") as stream:
                for number, line in enumerate(stream, start=1):
                    if emitted >= max_results:
                        break
                    if not line_matches(line.rstrip("\n")):
                        continue
                    if filenames_only:
                        if relative not in seen_files:
                            seen_files.add(relative)
                            print(relative)
                            emitted += 1
                        break
                    if line_numbers:
                        print(f"{relative}:{number}:{line.rstrip(chr(10))}")
                    else:
                        print(f"{relative}:{line.rstrip(chr(10))}")
                    emitted += 1
        except _TEXT_SUFFIX_ERROR:
            continue


def read(path, offset, limit):
    _, target = checked_path(path)
    if not target.is_file():
        raise ValueError(_missing(path, target))
    with target.open("rb") as stream:
        for line in itertools.islice(stream, offset - 1, offset - 1 + limit):
            sys.stdout.buffer.write(line)


def _edit_refusal(path, text, old):
    """Interface v4: say why an edit matched zero or several times, and how to pick one."""
    starts, at = [], text.find(old)
    while at != -1:
        starts.append(text.count("\n", 0, at) + 1)
        at = text.find(old, at + 1)
    if not starts:
        hint = " (check spaces and line breaks against the file)" if old.strip() in text else ""
        return f"old text not found in {path}{hint}"
    lines = ", ".join(map(str, starts[:10])) + (", ..." if len(starts) > 10 else "")
    return (f"old text occurs {len(starts)} times in {path} (lines {lines}); "
            "put old in <<< >>> with a neighbouring line so it occurs once")


def edit(path, old, new):
    _, target = checked_path(path)
    if not target.is_file():
        raise ValueError(_missing(path, target))
    with target.open("rb") as stream:
        mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
        original = stream.read(EDIT_LIMIT + 1)
    if len(original) > EDIT_LIMIT:
        raise ValueError("File exceeds the 1 MiB literal edit limit")
    text = original.decode("utf8")
    if "\0" in text or not old or text.count(old) != 1:
        if INTERFACE >= 4 and "\0" not in text and old:
            raise ValueError(_edit_refusal(path, text, old))
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


INTERFACE = 3  # the interface version the step reports to; set from the server's argv


def main():
    global INTERFACE
    name, _, arguments, *rest = sys.argv[1:]
    INTERFACE = int(rest[0]) if rest else 3
    try:
        {"fs.find": find, "fs.read": read, "fs.edit": edit,
         "fs.list": list_, "fs.grep": grep}[name](**json.loads(arguments))
    except (UnicodeError, OSError, OverflowError, RuntimeError):
        print("Unable to access workspace text", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
