import os
import stat

from dev import factory


def fake_server(tmp_path, listing):
    path = tmp_path / 'llama-server'
    path.write_text('#!/bin/sh\nprintf "%s\\n" "$CUDA_DEVICE_ORDER" >&2\ncat <<EOF\nAvailable devices:\n'
                    + listing + 'EOF\n')
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_single_matching_device_is_recorded(tmp_path, monkeypatch):
    monkeypatch.delenv('CUDA_DEVICE_ORDER', raising=False)
    server = fake_server(tmp_path, '  CUDA0: NVIDIA GeForce RTX 3090 (24176 MiB, 23804 MiB free)\n')
    assert factory.gpu_device(server, 'RTX 3090') == 'NVIDIA GeForce RTX 3090'
    assert os.environ['CUDA_DEVICE_ORDER'] == 'PCI_BUS_ID'


def test_wrong_or_multiple_devices_refuse(tmp_path):
    wrong = fake_server(tmp_path, '  CUDA0: NVIDIA GeForce RTX 4070 (11947 MiB, 10903 MiB free)\n')
    assert factory.gpu_device(wrong, 'RTX 3090') is None
    both = fake_server(tmp_path, '  CUDA0: NVIDIA GeForce RTX 3090 (1 MiB, 1 MiB free)\n'
                                 '  CUDA1: NVIDIA GeForce RTX 4070 (1 MiB, 1 MiB free)\n')
    assert factory.gpu_device(both, 'RTX 3090') is None
