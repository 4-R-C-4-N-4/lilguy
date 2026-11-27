"""audit_args / build_v1_tools coverage for interface v8 (fs.rename) and the fs.append
regression now that _v1_arg_types is a union over every supported interface version.
"""
from lilguy import mcp_server


def test_audit_args_fs_rename_shows_path_rule_width_redacts_glob():
    mcp_server._v1_arg_types.cache_clear()
    result = mcp_server.audit_args(
        "fs.rename", {"path": "scans", "rule": "zero_pad", "glob": "*.png", "width": 3})
    assert result == [["path", "scans"], ["rule", "zero_pad"], ["glob", "<5 chars>"], ["width", 3]]


def test_audit_args_fs_append_still_shows_path_though_v8_drops_the_tool():
    mcp_server._v1_arg_types.cache_clear()
    result = mcp_server.audit_args("fs.append", {"path": "a.txt", "lines": "x\n"})
    assert ["path", "a.txt"] in result


def test_build_v1_tools_v6_has_no_fs_rename():
    tools = mcp_server.build_v1_tools(6)
    assert "fs.rename" not in tools


def test_build_v1_tools_v8_has_fs_rename_but_not_fs_append():
    tools = mcp_server.build_v1_tools(8)
    assert "fs.rename" in tools
    assert "fs.append" not in tools
