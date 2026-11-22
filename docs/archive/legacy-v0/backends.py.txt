"""Model backends. Stdlib only.

LlamaCpp  -> llama-server's OpenAI-compatible /v1/chat/completions, with the
             GBNF grammar passed through so output is always a valid action.
Scripted  -> replays a fixed list of actions. Validates the harness, tasks and
             checks with no model involved.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

GRAMMAR = (Path(__file__).parent / "grammar.gbnf").read_text()


class Backend:
    name = "base"

    def complete(self, system: str, prompt: str) -> str:
        raise NotImplementedError


class LlamaCpp(Backend):
    name = "llamacpp"

    def __init__(self, url: str = "http://127.0.0.1:8080", use_grammar: bool = True,
                 temperature: float = 0.0, max_tokens: int = 200, timeout: float = 120.0,
                 model: str | None = None):
        self.url = url.rstrip("/")
        self.use_grammar = use_grammar
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.model = model

    def complete(self, system: str, prompt: str) -> str:
        body = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.model:
            body["model"] = self.model
        if self.use_grammar:
            body["grammar"] = GRAMMAR
        req = urllib.request.Request(
            f"{self.url}/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"]


class Scripted(Backend):
    name = "scripted"

    def __init__(self, actions: list[dict]):
        self.actions = list(actions)
        self.i = 0

    def complete(self, system: str, prompt: str) -> str:
        if self.i >= len(self.actions):
            return json.dumps({"action": "done", "arg": "script exhausted", "expect": "ok"})
        a = self.actions[self.i]
        self.i += 1
        return json.dumps({"action": a["action"], "arg": a.get("arg", ""), "expect": a.get("expect", "ok")})
