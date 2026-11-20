"""Runtime parity: the evaluator's llama-server path on verified training decision prompts.

Sends each selected training prompt (all messages except the target) to a Q8_0 GGUF exactly as the
development runner does (same grammar, greedy, seed, token limit and template kwargs), and compares
the predicted action class with the HF-runtime diagnostic for the same row. Never executes actions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dev import decision_diagnose, decision_metrics
from lilguy import protocol as p


def request_body(messages, grammar):
    """Identical to the request built by dev.fast12_runner.run_model."""
    return {'messages': messages, 'grammar': grammar, 'temperature': 0, 'seed': 42, 'max_tokens': 256,
            'chat_template_kwargs': {'enable_thinking': False}}


def agreement(rows):
    """Per expected class: llama-server accuracy, HF generation accuracy and llama/HF agreement."""
    out = {}
    for cls in decision_metrics.ACTION_CLASSES:
        sub = [r for r in rows if r['class'] == cls]
        if not sub:
            continue
        both = [r for r in sub if r.get('hf') is not None]
        out[cls] = {'count': len(sub), 'server_accuracy': sum(r['server'] == cls for r in sub) / len(sub),
                    'hf_count': len(both),
                    'hf_accuracy': sum(r['hf'] == cls for r in both) / len(both) if both else None,
                    'agreement': sum(r['hf'] == r['server'] for r in both) / len(both) if both else None}
    return out


def main(argv=None):
    import urllib.request
    from dev.fast12_runner import managed_server
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('server', type=Path)
    parser.add_argument('gguf', type=Path)
    parser.add_argument('diagnostic', type=Path, help='decision_diagnose JSON for the same model')
    parser.add_argument('data', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--limit', type=int, default=0, help='first N diagnostic rows (0 = all)')
    args = parser.parse_args(argv)
    diag = json.loads(args.diagnostic.read_text())
    rows = {r['row']: r for r in decision_diagnose.verified_inputs(args.data)}
    tools = p.load_tools()
    grammar = p.grammar(tools)
    selected = diag['rows'][:args.limit or None]
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with managed_server(str(args.server), str(args.gguf), args.out) as (port, opener):
        for item in selected:
            messages = rows[item['row']]['messages']
            if messages[-1]['content'] != item['target']:
                raise ValueError(f"diagnostic row {item['row']} does not match the verified corpus")
            req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',
                                         json.dumps(request_body(messages[:-1], grammar)).encode(),
                                         {'Content-Type': 'application/json'})
            with opener.open(req, timeout=120) as response:
                reply = json.load(response)['choices'][0]['message']['content']
            results.append({'row': item['row'], 'family': item['family'], 'class': item['class'],
                            'server': decision_metrics.action_class(reply), 'server_text': reply,
                            'hf': item.get('generated'), 'teacher_correct': item['teacher_correct']})
    report = {'gguf': str(args.gguf), 'gguf_sha256': decision_diagnose.digest(args.gguf),
              'diagnostic_identity': diag['identity'], 'rows': len(results), 'by_class': agreement(results),
              'results': results}
    (args.out / 'parity.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['by_class']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
