import asyncio
import json
from dataclasses import replace

import pytest

from dev import small_model_corpus as corpus
from dev.small_model_eval import FIXTURES, PAIRED_FIXTURES


def test_deterministic_split_and_chat_export(tmp_path):
    cases = corpus.generate(42)
    assert cases == corpus.generate(42)
    assert cases != corpus.generate(43)
    assert len(cases) == 256
    assert {c.group for c in cases if c.split == "train"}.isdisjoint(
        c.group for c in cases if c.split == "validation"
    )
    output = tmp_path / "corpus"
    assert corpus.main(["--seed", "42", "--out", str(output)]) == 0
    expected = {"train": {"fs.edit": 96, "ask": 48, "done": 144},
                "validation": {"fs.edit": 32, "ask": 16, "done": 48}}
    assert json.loads((output / "manifest.json").read_text())["actions"] == expected
    for split, counts in expected.items():
        rows = [json.loads(line) for line in (output / f"{split}.jsonl").read_text().splitlines()]
        assert len(rows) == sum(counts.values())
        for row in rows:
            assert set(row) == {"messages"}
            assert row["messages"][-1]["role"] == "assistant"
            assert all(set(message) == {"role", "content"} for message in row["messages"])


def test_same_wording_asks_or_edits_depending_on_the_workspace():
    cases = corpus.generate(42)
    for ask in (c for c in cases if c.kind == "ask"):
        infer = next(c for c in cases if c.kind == "infer" and c.group == ask.group
                     and c.task == ask.task and c.order == ask.order)
        field = f"{ask.field}=".encode()
        assert sum(field in content for _, content in ask.files) == 2
        assert sum(field in content for _, content in infer.files) == 1
        assert json.loads(ask.labels[0])["action"] == "ask"
        assert json.loads(infer.labels[0])["action"] == "fs.edit"


def test_oracle_refuses_infer_and_ask_with_the_wrong_workspace(tmp_path):
    cases = corpus.generate(42)
    ask = next(c for c in cases if c.kind == "ask")
    infer = next(c for c in cases if c.kind == "infer" and c.task == ask.task and c.order == ask.order)
    for bad in (replace(infer, files=ask.files), replace(ask, files=infer.files)):
        with pytest.raises(ValueError):
            asyncio.run(corpus.verify(bad, tmp_path / "workspace"))
    assert not list(tmp_path.iterdir())


def test_after_an_edit_the_stop_row_continues_in_the_evaluator_protocol(tmp_path):
    from dev.small_model_eval import observation_message

    case = next(c for c in corpus.generate(42) if c.kind == "act")
    edit_row, done_row = asyncio.run(corpus.verify(case, tmp_path / "workspace"))
    assert json.loads(edit_row["messages"][-1]["content"])["action"] == "fs.edit"
    assert done_row["messages"][:3] == edit_row["messages"]
    assert done_row["messages"][3] == {"role": "user", "content": observation_message("exit=0\n(no output)")}
    assert json.loads(done_row["messages"][4]["content"]) == {"action": "done"}
    assert len(done_row["messages"]) == 5


def test_every_case_is_read_in_both_orders(tmp_path):
    cases = corpus.generate(42)
    forward = {c for c in cases if c.order == (0, 1)}
    backward = {replace(c, order=(0, 1)) for c in cases if c.order == (1, 0)}
    assert backward == forward and len(forward) * 2 == len(cases)
    for order in ((0, 1), (1, 0)):
        case = next(c for c in cases if c.order == order)
        (tmp_path / str(order[0])).mkdir()
        records = asyncio.run(corpus.verify(case, tmp_path / str(order[0]) / "workspace"))
        first = records[0]["messages"][1]["content"].split("Open file ")[1].split(":")[0]
        assert first == corpus.FAMILY[case.group].paths[order[0]]


def test_families_share_nothing_across_splits():
    by_split = {split: [f for f in corpus.FAMILIES if f.split == split] for split in corpus.SPLITS}
    assert len(by_split["train"]) >= 12 and len(by_split["validation"]) >= 4

    def vocabulary(families):
        return {
            "group": {f.group for f in families},
            "path": {p for f in families for p in f.paths},
            "word": {w for f in families for w in f.words},
            "setting": {name for f in families for name in (f.field, f.sibling)},
            "decoy": {f.decoy for f in families},
            "sentence": {t for f in families for t in (*f.explicit, *f.ambiguous, f.satisfied)},
        }

    train, validation = vocabulary(by_split["train"]), vocabulary(by_split["validation"])
    for key, values in train.items():
        assert values.isdisjoint(validation[key]), key
    assert len({f.group for f in corpus.FAMILIES}) == len(corpus.FAMILIES)


def test_each_family_names_targets_by_path_and_by_word():
    for family in corpus.FAMILIES:
        assert any("{path}" in t for t in family.explicit), family.group
        assert any("{word}" in t and "{path}" not in t for t in family.explicit), family.group
        assert len(set(family.words)) == 2


def test_requests_mention_exactly_their_target_and_ambiguous_ones_none():
    for case in corpus.generate(42):
        family = corpus.FAMILY[case.group]
        hits = corpus.mentioned(family, case.task)
        if case.kind in ("ask", "infer"):
            assert hits == [], case.task
        else:
            assert len(hits) == 1, case.task


def test_oracle_refuses_requests_naming_both_or_any_candidate_when_ambiguous(tmp_path):
    cases = corpus.generate(42)
    act = next(c for c in cases if c.kind == "act")
    ask = next(c for c in cases if c.kind == "ask")
    act_family, ask_family = corpus.FAMILY[act.group], corpus.FAMILY[ask.group]
    both = replace(act, task=f"{act.task} Also the {act_family.words[0]} and {act_family.words[1]} ones.")
    named = replace(ask, task=f"{ask.task} The {ask_family.words[0]} one.")
    for bad in (both, named):
        with pytest.raises(ValueError, match="intent"):
            asyncio.run(corpus.verify(bad, tmp_path / "workspace"))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("raw", [
    '{"action":"done"}',
    '{"action":"fs.edit","arguments":{"path":"elsewhere","old":"a","new":"b"}}',
    '{"action":"done","action":"fs.edit"}',
    '{"action":"fs.edit","arguments":[]}',
    '{"action":"fs.edit","arguments":{"path":true,"old":"a","new":"b"}}',
])
def test_bad_labels_fail_before_workspace_creation(tmp_path, raw):
    case = next(c for c in corpus.generate(42) if c.kind == "act")
    bad = replace(case, labels=(raw, *case.labels[1:]))
    with pytest.raises(ValueError):
        asyncio.run(corpus.verify(bad, tmp_path / "workspace"))
    assert not list(tmp_path.iterdir())


def test_ambiguous_question_must_select_between_candidates(tmp_path):
    case = next(c for c in corpus.generate(42) if c.kind == "ask")
    bad = replace(case, labels=('{"action":"ask","question":"Proceed?"}',))
    with pytest.raises(ValueError):
        asyncio.run(corpus.verify(bad, tmp_path / "workspace"))


def test_request_and_literal_mismatch_fail_before_writes(tmp_path):
    case = next(c for c in corpus.generate(42) if c.kind == "act")
    label = json.loads(case.labels[0])
    label["arguments"]["old"] = label["arguments"]["new"]
    for bad in (replace(case, task=f"Ignore this request. {case.task}"),
                replace(case, labels=(json.dumps(label), case.labels[1]))):
        with pytest.raises(ValueError):
            asyncio.run(corpus.verify(bad, tmp_path / "workspace"))
    assert not list(tmp_path.iterdir())


def test_full_snapshot_detects_mode_and_extra_effects(tmp_path, monkeypatch):
    case = next(c for c in corpus.generate(42) if c.kind == "act")
    original = corpus.offline_call

    async def polluted(workspace, name, args):
        result = await original(workspace, name, args)
        if name == "fs.edit":
            (workspace / args["path"]).chmod(0o700)
            (workspace / "extra").touch()
        return result

    monkeypatch.setattr(corpus, "offline_call", polluted)
    with pytest.raises(ValueError, match="effects"):
        asyncio.run(corpus.verify(case, tmp_path / "workspace"))


def test_duplicate_group_and_duplicate_case_rejected():
    cases = corpus.generate(42)
    with pytest.raises(ValueError):
        corpus.check_split((*cases, cases[0]))
    with pytest.raises(ValueError):
        corpus.check_split((*cases, replace(cases[0], split="validation")))


def test_guarded_selection_is_bounded_and_covers_both_splits():
    cases = corpus.guarded_sample(corpus.generate(42))
    assert len(cases) == 8
    assert {(c.split, c.kind) for c in cases} == {
        (split, kind) for split in ("train", "validation") for kind in ("act", "ask", "stop", "infer")
    }


def test_evaluation_fixtures_are_disjoint():
    cases = corpus.generate(42)
    evaluation = (*FIXTURES, *PAIRED_FIXTURES)
    assert {case.task for case in cases}.isdisjoint(fixture.task for fixture in evaluation)
    assert {path for case in cases for path, _ in case.files}.isdisjoint(
        path for fixture in evaluation for path in fixture.files
    )
    assert {content for case in cases for _, content in case.files}.isdisjoint(
        content for fixture in evaluation for content in fixture.files.values()
    )


def test_acceptance_failure_creates_no_export(tmp_path, monkeypatch):
    cases = corpus.generate(42)
    monkeypatch.setattr(corpus, "generate", lambda _: (*cases[:-1], replace(cases[-1], labels=("null",))))
    output = tmp_path / "corpus"
    with pytest.raises(ValueError, match="oracle action"):
        corpus.main(["--out", str(output)])
    assert not output.exists()


def test_system_prompt_is_shared_and_lists_tools_by_name():
    from lilguy.mcp_server import load_tools

    tools = load_tools(corpus.TOOLSET)
    text = corpus.system_prompt(tools)
    assert text.startswith("Return one JSON action for the user request.")
    positions = [text.index(f'"name": "{name}"') for name in sorted(tools)]
    assert positions == sorted(positions)
