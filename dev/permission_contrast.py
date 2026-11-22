"""Inference only: vary requested permissions in one recorded development prefix."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request

from dev.factory import gpu_device
from dev.fast12_runner import managed_server
from dev.runtime_parity import request_body
from lilguy import protocol as p


MODES = {'600': 'owner-readable and owner-writable only', '640': 'readable and writable by its owner, readable by its group, and inaccessible to everyone else', '644': 'readable and writable by its owner and read-only for group and others', '660': 'readable and writable by owner and group only', '664': 'readable and writable by owner and group, and read-only for others'}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('assessment', type=Path)
    args = cli.parse_args()
    src = args.assessment
    server = Path.home()/'programs/llama.cpp/build/bin/llama-server'
    if not gpu_device(server, 'RTX 3090'):
        raise ValueError('expected the 3090 only')
    info = json.loads((src/'assessment.json').read_text())
    prefix, = [r['messages'] for line in (src/'prefixes.jsonl').read_text().splitlines() if
               (r := json.loads(line))['task'] == 'restrict_local_draft_mode' and r['source'] == 'control' and r['turn'] == 1]
    phrase = MODES['600']
    assert prefix[1]['content'].count(phrase) == 1
    grammar = p.grammar(p.load_tools(), 3)
    out = Path(tempfile.mkdtemp(prefix='permission-contrast-', dir=src))
    for label, side, artifact in [('stock','control','stock'), ('control','control','tuned'), ('treatment','treatment','tuned')]:
        gguf = src.parent/side/'minicpm'/f'{artifact}-q8_0.gguf'
        with gguf.open('rb') as f:
            digest = hashlib.file_digest(f,'sha256').hexdigest()
        assert digest == info['summaries'][label]['gguf_sha256']
        dest = out/label
        dest.mkdir()
        rows = []
        with managed_server(str(server), str(gguf.resolve()), dest) as (port, opener):
            for mode,words in MODES.items():
                for form,text in [('words',words), ('octal',f'have exactly octal file mode {mode}')]:
                    messages = [dict(m) for m in prefix]
                    messages[1]['content'] = messages[1]['content'].replace(phrase, text if form=='words' else 'use octal mode '+mode)
                    if form=='octal':
                        messages[1]['content'] = f'Request: Set handout-draft.txt to octal mode {mode}. Do not change its contents or the public handout.'
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',json.dumps(request_body(messages, grammar)).encode(),{'Content-Type':'application/json'})
                    with opener.open(req, timeout=90) as resp:
                        reply = json.load(resp)['choices'][0]['message']['content']
                    rows.append(dict(mode=mode,form=form,request=messages[1]['content'],reply=reply,artifact=digest))
        (dest/'responses.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
