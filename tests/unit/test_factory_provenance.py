from dev import factory


def test_candidate_identity_uses_bytes_not_filename(tmp_path):
    model = tmp_path / 'model.gguf'
    server = tmp_path / 'server'
    model.write_bytes(b'candidate one')
    server.write_bytes(b'server')
    first = factory.fast12_identity(model, server)
    model.write_bytes(b'candidate two')
    second = factory.fast12_identity(model, server)
    assert first['gguf_sha256'] != second['gguf_sha256']
    assert first['evaluation_sha256'] == second['evaluation_sha256']
    server.write_bytes(b'new runtime')
    assert second['evaluation_sha256'] != factory.fast12_identity(model, server)['evaluation_sha256']


def test_v3_oracles_are_part_of_the_evaluation_fingerprint(tmp_path):
    model, server = tmp_path / 'm.gguf', tmp_path / 'server'
    model.write_bytes(b'model')
    server.write_bytes(b'server')
    assert 'dev/oracles_v3.py' in factory.fast12_identity(model, server, interface=3)['evaluation_inputs']
