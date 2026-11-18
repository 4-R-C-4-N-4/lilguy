import os

import pytest

from lilguy.sandbox.private_io import open_private


def test_reads_unreadable_private_file_and_restores_exact_mode(tmp_path):
    private = tmp_path / "session"
    private.mkdir()
    target = private / "f"
    target.write_bytes(b"secret")
    os.chmod(target, 0)
    with open_private(target, private) as stream:
        assert stream.read() == b"secret"
    assert target.stat().st_mode & 0o7777 == 0


def test_never_widens_files_outside_the_private_root(tmp_path):
    private = tmp_path / "session"
    private.mkdir()
    outside = tmp_path / "workspace-file"
    outside.write_bytes(b"x")
    os.chmod(outside, 0)
    with pytest.raises(PermissionError):
        with open_private(outside, private):
            pass
    assert outside.stat().st_mode & 0o7777 == 0


def test_never_follows_symlinks(tmp_path):
    private = tmp_path / "session"
    private.mkdir()
    real = tmp_path / "elsewhere"
    real.write_bytes(b"x")
    os.chmod(real, 0)
    (private / "link").symlink_to(real)
    with pytest.raises(OSError):
        with open_private(private / "link", private):
            pass
    assert real.stat().st_mode & 0o7777 == 0


def test_mode_restored_even_if_reading_fails(tmp_path):
    private = tmp_path / "session"
    private.mkdir()
    target = private / "f"
    target.write_bytes(b"x")
    os.chmod(target, 0o200)
    with pytest.raises(RuntimeError):
        with open_private(target, private):
            raise RuntimeError("boom")
    assert target.stat().st_mode & 0o7777 == 0o200


def test_swap_to_symlink_during_permission_bump_never_touches_the_target(tmp_path, monkeypatch):
    # Review finding: the file was chmodded by name, so swapping it for a symlink between the check
    # and the chmod redirected both chmods to any host file. Swap at the first chmod, whatever path.
    import stat as statmod
    from lilguy.sandbox import private_io
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    victim = tmp_path / "outside.txt"
    victim.write_text("host file")
    victim.chmod(0o600)
    inner = root / "f"
    inner.write_text("layer data")
    inner.chmod(0o330)
    real_chmod = os.chmod
    swapped = []

    def racing_chmod(path, mode, *args, **kwargs):
        if not swapped:
            os.unlink(inner)
            os.symlink(victim, inner)
            swapped.append(True)
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(private_io.os, "chmod", racing_chmod)
    try:
        with private_io.open_private(inner, root) as stream:
            data = stream.read()
        assert data == b"layer data"  # read the inode that was checked, not the swapped-in path
    except OSError:
        pass  # failing closed is also acceptable
    assert statmod.S_IMODE(victim.stat().st_mode) == 0o600
    assert victim.read_text() == "host file"
