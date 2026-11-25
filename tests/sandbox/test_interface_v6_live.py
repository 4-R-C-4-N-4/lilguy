"""Interface v6 live: the typed archive tools through the real guarded server.

1. The whole development roster still calibrates under v6: scripted solution passes, immediate
   `done` fails (as tests/sandbox/test_dev_v5_live.py does for v5).
2. Each new tool, scripted, reaches the expected staged effects and the same policy stops a
   shell command with the same effect would (effect-based policy, docs/plan/INTERFACE-V6.md).
"""
import pytest

from dev import broad_runner, dev_archives, dev_focus, fast12, fast12_runner as fr
from dev.dev_workspace import Task
from lilguy import protocol

pytestmark = pytest.mark.sandbox

V6 = 6
ROSTER = [(task, fast12.grade, None, None) for task in fast12.TASKS] + \
    [(task, grade, None, None) for task, grade in broad_runner.task_graders()] + \
    [(task, dev_focus.grade, dev_focus.ASK, dev_focus.ORACLES) for task in dev_focus.TASKS]


@pytest.mark.parametrize('task,grade,ask_ids,oracles', ROSTER, ids=[row[0].id for row in ROSTER])
def test_v6_controls(tmp_path, task, grade, ask_ids, oracles):
    tools = protocol.load_tools(version=V6)
    task = fr.oracle_for(task, V6, oracles)
    mode = fr.task_mode(task, V6, ask_ids)
    oracle = fr.run_oracle(tmp_path / 'oracle', task, tools, grade, version=V6, mode=mode)
    assert oracle['infra_error'] is None and oracle['terminal'] == 'done' and oracle['answer'] == ''
    scored = fr.interface_grade(grade, answer_required=fr.answer_required(oracle), version=V6)
    failures = list(scored(task, terminal=oracle['terminal'], answer=oracle['answer'], changes=oracle['changes'],
                           events=fr._events(oracle), original_unchanged=oracle['original_unchanged']))
    assert failures == [], (failures, fr.quote_text(fr._events(oracle), task.files))
    null = fr.run_false_done(tmp_path / 'null', task, tools, scored, version=V6, mode=mode)
    assert null['infra_error'] is None and null['failures'], null


_SETTINGS = dev_archives.tar_fixture({'config.ini': 'volume=9\n', 'colors.ini': 'accent=teal\n'})
_SITE = dev_archives.tar_fixture({'site/index.html': '<h1>Welcome</h1>\n', 'site/about.html': '<p>Since 1998</p>\n'})

# (task, expected final policy). Scripted with the new tools only; graded like the archive batch.
TOOL_CASES = [
    (Task('v6_pack_exclude', 'Pack notes/ into notes.tar.gz without .tmp files.',
          {'notes/a.txt': 'a\n', 'notes/s.tmp': 't\n'},
          ('tool archive.pack\narchive: notes.tar.gz\nsource: notes\nexclude: *.tmp', 'done'),
          {'notes.tar.gz': dev_archives.archive('tar.gz', {'notes/a.txt': 'a\n'})}), 'ok'),
    (Task('v6_gzip_keep', 'Gzip server.log, keeping it.', {'server.log': 'up\n'},
          ('tool archive.pack\narchive: server.log.gz\nsource: server.log', 'done'),
          {'server.log.gz': dev_archives.gzipped('up\n')}), 'ok'),
    (Task('v6_unpack_keep_existing', 'Unpack settings.tar here without overwriting.',
          {'settings.tar': _SETTINGS, 'config.ini': 'volume=3\n'},
          ('tool archive.unpack\narchive: settings.tar', 'done'),
          {'colors.ini': 'accent=teal\n'}), 'ok'),
    (Task('v6_unpack_one_member', 'Take only colors.ini out of settings.tar into out/.',
          {'settings.tar': _SETTINGS},
          ('tool archive.unpack\narchive: settings.tar\ninto: out\nmember: colors.ini', 'done'),
          {'out': '<dir added>', 'out/colors.ini': 'accent=teal\n'}), 'ok'),
    (Task('v6_add_to_tar', 'Add extra.txt to settings.tar.',
          {'settings.tar': _SETTINGS, 'extra.txt': 'e\n'},
          ('tool archive.add\narchive: settings.tar\nsource: extra.txt', 'done'),
          {'settings.tar': dev_archives.archive('tar', {'config.ini': 'volume=9\n', 'colors.ini': 'accent=teal\n',
                                                        'extra.txt': 'e\n'})}), 'ok'),
]


@pytest.mark.parametrize('task,policy', TOOL_CASES, ids=[t.id for t, _ in TOOL_CASES])
def test_v6_tools_reach_their_effects_under_the_same_policy(tmp_path, task, policy):
    tools = protocol.load_tools(version=V6)
    record = fr.run_oracle(tmp_path / 'oracle', task, tools, dev_archives.grade, version=V6, mode='do')
    assert record['infra_error'] is None, record
    assert record['changes'] == task.changes, record
    assert record['original_unchanged'] is True
    last = record['events'][-1]['observation']
    assert last.rstrip().endswith(f'policy: {policy}') or f'policy: {policy}' in last, last


def test_v6_compare_works_in_question_mode_and_packing_is_refused_there(tmp_path):
    tools = protocol.load_tools(version=V6)
    site = {'backup.tar': _SITE, 'site/index.html': '<h1>Welcome back</h1>\n', 'site/about.html': '<p>Since 1998</p>\n'}
    ask = Task('v6_compare', 'Does backup.tar match site/?', site,
               ('tool archive.list\npath: backup.tar\ncompare: true', 'done'))
    record = fr.run_oracle(tmp_path / 'ask', ask, tools, dev_archives.grade, version=V6, mode='ask')
    out = record['events'][-1]['observation']
    assert 'site/index.html differs' in out and 'site/about.html same' in out and 'policy: ok' in out
    pack = Task('v6_pack_in_ask', 'Pack site/.', site, ('tool archive.pack\narchive: s.tar\nsource: site', 'done'))
    record = fr.run_oracle(tmp_path / 'pack', pack, tools, dev_archives.grade, version=V6, mode='ask')
    assert 'policy: rejected' in record['events'][-1]['observation'] and record['changes'] == {}
