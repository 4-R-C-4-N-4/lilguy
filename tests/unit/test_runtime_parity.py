from dev import fast12_runner, runtime_parity


def test_parity_request_is_the_development_runner_request():
    import inspect
    source = inspect.getsource(fast12_runner.run_model)
    body = runtime_parity.request_body([{'role': 'user', 'content': 'x'}], 'G')
    assert body == {'messages': [{'role': 'user', 'content': 'x'}], 'grammar': 'G', 'temperature': 0,
                    'seed': 42, 'max_tokens': 256, 'chat_template_kwargs': {'enable_thinking': False}}
    for fragment in ('"grammar": grammar', '"temperature": 0', '"seed": 42', '"max_tokens": 256',
                     '"chat_template_kwargs": {"enable_thinking": False}'):
        assert fragment in source


def test_agreement_uses_only_rows_with_hf_generation_for_hf_rates():
    rows = [{'class': 'ask', 'server': 'ask', 'hf': 'ask'}, {'class': 'ask', 'server': 'run', 'hf': None},
            {'class': 'ask', 'server': 'run', 'hf': 'ask'}]
    result = runtime_parity.agreement(rows)['ask']
    assert result == {'count': 3, 'server_accuracy': 1 / 3, 'hf_count': 2, 'hf_accuracy': 1.0, 'agreement': 0.5}
