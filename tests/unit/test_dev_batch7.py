"""Batch 7 (archives, organise, recovery): archive grading is content-based, and categories line up."""
import gzip
import io
import tarfile
from collections import Counter

from dev import broad_runner, dev_archives, dev_categories, fast12
from dev.fast12_runner import describe_archive


def _tar(members, mtime, compress):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz' if compress else 'w') as tar:
        for path, text in members.items():
            info = tarfile.TarInfo(path)
            info.size, info.mtime = len(text), mtime
            tar.addfile(info, io.BytesIO(text.encode()))
    return buf.getvalue()


def test_archive_description_ignores_timestamps_and_matches_expected():
    members = {'b/two.txt': 'two\n', 'a.txt': 'one\n'}
    for compress, kind in ((True, 'tar.gz'), (False, 'tar')):
        first, second = _tar(members, 1, compress), _tar(members, 2, compress)
        assert first != second
        assert describe_archive(first) == describe_archive(second) == dev_archives.archive(kind, members)
    assert describe_archive(gzip.compress(b'log\n', mtime=5)) == dev_archives.gzipped('log\n')
    assert describe_archive(b'plain text\n') is None


def test_tar_fixture_round_trips_as_text():
    text = dev_archives.tar_fixture({'x.txt': 'x\n'})
    assert describe_archive(text.encode('utf8')) == dev_archives.archive('tar', {'x.txt': 'x\n'})


def test_roster_is_106_with_batch_7_categories():
    ids = [t.id for t in fast12.TASKS] + [t.id for t, _ in broad_runner.task_graders()]
    assert len(ids) == len(set(ids)) == 106
    counts = Counter(dev_categories.category(i) for i in ids)
    assert counts['archives'] == 10 and counts['organise'] == 17 and counts['recovery'] == 10


def test_archive_grading_accepts_either_top_folder_layout_but_not_a_mixed_one():
    from dev.dev_archives import _flat
    with_top = dev_archives.archive('tar.gz', {'logs/a.log': 'a\n', 'logs/b.log': 'b\n'})
    without = dev_archives.archive('tar.gz', {'a.log': 'a\n', 'b.log': 'b\n'})
    mixed = dev_archives.archive('tar.gz', {'logs/a.log': 'a\n', 'b.log': 'b\n'})
    assert _flat(with_top) == _flat(without) == without
    assert _flat(mixed) == mixed != _flat(with_top)
    assert _flat('plain text\n') == 'plain text\n'
