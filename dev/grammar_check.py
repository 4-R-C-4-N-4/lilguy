"""Live check: does llama.cpp accept the v1 grammar, and does constrained output parse?

Development helper. Needs a running llama-server (any chat model) on 127.0.0.1:<port>.
Sends a handful of everyday requests with the v1 system prompt and grammar, then parses
each reply with lilguy.protocol. Exit 0 only if the server accepted the grammar and every
reply parsed.
"""
import json
import sys
import urllib.error
import urllib.request

from lilguy import protocol as p

REQUESTS = [
    "Show me what is in this folder.",
    "Count the lines of Python in this repo.",
    "In config/app.ini change retry=2 to retry=5.",
    "Delete the big log file.",
    "Read notes.md",
    "Find every TODO in the source.",
    "Make the scripts in bin executable.",
    "Which file here is the biggest?",
]


def main(port=11600):
    tools = p.load_tools()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    parsed = 0
    for request in REQUESTS:
        body = {"messages": [{"role": "system", "content": p.system_prompt(tools)},
                             {"role": "user", "content": request}],
                "grammar": p.grammar(tools), "temperature": 0, "max_tokens": 160,
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                     json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            reply = json.load(opener.open(req, timeout=120))["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            print("server refused:", exc.code, exc.read()[:500].decode(errors="replace"))
            return 2
        try:
            action = p.parse_action(reply, tools)
            parsed += 1
            detail = action.text if action.kind != "tool" else f"{action.tool} {action.args}"
            print(f"ok      {request[:40]:40s} -> {action.kind}: {detail[:70]!r}")
        except p.ProtocolError as exc:
            print(f"REFUSED {request[:40]:40s} -> {exc} | {reply[:100]!r}")
    print(f"{parsed}/{len(REQUESTS)} grammar-constrained replies parsed")
    return 0 if parsed == len(REQUESTS) else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 11600))
