"""Greedy coverage curve (guide §8.3): which additions to the toolset cover the most records."""
from lilguy.data.coverage import greedy_curve

RECORDS = (
    [{"cmd": "ls -l"}] * 3
    + [{"cmd": r"find . -name x -exec rm {} \;"}] * 2
    + [{"cmd": "cat a | grep b"}]
    + [{"cmd": "echo $(date)"}]          # command substitution: never coverable
    + [{"cmd": "echo hi"}]              # already covered by the base toolset
)


def test_curve_adds_the_most_valuable_set_first():
    curve = greedy_curve(RECORDS, {"echo": []}, rounds=5)
    assert curve["total_records"] == 8
    assert curve["base_covered"] == 1
    assert curve["never_coverable"] == 1
    steps = curve["steps"]
    assert steps[0]["added"] == ["flag:ls:l", "util:ls"]
    assert [s["gain"] for s in steps] == [3, 2, 1]
    assert steps[1]["added"] == ["flag:find:exec", "flag:find:name", "util:find", "util:rm"]
    assert [s["covered"] for s in steps] == [4, 6, 7]
    assert steps[-1]["covered_percent"] == 7 / 8
    assert steps[-1]["items_total"] == 2 + 4 + 2


def test_pipe_stages_are_items_when_the_toolset_has_an_allowlist():
    toolset = {"tools": {"cat": {"bash": {"utility": "cat", "flags": []}},
                         "grep": {"bash": {"utility": "grep", "flags": []}},
                         "pipe": {"stages": ["grep"]}}}
    curve = greedy_curve([{"cmd": "cat a | grep b"}], toolset, rounds=3)
    assert curve["steps"][0]["added"] == ["pipe:cat"]


def test_candidates_that_need_too_many_additions_are_skipped():
    records = [{"cmd": "tar -c -z -v -f -p -h x"}] * 5 + [{"cmd": "ls -a"}]
    curve = greedy_curve(records, {}, rounds=3, max_items=4)
    assert [s["added"] for s in curve["steps"]] == [["flag:ls:a", "util:ls"]]
    assert curve["too_large_to_add"] == 5


def test_record_needing_items_from_two_rounds_counts_once_both_are_added():
    records = [{"cmd": "ls -a"}] * 3 + [{"cmd": "ls -a -l"}]
    curve = greedy_curve(records, {}, rounds=3)
    assert [s["gain"] for s in curve["steps"]] == [3, 1]
    assert curve["steps"][1]["added"] == ["flag:ls:l"]
