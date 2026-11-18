"""Serve a local base model, optionally with a LoRA adapter, to the guarded evaluator.

Development only; runs under the training interpreter. It implements the small subset of
Ollama's HTTP API that `dev/small_model_eval.py --backend ollama` uses (`/api/version`,
`/api/tags`, non-streaming `/api/chat`), bound to 127.0.0.1. The evaluator, the guarded MCP
server and the sandbox are unchanged; only the inference service differs. It identifies itself
in `/api/version`, and its digest covers the base config and adapter weights, so result rows
record what actually answered.

Differences from Ollama, on purpose: greedy decoding only (temperature must be 0) and no
JSON-constrained decoding; `format` is accepted and ignored. Prompts are rendered with the same
function the trainer uses (`dev.sft_pilot.prompt_ids`).
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys

from dev import sft_pilot

VERSION = "lilguy-sft-server/1 (transformers, greedy, unconstrained)"
ROLES = {"system", "user", "assistant"}
MAX_BODY = 2**20


class Engine:
    def __init__(self, model, tokenizer, *, name, digest, size, device, template_kwargs=None):
        self.model, self.tokenizer = model, tokenizer
        self.name, self.digest, self.size, self.device = name, digest, size, device
        self.template_kwargs = template_kwargs

    def version(self):
        return {"version": VERSION}

    def tags(self):
        return {"models": [{"name": self.name, "digest": self.digest, "size": self.size}]}

    def chat(self, payload):
        if payload.get("model") != self.name:
            raise ValueError("unknown model")
        if payload.get("stream"):
            raise ValueError("streaming is not supported")
        options = payload.get("options") or {}
        if options.get("temperature", 0) != 0:
            raise ValueError("only greedy decoding (temperature 0) is supported")
        messages = payload.get("messages")
        if (not isinstance(messages, list) or not messages
                or any(not isinstance(m, dict) or m.get("role") not in ROLES
                       or not isinstance(m.get("content"), str) for m in messages)):
            raise ValueError("messages must be a non-empty list of system/user/assistant turns")
        messages = [{"role": m["role"], "content": m["content"]} for m in messages]
        text = sft_pilot.complete(self.model, self.tokenizer, messages,
                                  max_new_tokens=int(options.get("num_predict", 256)),
                                  device=self.device, template_kwargs=self.template_kwargs)
        return {"model": self.name, "message": {"role": "assistant", "content": text}, "done": True}


def handler_for(engine):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 (http.server API)
            routes = {"/api/version": engine.version, "/api/tags": engine.tags}
            if self.path not in routes:
                return self._reply(404, {"error": "not found"})
            return self._reply(200, routes[self.path]())

        def do_POST(self):  # noqa: N802
            if self.path != "/api/chat":
                return self._reply(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                return self._reply(413, {"error": "request body missing or too large"})
            try:
                return self._reply(200, engine.chat(json.loads(self.rfile.read(length))))
            except (ValueError, TypeError) as exc:
                return self._reply(400, {"error": str(exc)})

        def log_message(self, format, *args):  # noqa: A002
            sys.stderr.write("[sft-server] " + (format % args) + "\n")

    return Handler


def _digest(model_dir, adapter):
    h = hashlib.sha256((model_dir / "config.json").read_bytes())
    size = sum(p.stat().st_size for p in model_dir.glob("*.safetensors"))
    if adapter is not None:
        for path in sorted(adapter.rglob("*")):
            if path.is_file():
                h.update(path.name.encode())
                h.update(path.read_bytes())
                size += path.stat().st_size
    return "sha256:" + h.hexdigest(), size


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, type=Path, help="local base model directory")
    parser.add_argument("--adapter", type=Path, help="LoRA adapter directory (omit for the base)")
    parser.add_argument("--name", required=True, help="model tag the evaluator will request")
    parser.add_argument("--port", type=int, default=11500)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--template-kwargs", default='{"enable_thinking": false}')
    args = parser.parse_args(argv)
    if not args.model.is_dir() or (args.adapter is not None and not args.adapter.is_dir()):
        parser.error("--model and --adapter must be existing local directories")

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = sft_pilot._device(args.device)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(args.model, local_files_only=True, dtype=torch.bfloat16)
    if args.adapter is not None:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
    model.to(device).eval()
    digest, size = _digest(args.model, args.adapter)
    engine = Engine(model, tokenizer, name=args.name, digest=digest, size=size, device=device,
                    template_kwargs=json.loads(args.template_kwargs))
    server = HTTPServer(("127.0.0.1", args.port), handler_for(engine))
    print(json.dumps({"listening": f"127.0.0.1:{args.port}", "name": args.name, "digest": digest}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
