"""Offline tests for the supervised LoRA pilot.

Needs torch, transformers and PEFT, so the main gate skips them. Run them with the
training interpreter (see docs/plan/ROADMAP.md, "Training pilot").
"""
import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("peft")

from dev import sft_pilot as sp  # noqa: E402

EDIT = json.dumps({"action": "fs.edit", "arguments": {"path": "a/x.cfg", "old": "k=1\n", "new": "k=2\n"}})
ASK = json.dumps({"action": "ask", "question": "Which file should I change, a/x.cfg or b/x.cfg?"})
DONE = json.dumps({"action": "done"})


def row(user, answer, system="Return one JSON action."):
    return [{"role": "system", "content": system}, {"role": "user", "content": user},
            {"role": "assistant", "content": answer}]


TRAIN = [row("In a/x.cfg set k to 2.", EDIT), row("Set k to 2 in one file.", ASK)]
VALIDATION = [row("k is already 2 in a/x.cfg.", DONE)]


def toy_tokenizer():
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast

    alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
    tokenizer = Tokenizer(models.BPE(vocab={c: i for i, c in enumerate(alphabet)}, merges=[]))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    fast = PreTrainedTokenizerFast(tokenizer_object=tokenizer)
    fast.add_special_tokens({"eos_token": "<|end|>", "pad_token": "<|pad|>",
                             "additional_special_tokens": ["<|system|>", "<|user|>", "<|assistant|>"]})
    fast.chat_template = ("{% for m in messages %}<|{{ m.role }}|>{{ m.content }}<|end|>{% endfor %}"
                          "{% if add_generation_prompt %}<|assistant|>{% endif %}")
    return fast


def tiny_model(tokenizer):
    from transformers import LlamaConfig, LlamaForCausalLM

    torch.manual_seed(0)
    return LlamaForCausalLM(LlamaConfig(
        vocab_size=len(tokenizer), hidden_size=64, intermediate_size=128, num_hidden_layers=2,
        num_attention_heads=4, max_position_embeddings=1024, pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id, bos_token_id=None))


def write_rows(path, rows):
    path.write_text("".join(json.dumps({"messages": r}) + "\n" for r in rows))
    return path


def test_example_trains_only_on_the_answer_and_its_end_of_turn():
    tok = toy_tokenizer()
    example = sp.encode_example(tok, TRAIN[0], max_length=1024)
    prompt = sp.prompt_ids(tok, TRAIN[0][:-1])
    assert example["input_ids"][:len(prompt)] == prompt
    assert example["labels"][:len(prompt)] == [sp.IGNORE] * len(prompt)
    target = example["labels"][len(prompt):]
    assert sp.IGNORE not in target and target == example["input_ids"][len(prompt):]
    assert target[-1] == tok.eos_token_id
    assert tok.decode(target) == EDIT + tok.eos_token


def test_generation_prompt_is_the_training_prefix():
    tok = toy_tokenizer()
    text = tok.decode(sp.prompt_ids(tok, VALIDATION[0][:-1]))
    assert text.endswith("<|assistant|>") and DONE not in text


def test_overlong_example_is_refused_not_truncated():
    with pytest.raises(ValueError, match="max_length"):
        sp.encode_example(toy_tokenizer(), TRAIN[0], max_length=16)


@pytest.mark.parametrize("messages", [
    TRAIN[0][:-1],                                              # no assistant target
    TRAIN[0][:-1] + [{"role": "assistant", "content": "not json"}],
    TRAIN[0][:-1] + [{"role": "assistant", "content": "[1]"}],
    TRAIN[0][:-1] + [{"role": "assistant", "content": json.dumps({"tool": "x"})}],
    TRAIN[0] + [{"role": "user", "content": "Observation:\nexit=0"}],  # ends on a user turn
])
def test_malformed_rows_are_refused(tmp_path, messages):
    with pytest.raises(ValueError):
        sp.load_rows(write_rows(tmp_path / "rows.jsonl", [messages]))


def test_load_rows_round_trips(tmp_path):
    assert sp.load_rows(write_rows(tmp_path / "rows.jsonl", TRAIN)) == TRAIN


def test_multi_turn_rows_train_only_on_the_final_answer(tmp_path):
    tok = toy_tokenizer()
    follow_up = TRAIN[0] + [{"role": "user", "content": "Observation:\nexit=0"},
                            {"role": "assistant", "content": DONE}]
    assert sp.load_rows(write_rows(tmp_path / "rows.jsonl", [follow_up])) == [follow_up]
    example = sp.encode_example(tok, follow_up, max_length=2048)
    target = [t for t in example["labels"] if t != sp.IGNORE]
    assert tok.decode(target) == DONE + tok.eos_token


def test_validation_inputs_must_not_appear_in_training():
    leaked = row(TRAIN[1][1]["content"], DONE)  # same input, different answer
    with pytest.raises(ValueError, match="overlap"):
        sp.check_disjoint(TRAIN, [leaked])


def test_score_separates_actions_and_reports_majority_baseline():
    golds = [DONE, DONE, ASK, EDIT]
    predictions = [DONE, ASK, json.dumps({"action": "ask", "question": "Which one?"}), "garbage"]
    result = sp.score(golds, predictions)
    assert (result["n"], result["exact"], result["action_match"], result["invalid"]) == (4, 1, 2, 1)
    assert (result["majority_action"], result["majority_baseline"]) == ("done", 2)
    assert result["by_gold_action"] == {
        "ask": {"n": 1, "exact": 0, "action_match": 1},
        "done": {"n": 2, "exact": 1, "action_match": 1},
        "fs.edit": {"n": 1, "exact": 0, "action_match": 0},
    }


def test_zero_steps_leaves_base_and_tuned_identical(tmp_path):
    tok = toy_tokenizer()
    report = sp.run_pilot(tiny_model(tok), tok, TRAIN, VALIDATION, out_dir=tmp_path / "run", steps=0,
                          lr=1e-3, rank=4, target_modules=["q_proj", "v_proj"], max_length=1024,
                          max_new_tokens=8, device="cpu", seed=0)
    assert report["eval"]["base"]["predictions"] == report["eval"]["tuned"]["predictions"]


def test_short_run_learns_and_writes_adapter_and_report(tmp_path):
    # A frozen random base learns slowly through LoRA, so check what matters: after training,
    # each training input yields its own action (edit vs ask); the untrained base does not.
    tok = toy_tokenizer()
    report = sp.run_pilot(tiny_model(tok), tok, TRAIN, VALIDATION, out_dir=tmp_path / "run", steps=200,
                          lr=1e-2, rank=8, target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                                           "gate_proj", "up_proj", "down_proj"],
                          max_length=1024, max_new_tokens=20, device="cpu", seed=0)
    losses = report["train"]["losses"]
    assert len(losses) == 200 and all(map(lambda x: x == x, losses))
    assert sum(losses[-5:]) < 0.9 * sum(losses[:5])
    tuned = report["eval"]["tuned_train"]["predictions"]
    assert tuned[0].startswith('{"action": "fs.edit"') and tuned[1].startswith('{"action": "ask"')
    assert not report["eval"]["base"]["predictions"][0].startswith('{"action"')
    assert set(report["eval"]) == {"base", "tuned", "tuned_train"}
    assert report["eval"]["base"]["score"]["n"] == 1 and report["eval"]["tuned_train"]["score"]["n"] == 2
    assert report["train"]["trainable_parameters"] > 0 and report["train"]["tokens"] > 0
    assert (tmp_path / "run" / "adapter" / "adapter_config.json").is_file()
    assert json.loads((tmp_path / "run" / "report.json").read_text()) == report


def test_existing_output_directory_is_refused(tmp_path):
    tok = toy_tokenizer()
    (tmp_path / "run").mkdir()
    with pytest.raises(FileExistsError):
        sp.run_pilot(tiny_model(tok), tok, TRAIN, VALIDATION, out_dir=tmp_path / "run", steps=0,
                     lr=1e-3, rank=4, target_modules=["q_proj"], max_length=1024, max_new_tokens=4,
                     device="cpu", seed=0)


def test_decision_weight_covers_exactly_the_action_name():
    tok = toy_tokenizer()
    example = sp.encode_example(tok, TRAIN[0], max_length=1024, decision_weight=5.0)
    prompt = len(sp.prompt_ids(tok, TRAIN[0][:-1]))
    assert example["weights"][:prompt] == [0.0] * prompt
    target_ids = example["input_ids"][prompt:]
    weights = example["weights"][prompt:]
    heavy = [t for t, w in zip(target_ids, weights) if w == 5.0]
    assert tok.decode(heavy) == '{"action": "fs.edit"'
    assert set(weights) == {5.0, 1.0} and weights[-1] == 1.0  # end-of-turn weighted normally


def test_unit_decision_weight_reproduces_the_standard_loss():
    tok = toy_tokenizer()
    model = tiny_model(tok)
    example = sp.encode_example(tok, TRAIN[1], max_length=1024)
    ids, labels, weights = (torch.tensor([example[k]]) for k in ("input_ids", "labels", "weights"))
    expected = model(input_ids=ids, labels=labels).loss
    assert torch.allclose(sp.weighted_loss(model, ids, labels, weights), expected, atol=1e-5)


def test_decision_weight_refuses_targets_without_a_leading_action():
    tok = toy_tokenizer()
    odd = row("x", json.dumps({"arguments": {}, "action": "done"}))
    assert sp.encode_example(tok, odd, max_length=1024)["weights"][-1] == 1.0  # unweighted is fine
    with pytest.raises(ValueError, match="decision"):
        sp.encode_example(tok, odd, max_length=1024, decision_weight=5.0)
