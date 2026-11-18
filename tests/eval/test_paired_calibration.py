import asyncio
import json

import pytest

from dev.small_model_eval import Effects, PAIRED_FIXTURES, grade, main, oracle_case


@pytest.mark.parametrize("fixture", PAIRED_FIXTURES, ids=lambda fixture: fixture.id)
def test_paired_oracle_is_deterministic(fixture):
    result = asyncio.run(oracle_case(fixture, "open", "neutral", 8))
    assert result == asyncio.run(oracle_case(fixture, "open", "neutral", 8))
    assert result["pass"]
    assert result["termination"] == ("done" if fixture.target else "ask")
    assert result["write_attempts"] == bool(fixture.target)
    if fixture.target:
        assert result["trace"][0]["arguments"]["path"] == fixture.target
        assert fixture.target in fixture.task
    else:
        assert all(path not in fixture.task for path in fixture.paths)


def test_paired_cli_and_prompt_controls(tmp_path):
    output = tmp_path / "paired.jsonl"
    assert main(["--suite", "paired", "--out", str(output)]) == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 4
    assert len({row["pair"] for row in rows}) == 2
    assert {row["context"] for row in rows} == {"open"}
    assert {row["formatting"] for row in rows} == {"neutral"}
    for explicit, ambiguous in zip(rows[::2], rows[1::2], strict=True):
        assert explicit["pair"] == ambiguous["pair"]
        assert (explicit["variant"], ambiguous["variant"]) == ("explicit", "ambiguous")
        first, second = explicit["initial_messages"], ambiguous["initial_messages"]
        assert first[0] == second[0]
        first_task, first_context = first[1]["content"].split("\n\n", 1)
        second_task, second_context = second[1]["content"].split("\n\n", 1)
        assert first_task != second_task
        assert first_context == second_context
        assert first_context.count("Open file ") == 2


@pytest.mark.parametrize(
    "explicit,ambiguous", list(zip(PAIRED_FIXTURES[::2], PAIRED_FIXTURES[1::2], strict=True)),
)
def test_paired_fixture_grading(explicit, ambiguous):
    assert explicit.paths == ambiguous.paths
    assert explicit.files == ambiguous.files
    assert set(explicit.paths) == set(explicit.files)
    assert len(explicit.paths) == 2
    assert all(content.count(explicit.old.encode()) == 1 for content in explicit.files.values())
    clean = Effects((), None, True, False)
    exact = Effects(explicit.expected_entries, explicit.expected_bytes, True, False)
    other = next(path for path in explicit.paths if path != explicit.target)
    wrong = exact._replace(entries=(("modified", other, "file"),))
    choices = " or ".join(path.split("/")[0] for path in ambiguous.paths)
    ask = {"action": "ask", "question": f"Should I use {choices}?"}
    done = {"action": "done"}
    assert grade(explicit, [done], exact)["pass"]
    assert not grade(explicit, [done], wrong)["pass"]
    assert not grade(explicit, [done], exact._replace(staged=b"wrong bytes"))["pass"]
    assert not grade(explicit, [done], clean)["pass"]
    assert not grade(explicit, [ask], clean)["pass"]
    assert grade(ambiguous, [ask], clean)["pass"]
    assert not grade(ambiguous, [done], clean)["pass"]
    assert not grade(ambiguous, [ask], exact)["pass"]
    assert not grade(ambiguous, [{"action": "fs.edit"}, ask], clean)["pass"]
    assert not grade(ambiguous, [{"action": "ask", "question": "Which value?"}], clean)["pass"]
