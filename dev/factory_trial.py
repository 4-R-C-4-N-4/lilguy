"""One disposable development task against a local GGUF; not a held-out benchmark."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from lilguy import protocol as p
from lilguy.sandbox import layers, persist
from lilguy.sandbox.diff import session_diff


async def episode(port, root, opener):
    ws = root / 'work'
    state = root / 'state'
    ws.mkdir()
    note = ws / 'notes.txt'
    note.write_text('status: draft\n')
    tools = p.load_tools()
    messages = [{'role': 'system', 'content': p.system_prompt(tools)}, {'role': 'user', 'content':
                'In notes.txt change status: draft to status: ready. Check the result.'}]
    params = StdioServerParameters(command=sys.executable, env={k: os.environ[k] for k in
        ('XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS') if k in os.environ}, args=['-m', 'lilguy.mcp_server',
        '--workspace', str(ws), '--state-dir', str(state), '--toolset', str(p.TOOLSET), '--interface-v1'])
    terminal = 'budget'
    async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
        await client.initialize()
        for _ in range(6):
            body = {'messages': messages, 'grammar': p.grammar(tools), 'temperature': 0, 'seed': 42,
                    'max_tokens': 128, 'chat_template_kwargs': {'enable_thinking': False}}
            req = urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions', json.dumps(body).encode(),
                                         {'Content-Type': 'application/json'})
            with opener.open(req, timeout=90) as response:
                reply = json.load(response)['choices'][0]['message']['content']
            messages.append({'role': 'assistant', 'content': reply})
            try:
                action = p.parse_action(reply, tools)
            except p.ProtocolError:
                terminal = 'invalid'
                break
            if action.kind in ('ask', 'done'):
                terminal = action.kind
                break
            result = await client.call_tool(action.tool or 'run', action.args if action.tool else {'command': action.text})
            text = result.content[0].text
            messages.append({'role': 'user', 'content': p.observation_message(text)})
            if result.isError:
                terminal = 'tool-error'
                break
    unchanged = note.read_bytes() == b'status: draft\n' and set(ws.iterdir()) == {note}
    sessions = list(state.glob('*/progress.json'))
    correct = False
    if len(sessions) == 1:
        session = persist.load_session(sessions[0].parent)
        target = layers.resolve(session, 'notes.txt')
        changes = [(e.op, e.path) for e in session_diff(session)]
        correct = bool(changes == [('modified', 'notes.txt')] and target and not target.is_symlink() and target.is_file() and target.stat().st_size == 14
                       and target.read_bytes() == b'status: ready\n')
    return {'task': 'dev-notes-status', 'terminal': terminal, 'original_unchanged': unchanged,
            'target_bytes_correct': correct, 'passed': unchanged and correct and terminal == 'done', 'turns': messages}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('server')
    ap.add_argument('gguf')
    ap.add_argument('out', type=Path)
    args = ap.parse_args()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (args.out / 'server.log').open('w') as log, tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen([args.server, '-m', args.gguf, '--host', '127.0.0.1', '--port', str(port),
                                 '-c', '4096', '-np', '1'], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            while proc.poll() is None and time.monotonic() < deadline:
                try:
                    with opener.open(f'http://127.0.0.1:{port}/health', timeout=1) as r:
                        if json.load(r).get('status') == 'ok':
                            break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError('llama-server failed to start; see server.log')
            result = asyncio.run(episode(port, Path(tmp), opener))
            (args.out / 'trial.json').write_text(json.dumps(result, indent=2) + '\n')
            print({k:v for k,v in result.items() if k != 'turns'})
            return 0 if result['passed'] else 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == '__main__':
    raise SystemExit(main())
