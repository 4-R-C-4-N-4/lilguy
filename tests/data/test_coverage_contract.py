from lilguy.data.coverage import coverage


def test_implementation_toolset_shape_and_dash_flags_support_pipeline():
    toolset = {"tools": {
        "fs.grep": {"bash": {"utility": "grep", "flags": {"-i": "ignore_case"}}},
        "text.sort": {"bash": {"utility": "sort", "flags": {"-r": "reverse"}}},
        "pipe": {"stages": ["grep", "sort"]},
    }}
    result = coverage([{"source": "synthetic", "cmd": "grep -i needle file | sort -r"}], toolset)
    assert result["covered_count"] == 1


def test_pipeline_stage_must_be_in_declared_allowlist():
    toolset = {"tools": {
        "fs.grep": {"bash": {"utility": "grep", "flags": []}},
        "danger.delete": {"bash": {"utility": "rm", "flags": []}},
        "pipe": {"stages": ["grep"]},
    }, "pipe": {"stages": ["grep"]}}
    result = coverage([{"source": "synthetic", "cmd": "grep needle file | rm file"}], toolset)
    assert result["covered_count"] == 0
