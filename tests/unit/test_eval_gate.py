import hashlib
import json
import subprocess
import sys


def test_factory_rejects_changed_holdout_before_parsing(tmp_path):
    held = tmp_path / 'held.json'
    dev = tmp_path / 'dev.json'
    held.write_text('[]')
    pin = hashlib.sha256(held.read_bytes()).hexdigest()
    held.write_text('sensitive modified contents')
    dev.write_text('[]')
    r = subprocess.run([sys.executable, '-m', 'dev.factory', 'audit-splits', '--held-out', str(held),
                        '--manifest', str(dev), '--held-out-sha256', pin], capture_output=True, text=True)
    assert r.returncode != 0 and 'digest mismatch' in r.stdout
    assert 'sensitive' not in r.stdout + r.stderr


def test_small_holdout_cannot_pass_gate(tmp_path):
    from dev.eval_gate import verify
    held = tmp_path / 'h'
    held.write_text(json.dumps([dict(id='h', split='held-out', template_id='ht', request='q', files={})]))
    assert not verify(held, hashlib.sha256(held.read_bytes()).hexdigest(), held)['ok']


def test_ids_cannot_pad_holdout_with_identical_tasks(tmp_path):
    from dev.eval_gate import verify
    held, candidate = tmp_path / 'held', tmp_path / 'dev'
    held.write_text(json.dumps([dict(id=str(i), split='held-out', template_id=str(i),
                                     request='Read example', files={'example': 'same'}) for i in range(100)]))
    candidate.write_text(json.dumps([dict(id='d', split='dev', template_id='d',
                                          request='Count lines', files={'a.txt': 'one\ntwo', 'b.txt': 'three'})]))
    result = verify(held, hashlib.sha256(held.read_bytes()).hexdigest(), candidate)
    assert result == {'ok': False, 'reason': 'split audit detected overlap'}


def test_clean_control_and_cross_split_leak(tmp_path):
    from dev.eval_gate import verify
    def row(i, split):
        label = chr(103 + i // 10) + chr(103 + i % 10)
        return dict(id=label, split=split, request='Inspect ' + label, files={label: label}, template_id=label)
    held, candidate = tmp_path / 'held', tmp_path / 'candidate'
    held.write_text(json.dumps([row(i, 'held-out') for i in range(100)]))
    pin = hashlib.sha256(held.read_bytes()).hexdigest()
    entry = row(101, 'dev')
    candidate.write_text(json.dumps([entry]))
    assert verify(held, pin, candidate)['ok']
    entry['template_id'] = row(0, 'held-out')['template_id']
    candidate.write_text(json.dumps([entry]))
    assert verify(held, pin, candidate)['reason'] == 'split audit detected overlap'


def test_full_dev_controls_and_third_copy(tmp_path):
    from pathlib import Path
    from dev.broad_runner import development_rows
    from dev.eval_gate import verify
    held = Path(__file__).resolve().parents[2] / 'dev/holdout_manifest.json'
    pin = held.with_suffix('.sha256').read_text().split()[0]
    entries = development_rows()
    path = tmp_path / 'development.json'
    path.write_text(json.dumps(entries))
    assert verify(held, pin, path)['ok']
    entries.append(dict(entries[0], id='extra', split='train'))
    path.write_text(json.dumps(entries))
    assert not verify(held, pin, path)['ok']
