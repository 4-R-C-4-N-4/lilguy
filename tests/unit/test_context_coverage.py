from dev import context_coverage as cc


def test_missing_path_ignores_existing_files_and_nested_basenames():
    assert cc.names_missing_path('Copy a.txt into out.txt.', {'a.txt': 'x'})
    assert not cc.names_missing_path('Read notes.md.', {'docs/notes.md': 'x'})
    assert not cc.names_missing_path('List the folder.', {'a.txt': 'x'})


def test_targets_after_not_found_count_only_rows_following_a_missing_path():
    def row(observation, target):
        return [{'content': 's'}, {'content': 'u'}, {'content': 'tool fs.read\npath: x'},
                {'content': observation}, {'content': target}]
    rows = [row('exit=1\nstderr (1 lines):\n  Path does not exist', 'tool fs.find\nname_glob: x'),
            row('exit=0\nstdout (1 lines):\n  x', 'done\nok')]
    assert cc.after_not_found(rows) == {'tool fs.find': 1}
