"""Pure-Python decision metrics for ask/done action classification.

No third-party or GPU dependencies; stdlib only.
"""

import math
from collections import Counter

ACTION_CLASSES = (
    "ask",
    "done",
    "run",
    "tool fs.list",
    "tool fs.find",
    "tool fs.read",
    "tool fs.grep",
    "tool fs.edit",
)

_ACTION_CLASS_SET = set(ACTION_CLASSES)
_PREDICTION_VALUES = _ACTION_CLASS_SET | {"invalid"}


def action_class(text: str) -> str:
    """Return the canonical action class of the first line of ``text``.

    Only leading/trailing whitespace is stripped from the first line; no
    other normalization is applied. Arbitrary prose or prefix matches are
    not accepted. Returns ``'invalid'`` when the first line is not exactly
    one of ACTION_CLASSES.
    """
    first_line = text.split("\n", 1)[0].strip()
    if first_line in _ACTION_CLASS_SET:
        return first_line
    return "invalid"


def stratified_indices(labels: list, per_class: int, seed: int) -> list:
    """Deterministically sample up to ``per_class`` indices per present class.

    Returns a sorted list of unique indices into ``labels``.
    """
    if per_class <= 0:
        raise ValueError("per_class must be > 0")

    by_class: dict = {}
    for i, label in enumerate(labels):
        by_class.setdefault(label, []).append(i)

    import random

    rng = random.Random(seed)
    selected: list = []
    for label in sorted(by_class.keys()):
        candidates = by_class[label]
        k = min(per_class, len(candidates))
        chosen = rng.sample(candidates, k)
        selected.extend(chosen)

    return sorted(set(selected))


def _empty_class_stats() -> dict:
    return {
        "count": 0,
        "decision_accuracy": None,
        "mean_decision_logprob": None,
        "mean_decision_probability": None,
        "generated_count": 0,
        "generated_accuracy": None,
    }


def summarize(records: list) -> dict:
    """Summarize teacher/generation decision records.

    Each record is a dict with:
      - "class": expected canonical action class (must be in ACTION_CLASSES)
      - "teacher_prediction": canonical class or "invalid"
      - "teacher_correct": bool, whole multi-token decision span exactness
      - "decision_logprob": float <= 0 and finite (sum of token logprobs)
      - "generated": optional canonical class/"invalid" string, or None/absent
    """
    per_class_records: dict = {cls: [] for cls in ACTION_CLASSES}
    teacher_confusion: dict = {}
    generated_confusion: dict = {}

    for record in records:
        expected = record.get("class")
        if expected not in _ACTION_CLASS_SET:
            raise ValueError(f"invalid expected class: {expected!r}")

        prediction = record.get("teacher_prediction")
        if prediction not in _PREDICTION_VALUES:
            raise ValueError(f"unknown teacher_prediction: {prediction!r}")

        correct = record.get("teacher_correct")
        if not isinstance(correct, bool):
            raise ValueError("teacher_correct must be a bool")

        logprob = record.get("decision_logprob")
        if not isinstance(logprob, (int, float)) or not math.isfinite(logprob):
            raise ValueError("decision_logprob must be finite")
        if logprob > 0:
            raise ValueError("decision_logprob must be <= 0")

        generated = record.get("generated")
        if generated is not None and generated not in _PREDICTION_VALUES:
            raise ValueError(f"unknown generated prediction: {generated!r}")

        per_class_records[expected].append(
            {
                "prediction": prediction,
                "correct": correct,
                "logprob": float(logprob),
                "generated": generated,
            }
        )

        teacher_confusion.setdefault(expected, Counter())[prediction] += 1
        if generated is not None:
            generated_confusion.setdefault(expected, Counter())[generated] += 1

    by_class: dict = {}
    total_count = 0
    for cls in ACTION_CLASSES:
        items = per_class_records[cls]
        n = len(items)
        total_count += n
        if n == 0:
            by_class[cls] = _empty_class_stats()
            continue

        correct_count = sum(1 for item in items if item["correct"])
        logprobs = [item["logprob"] for item in items]
        probabilities = [math.exp(lp) for lp in logprobs]

        generated_items = [item for item in items if item["generated"] is not None]
        n_gen = len(generated_items)
        generated_correct = sum(
            1 for item in generated_items if item["generated"] == cls
        )

        by_class[cls] = {
            "count": n,
            "decision_accuracy": correct_count / n,
            "mean_decision_logprob": sum(logprobs) / n,
            "mean_decision_probability": sum(probabilities) / n,
            "generated_count": n_gen,
            "generated_accuracy": (generated_correct / n_gen) if n_gen else None,
        }

    return {
        "count": total_count,
        "by_class": by_class,
        "teacher_confusion": {
            expected: dict(counts) for expected, counts in teacher_confusion.items()
        },
        "generated_confusion": {
            expected: dict(counts) for expected, counts in generated_confusion.items()
        },
    }
