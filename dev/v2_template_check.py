"""Chat-template parity: the trainer's prompt must be byte-identical to what llama-server renders.

Starts the pinned llama-server on a GGUF, asks it to render real multi-turn v1 conversations with
the same `chat_template_kwargs` the evaluator sends, and compares text and token ids against the
base tokenizer's rendering used by dev/v2_train.py. Exits 1 on any difference.
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

from dev import fast12_runner, v2_corpus, v2_train


def _post(opener, port, path, body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    with opener.open(req, timeout=60) as response:
        return json.load(response)


def check(base_key, base_dir, gguf, server, data, out, samples=6):
    from transformers import AutoTokenizer  # training interpreter only

    base = v2_train.check_base(base_key, base_dir)
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True)
    rows = v2_corpus.verified_rows(data)
    # The longest history plus a few first-turn rows: every assistant/observation shape appears.
    picks = sorted(rows, key=len)[-samples // 2:] + rows[:samples - samples // 2]
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with fast12_runner.managed_server(str(server), str(gguf), out) as (port, opener):
        for messages in picks:
            prompt = messages[:-1]
            ours = v2_train.render_prompt(tokenizer, prompt, base)
            theirs = _post(opener, port, '/apply-template', {
                'messages': prompt, 'chat_template_kwargs': base['template_kwargs']})['prompt']
            our_ids = tokenizer(ours, add_special_tokens=False)['input_ids']
            their_ids = _post(opener, port, '/tokenize', {'content': theirs, 'add_special': False,
                                                         'parse_special': True})['tokens']
            first = next((i for i, (a, b) in enumerate(zip(ours, theirs)) if a != b), None)
            results.append({'turns': len(prompt), 'text_equal': ours == theirs, 'ids_equal': our_ids == their_ids,
                            'first_text_difference': first, 'ours_tail': ours[-60:], 'theirs_tail': theirs[-60:]})
    report = {'base': base_key, 'gguf': str(gguf), 'ok': all(r['text_equal'] and r['ids_equal'] for r in results),
              'samples': results}
    (out / 'template-parity.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('base_key', choices=sorted(v2_train.BASES))
    parser.add_argument('base_dir', type=Path)
    parser.add_argument('gguf', type=Path)
    parser.add_argument('server', type=Path)
    parser.add_argument('data', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args(argv)
    report = check(args.base_key, args.base_dir, args.gguf, args.server, args.data, args.out)
    print(json.dumps({'base': report['base'], 'ok': report['ok'],
                      'samples': [(r['turns'], r['text_equal'], r['ids_equal']) for r in report['samples']]}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
