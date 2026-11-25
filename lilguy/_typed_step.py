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


# --- interface v6: typed permission and archive tools (docs/plan/INTERFACE-V6.md) ---------------

_BITS = {"u": {"read": stat.S_IRUSR, "write": stat.S_IWUSR, "execute": stat.S_IXUSR},
         "g": {"read": stat.S_IRGRP, "write": stat.S_IWGRP, "execute": stat.S_IXGRP},
         "o": {"read": stat.S_IROTH, "write": stat.S_IWOTH, "execute": stat.S_IXOTH}}


def _symbolic(mode):
    return "".join(c if mode & bit else "-" for c, bit in zip(
        "rwxrwxrwx", (stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR, stat.S_IRGRP, stat.S_IWGRP,
                      stat.S_IXGRP, stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH)))


def _chmod_targets(path):
    """A path or a glob (helpers/*.sh), workspace-relative, sorted; symlinks are never followed."""
    if not any(c in path for c in "*?["):
        start, target = checked_path(path)
        if not target.exists() and not start.is_symlink():
            raise ValueError(_absent(path))
        return [start]
    import glob
    hits = []
    for name in sorted(glob.glob(path)):
        start, _ = checked_path(name)
        hits.append(start)
    if not hits:
        raise ValueError(_absent(path))
    return hits


def _class_mode(scope, value, before):
    """New bits of one class (u, g or o) from a v6 value: keep, a final state, or add/remove one."""
    bits = _BITS[scope]
    mask = bits["read"] | bits["write"] | bits["execute"]
    if value == "keep":
        return before & mask
    if value.startswith(("add ", "remove ")):
        action, permission = value.split(" ")
        return (before | bits[permission]) & mask if action == "add" else before & mask & ~bits[permission]
    words = () if value == "none" else value.split(" ")
    return sum(bits[w] for w in words)


def chmod(path, user="keep", group="keep", others="keep", recursive=False):
    values = {"u": user, "g": group, "o": others}
    if all(v == "keep" for v in values.values()):
        raise ValueError("Nothing to change: give user, group or others a value other than keep")
    for start in _chmod_targets(path):
        if start.is_symlink():
            raise ValueError(f"{start.relative_to(Path.cwd()).as_posix()} is a symbolic link")
        for entry in candidates(start, None if recursive else 0):
            if entry.is_symlink():
                continue
            before = stat.S_IMODE(entry.lstat().st_mode)
            after = before & ~0o777
            for scope, value in values.items():
                after |= _class_mode(scope, value, before)
            name = entry.relative_to(Path.cwd()).as_posix()
            if after != before:
                os.chmod(entry, after)
                print(f"{name}: {_symbolic(before)} -> {_symbolic(after)}")
            else:
                print(f"{name}: {_symbolic(before)} (unchanged)")


def _kind(path):
    name = path.lower()
    if name.endswith((".tar.gz", ".tgz")):
        return "tar.gz"
    if name.endswith(".tar"):
        return "tar"
    if name.endswith(".gz"):
        return "gz"
    raise ValueError(f"{path}: expected a .tar, .tar.gz, .tgz or .gz archive")


def _open_tar(target, path, mode="r:*"):
    import tarfile
    try:
        return tarfile.open(target, mode)
    except (tarfile.TarError, EOFError) as exc:
        raise ValueError(f"{path} is not a readable archive") from exc


def archive_list(path, compare=False):
    import gzip
    _, target = checked_path(path)
    if not target.is_file():
        raise ValueError(_missing(path, target))
    if _kind(path) == "gz":
        try:
            data = gzip.decompress(target.read_bytes())
        except (OSError, EOFError) as exc:
            raise ValueError(f"{path} is not a readable archive") from exc
        inner = path[:-3]
        if not compare:
            print(f"{Path(inner).name} {len(data)} bytes")
            return
        local, _ = checked_path(str(Path(path).parent / Path(inner).name))
        state = "missing" if not local.is_file() else "same" if local.read_bytes() == data else "differs"
        print(f"{Path(inner).name} {state}")
        return
    with _open_tar(target, path) as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("./")
            if member.isdir():
                if not compare:
                    print(f"{name}/")
                continue
            if not compare:
                print(f"{name} {member.size} bytes" if member.isfile() else f"{name} (link)")
                continue
            try:
                local, _ = checked_path(name)
            except ValueError:
                print(f"{name} outside the workspace")
                continue
            if not member.isfile():
                print(f"{name} (link, not compared)")
            elif not local.is_file():
                print(f"{name} missing")
            else:
                same = local.read_bytes() == tar.extractfile(member).read()
                print(f"{name} {'same' if same else 'differs'}")


def archive_pack(archive, source, exclude=None, top_folder=True):
    _pack(archive, source, exclude=exclude, add=False, top_folder=top_folder)


def archive_add(archive, source):
    _pack(archive, source, exclude=None, add=True, top_folder=True)


def _pack(archive, source, exclude=None, add=False, top_folder=True):
    import gzip
    import io
    import tarfile
    out, out_resolved = checked_path(archive)
    src, src_resolved = checked_path(source)
    if not src_resolved.exists():
        raise ValueError(_absent(source))
    if src.is_symlink():
        raise ValueError(f"{source} is a symbolic link")
    kind = _kind(archive)
    if kind == "gz":
        if not src_resolved.is_file():
            raise ValueError(f"{source}: .gz holds one file; use .tar.gz for a folder")
        if add:
            raise ValueError(".gz holds one file; archive.add needs a .tar or .tar.gz archive")
        out.write_bytes(gzip.compress(src_resolved.read_bytes()))
        print(f"{archive}: {source}")
        return
    if out_resolved.is_dir():
        raise ValueError(f"{archive} is a directory, not a file")
    if src_resolved == out_resolved or (src_resolved.is_dir() and out_resolved.is_relative_to(src_resolved)):
        raise ValueError(f"{archive} must not be inside {source}")
    root = Path.cwd()
    keep = []  # (name, bytes, mode) already in the archive, kept when adding
    if add:
        if not out_resolved.is_file():
            raise ValueError(_missing(archive, out_resolved))
        with _open_tar(out_resolved, archive) as old:
            for member in old.getmembers():
                if member.isfile():
                    keep.append((member.name, old.extractfile(member).read(), member.mode))
    # A file keeps its workspace path inside the archive, as tar does (kit/easel.txt); a folder keeps
    # its own name (top_folder) or contributes only its contents.
    base = root if src_resolved.is_file() else src.parent if top_folder else src
    files = []
    for entry in candidates(src, None):
        if entry.is_symlink() or not entry.is_file():
            continue
        if exclude and fnmatch.fnmatchcase(entry.name, exclude):
            continue
        files.append(entry)
    names = [entry.relative_to(base).as_posix() for entry in files]
    added = set(names)
    mode = "w:gz" if kind == "tar.gz" else "w"
    if out_resolved.is_file():
        file_mode = stat.S_IMODE(out_resolved.stat().st_mode)  # like fs.edit: replacing keeps the mode
    else:
        umask = os.umask(0)
        os.umask(umask)
        file_mode = 0o666 & ~umask
    with tempfile.NamedTemporaryFile(dir=out.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        with tarfile.open(staged, mode, format=tarfile.PAX_FORMAT) as tar:
            for name, data, member_mode in keep:
                if name in added:
                    continue
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), member_mode
                tar.addfile(info, io.BytesIO(data))
            for entry, name in zip(files, names):
                tar.add(entry, arcname=name, recursive=False)
        os.chmod(staged, file_mode)
        staged.replace(out)
    finally:
        staged.unlink(missing_ok=True)
    for name in names:
        print(name)


def archive_unpack(archive, into=".", member=None, overwrite=False):
    import gzip
    import tarfile
    _, source = checked_path(archive)
    if not source.is_file():
        raise ValueError(_missing(archive, source))
    dest, dest_resolved = checked_path(into)
    if dest_resolved.exists() and not dest_resolved.is_dir():
        raise ValueError(f"{into} is a file, not a folder")
    root = Path.cwd()
    if _kind(archive) == "gz":
        name = Path(archive).name[:-3]
        if member not in (None, name):
            raise ValueError(f"{archive} holds only {name}")
        try:
            data = gzip.decompress(source.read_bytes())
        except (OSError, EOFError) as exc:
            raise ValueError(f"{archive} is not a readable archive") from exc
        target, resolved = checked_path((dest / name).relative_to(root).as_posix())
        if resolved.exists() and not overwrite:
            print(f"kept existing: {target.relative_to(root).as_posix()}")
            return
        dest.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print(f"unpacked: {target.relative_to(root).as_posix()}")
        return
    written, kept = [], []
    with _open_tar(source, archive) as tar:
        members = tar.getmembers()
        if member is not None:
            members = [m for m in members if m.name.removeprefix("./") == member.removeprefix("./")]
            if not members:
                raise ValueError(f"{member} is not in {archive}")
        chosen = []
        for m in members:
            try:
                m = tarfile.data_filter(m, str(dest_resolved))
            except tarfile.FilterError as exc:
                raise ValueError(f"{archive}: refused member {m.name} ({exc.__class__.__name__})") from exc
            if m is None:
                continue
            final = dest_resolved / m.name
            shown = (dest / m.name).relative_to(root).as_posix()
            if m.isfile() and final.exists() and not overwrite:
                kept.append(shown)
                continue
            chosen.append(m)
            if m.isfile():
                written.append(shown)
        dest.mkdir(parents=True, exist_ok=True)
        tar.extractall(dest_resolved, members=chosen, filter="data")
    for name in written:
        print(f"unpacked: {name}")
    for name in kept:
        print(f"kept existing: {name}")


INTERFACE = 3  # the interface version the step reports to; set from the server's argv


class _TarError(Exception):
    """Placeholder until tarfile is imported (only archive tools need it)."""


def main():
    global INTERFACE
    name, _, arguments, *rest = sys.argv[1:]
    INTERFACE = int(rest[0]) if rest else 3
    global _TarError
    if name.startswith("archive."):
        import tarfile
        _TarError = tarfile.TarError
    try:
        {"fs.find": find, "fs.read": read, "fs.edit": edit,
         "fs.list": list_, "fs.grep": grep, "fs.chmod": chmod, "archive.list": archive_list,
         "archive.pack": archive_pack, "archive.add": archive_add, "archive.unpack": archive_unpack}[name](**json.loads(arguments))
    except (UnicodeError, OSError, OverflowError, RuntimeError):
        print("Unable to access workspace text", file=sys.stderr)
        return 1
    except _TarError as exc:
        print(f"Archive error: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
