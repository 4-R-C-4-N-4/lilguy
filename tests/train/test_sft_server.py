"""Offline tests for the adapter server's request handling (no sockets; see test_sft_pilot)."""
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")

from dev import sft_pilot as sp  # noqa: E402
from dev import sft_server as server  # noqa: E402
from tests.train.test_sft_pilot import TRAIN, tiny_model, toy_tokenizer  # noqa: E402


def engine():
    tok = toy_tokenizer()
    return server.Engine(tiny_model(tok), tok, name="lilguy-sft:test", digest="sha256:abc", size=123,
                         device="cpu"), tok


def payload(**overrides):
    body = {"model": "lilguy-sft:test", "messages": TRAIN[0][:-1], "stream": False, "format": "json",
            "think": False, "options": {"seed": 42, "temperature": 0, "num_predict": 6, "num_ctx": 4096}}
    return body | overrides


def test_identifies_itself_and_its_single_model():
    e, _ = engine()
    assert "lilguy-sft-server" in e.version()["version"]
    assert e.tags() == {"models": [{"name": "lilguy-sft:test", "digest": "sha256:abc", "size": 123}]}


def test_chat_continues_the_same_prompt_the_trainer_uses():
    e, tok = engine()
    reply = e.chat(payload())
    assert reply["message"]["role"] == "assistant" and reply["done"] is True
    expected = sp.complete(e.model, tok, TRAIN[0][:-1], max_new_tokens=6, device="cpu")
    assert reply["message"]["content"] == expected


def test_multi_turn_history_is_accepted():
    e, _ = engine()
    history = TRAIN[0][:-1] + [{"role": "assistant", "content": '{"action":"done"}'},
                               {"role": "user", "content": "Observation:\nexit=0"}]
    assert isinstance(e.chat(payload(messages=history))["message"]["content"], str)


@pytest.mark.parametrize("bad", [
    {"model": "other"},
    {"stream": True},
    {"options": {"temperature": 0.7}},
    {"messages": []},
    {"messages": [{"role": "user"}]},
    {"messages": [{"role": "tool", "content": "x"}]},
])
def test_refuses_requests_it_cannot_honour(bad):
    e, _ = engine()
    with pytest.raises(ValueError):
        e.chat(payload(**bad))
