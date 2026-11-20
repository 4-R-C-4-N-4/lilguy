import math

import pytest

from dev.decision_metrics import (
    ACTION_CLASSES,
    action_class,
    stratified_indices,
    summarize,
)


def test_generated_prediction_must_be_a_known_class_or_invalid():
    record = {'class': 'ask', 'teacher_prediction': 'ask', 'teacher_correct': True,
              'decision_logprob': -0.1, 'generated': 'asking'}
    with pytest.raises(ValueError):
        summarize([record])


def test_action_classes_contract():
    assert ACTION_CLASSES == (
        "ask",
        "done",
        "run",
        "tool fs.list",
        "tool fs.find",
        "tool fs.read",
        "tool fs.grep",
        "tool fs.edit",
    )


@pytest.mark.parametrize("cls", ACTION_CLASSES)
def test_action_class_exact_match(cls):
    assert action_class(cls) == cls


def test_action_class_strips_leading_trailing_whitespace_only():
    assert action_class("  ask  \nmore text") == "ask"
    assert action_class("  done  ") == "done"


def test_action_class_rejects_prefix_prose():
    assert action_class("ask the user something") == "invalid"
    assert action_class("I will run this") == "invalid"
    assert action_class("tool fs.list files") == "invalid"


def test_action_class_rejects_internal_whitespace_difference():
    # internal whitespace is part of the line; not normalized beyond strip
    assert action_class("tool  fs.list") == "invalid"


def test_action_class_empty_string():
    assert action_class("") == "invalid"


def test_action_class_only_first_line_considered():
    assert action_class("ask\ndone") == "ask"
    assert action_class("invalid first\nask") == "invalid"


def test_stratified_indices_basic_deterministic_balanced():
    labels = ["ask"] * 5 + ["done"] * 5 + ["run"] * 5
    idx1 = stratified_indices(labels, per_class=2, seed=42)
    idx2 = stratified_indices(labels, per_class=2, seed=42)
    assert idx1 == idx2
    assert idx1 == sorted(idx1)
    assert len(idx1) == len(set(idx1))
    # at most per_class from each present class
    from collections import Counter

    counts = Counter(labels[i] for i in idx1)
    for c in counts.values():
        assert c <= 2
    assert set(counts.keys()) <= {"ask", "done", "run"}


def test_stratified_indices_different_seed_can_differ():
    labels = ["ask"] * 10 + ["done"] * 10
    idx1 = stratified_indices(labels, per_class=3, seed=1)
    idx2 = stratified_indices(labels, per_class=3, seed=2)
    # not strictly required to differ but must both be valid
    for idx in (idx1, idx2):
        assert idx == sorted(idx)
        assert len(idx) == len(set(idx))


def test_stratified_indices_up_to_per_class_when_fewer_available():
    labels = ["ask"] * 1 + ["done"] * 5
    idx = stratified_indices(labels, per_class=3, seed=0)
    from collections import Counter

    counts = Counter(labels[i] for i in idx)
    assert counts["ask"] == 1
    assert counts["done"] == 3


def test_stratified_indices_rejects_nonpositive_per_class():
    with pytest.raises(ValueError):
        stratified_indices(["ask"], per_class=0, seed=0)
    with pytest.raises(ValueError):
        stratified_indices(["ask"], per_class=-1, seed=0)


def _rec(cls, pred, correct, logprob, generated=None):
    return {
        "class": cls,
        "teacher_prediction": pred,
        "teacher_correct": correct,
        "decision_logprob": logprob,
        "generated": generated,
    }


def test_summarize_includes_all_action_classes():
    records = [_rec("ask", "ask", True, -0.1)]
    result = summarize(records)
    assert set(result["by_class"].keys()) == set(ACTION_CLASSES)
    for cls in ACTION_CLASSES:
        if cls != "ask":
            assert result["by_class"][cls]["count"] == 0
            assert result["by_class"][cls]["decision_accuracy"] is None
            assert result["by_class"][cls]["mean_decision_logprob"] is None
            assert result["by_class"][cls]["mean_decision_probability"] is None
            assert result["by_class"][cls]["generated_count"] == 0
            assert result["by_class"][cls]["generated_accuracy"] is None


def test_summarize_basic_counts_and_accuracy():
    records = [
        _rec("ask", "ask", True, -0.2, generated="ask"),
        _rec("ask", "done", False, -1.0, generated="done"),
        _rec("done", "done", True, -0.05),
    ]
    result = summarize(records)
    assert result["count"] == 3
    ask_stats = result["by_class"]["ask"]
    assert ask_stats["count"] == 2
    assert ask_stats["decision_accuracy"] == pytest.approx(0.5)
    assert ask_stats["mean_decision_logprob"] == pytest.approx((-0.2 + -1.0) / 2)
    assert ask_stats["mean_decision_probability"] == pytest.approx(
        (math.exp(-0.2) + math.exp(-1.0)) / 2
    )
    assert ask_stats["generated_count"] == 2
    assert ask_stats["generated_accuracy"] == pytest.approx(0.5)

    done_stats = result["by_class"]["done"]
    assert done_stats["count"] == 1
    assert done_stats["decision_accuracy"] == pytest.approx(1.0)
    assert done_stats["generated_count"] == 0
    assert done_stats["generated_accuracy"] is None


def test_summarize_teacher_correct_false_despite_first_token_match():
    # multi-token decision wrong even if first token ("ask") matched;
    # teacher_correct is authoritative, independent of teacher_prediction value.
    records = [_rec("ask", "ask", False, -0.3)]
    result = summarize(records)
    assert result["by_class"]["ask"]["decision_accuracy"] == pytest.approx(0.0)


def test_summarize_generated_accuracy_denominator_excludes_missing():
    records = [
        _rec("ask", "ask", True, -0.1, generated="ask"),
        _rec("ask", "ask", True, -0.1, generated=None),
        _rec("ask", "ask", True, -0.1),  # generated key absent entirely
    ]
    result = summarize(records)
    ask_stats = result["by_class"]["ask"]
    assert ask_stats["count"] == 3
    assert ask_stats["generated_count"] == 1
    assert ask_stats["generated_accuracy"] == pytest.approx(1.0)


def test_summarize_generated_accuracy_mismatch():
    records = [
        _rec("ask", "ask", True, -0.1, generated="done"),
    ]
    result = summarize(records)
    assert result["by_class"]["ask"]["generated_accuracy"] == pytest.approx(0.0)


def test_summarize_probability_is_mean_of_exp_not_exp_of_mean():
    records = [
        _rec("ask", "ask", True, -0.1),
        _rec("ask", "ask", True, -5.0),
    ]
    result = summarize(records)
    expected_mean_prob = (math.exp(-0.1) + math.exp(-5.0)) / 2
    assert result["by_class"]["ask"]["mean_decision_probability"] == pytest.approx(
        expected_mean_prob
    )
    assert result["by_class"]["ask"]["mean_decision_probability"] != pytest.approx(
        math.exp((-0.1 + -5.0) / 2)
    )


def test_summarize_teacher_confusion_matrix():
    records = [
        _rec("ask", "ask", True, -0.1),
        _rec("ask", "done", False, -0.1),
        _rec("done", "done", True, -0.1),
    ]
    result = summarize(records)
    conf = result["teacher_confusion"]
    assert conf["ask"]["ask"] == 1
    assert conf["ask"]["done"] == 1
    assert conf["done"]["done"] == 1


def test_summarize_generated_confusion_matrix():
    records = [
        _rec("ask", "ask", True, -0.1, generated="ask"),
        _rec("ask", "ask", True, -0.1, generated="done"),
    ]
    result = summarize(records)
    conf = result["generated_confusion"]
    assert conf["ask"]["ask"] == 1
    assert conf["ask"]["done"] == 1


def test_summarize_rejects_invalid_expected_class():
    with pytest.raises(ValueError):
        summarize([_rec("not-a-class", "ask", True, -0.1)])


def test_summarize_rejects_unknown_teacher_prediction():
    with pytest.raises(ValueError):
        summarize([_rec("ask", "not-a-class-or-invalid", True, -0.1)])


def test_summarize_accepts_invalid_teacher_prediction_literal():
    # "invalid" is an allowed prediction value (teacher predicted nothing valid)
    records = [_rec("ask", "invalid", False, -0.1)]
    result = summarize(records)
    assert result["by_class"]["ask"]["count"] == 1


def test_summarize_rejects_nonfinite_logprob():
    with pytest.raises(ValueError):
        summarize([_rec("ask", "ask", True, float("nan"))])
    with pytest.raises(ValueError):
        summarize([_rec("ask", "ask", True, float("inf"))])


def test_summarize_rejects_positive_logprob():
    with pytest.raises(ValueError):
        summarize([_rec("ask", "ask", True, 0.1)])


def test_summarize_accepts_zero_logprob():
    records = [_rec("ask", "ask", True, 0.0)]
    result = summarize(records)
    assert result["by_class"]["ask"]["count"] == 1


def test_summarize_rejects_non_bool_teacher_correct():
    with pytest.raises(ValueError):
        summarize([_rec("ask", "ask", 1, -0.1)])
    with pytest.raises(ValueError):
        summarize([_rec("ask", "ask", "true", -0.1)])


def test_summarize_empty_records():
    result = summarize([])
    assert result["count"] == 0
    for cls in ACTION_CLASSES:
        stats = result["by_class"][cls]
        assert stats["count"] == 0
        assert stats["decision_accuracy"] is None
    assert result["teacher_confusion"] == {}
    assert result["generated_confusion"] == {}
