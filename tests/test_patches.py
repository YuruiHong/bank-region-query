"""Tests for the patch layer (patches.txt on top of bank_region_codes.json).

Patches are '银行 地区码 地区' triples with optional '# ...' notes; the notes
must stay in the patch file and never reach the data or any output.
"""

import json

import pytest

from bank_region_query import BankRegionQuery


@pytest.fixture
def patched(tmp_path):
    """Build a BankRegionQuery whose patch file holds the given content."""
    def _make(content):
        path = tmp_path / "patches.txt"
        path.write_text(content, encoding="utf-8")
        return BankRegionQuery(patch_file=str(path))
    return _make


@pytest.fixture
def unpatched(tmp_path):
    """A query with an empty patch file, i.e. the pristine bundled data."""
    path = tmp_path / "patches.txt"
    path.write_text("", encoding="utf-8")
    return BankRegionQuery(patch_file=str(path))


def test_patch_adds_mapping_both_directions(patched):
    q = patched("农行 407 亳州 # 261020点询亳州分行营业部确认\n")
    assert q.get_region_by_code("农行", "=407").data == "亳州"
    assert q.get_region_code("农行", "=亳州").data == "407"


def test_unpatched_data_has_no_亳州_for_农行(unpatched):
    assert unpatched.get_region_code("农行", "=亳州").success is False


def test_comment_never_enters_data_or_listing(patched):
    note = "261020点询亳州分行营业部确认"
    q = patched(f"农行 407 亳州 # {note}\n")
    assert note not in json.dumps(q.data, ensure_ascii=False)
    assert q.list_patches().data == [
        {"bank": "中国农业银行", "code": "407", "region": "亳州"}
    ]


def test_alias_resolution_does_not_touch_other_banks(patched):
    # 农行 is an alias of 中国农业银行; 交通银行 keeps its own 407 = 滨州市
    q = patched("农行 407 亳州\n")
    assert q.get_region_by_code("交通银行", "=407").data == "滨州市"


def test_patch_overrides_existing_mapping(patched, capsys):
    q = patched("交通 407 亳州\n")  # 交通银行 407 was 滨州市
    assert q.get_region_by_code("交通银行", "=407").data == "亳州"
    # the old region no longer claims the code
    assert "滨州市" not in q.data["交通银行"]["region_to_code"]
    assert "overrides" in capsys.readouterr().err


def test_patch_appends_second_code_to_region(patched):
    q = patched("农行 999 杭州市\n")  # 杭州市 was "032,萧山227"
    assert q.data["中国农业银行"]["region_to_code"]["杭州市"] == "032,萧山227,999"
    assert q.data["中国农业银行"]["code_to_region"]["999"] == "杭州市"


def test_malformed_and_ambiguous_lines_are_skipped(patched, capsys):
    q = patched(
        "\n"
        "# comment-only line\n"
        "农行 407\n"          # two fields
        "商银行 407 亳州\n"   # ambiguous: 工商/招商/浙商
        "农行 407 亳州 # ok\n"
    )
    assert q.list_patches().data == [
        {"bank": "中国农业银行", "code": "407", "region": "亳州"}
    ]
    err = capsys.readouterr().err
    assert "expected '银行 地区码 地区'" in err
    assert "does not resolve" in err


def test_stats_counts_patches(patched):
    q = patched("农行 407 亳州\n农行 408 亳州\n")
    assert q.get_statistics()["total_patches"] == 2


def test_bundled_patch_file_loads_by_default():
    q = BankRegionQuery()
    assert {"bank": "中国农业银行", "code": "407", "region": "亳州"} in q.list_patches().data


def test_explicit_missing_patch_file_warns(capsys):
    BankRegionQuery(patch_file="/nonexistent/patches.txt")
    assert "not found" in capsys.readouterr().err
