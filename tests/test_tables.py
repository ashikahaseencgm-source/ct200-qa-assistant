"""
Unit tests for table extraction and attachment, verifying known facts
about the CT-200 manual's two tables (Section 2.1 General
Specifications, Section 4.2 Error Codes) in both V1 and V2.

Table shape, as produced by pdf_extractor.py / tree_builder.py: each
node's "tables" field is a list of dicts, each with "rows" (list of
row-lists, row 0 = header), "row_count", "col_count",
"nearest_heading_section", etc. Confirmed via direct inspection of
real extraction output for both documents.
"""

import pytest

from conftest import find_nodes_by_section


def _get_single_node(tree, section_number):
    matches = find_nodes_by_section(tree["roots"], section_number)
    assert len(matches) == 1, (
        f"Expected exactly one node for section {section_number!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _get_single_table(node):
    tables = node["tables"]
    assert len(tables) == 1, (
        f"Expected exactly one table attached to section "
        f"{node['section_number']!r}, found {len(tables)}"
    )
    return tables[0]


def _find_row_by_code(table, code):
    """Find a data row (skipping the header row) whose first cell
    matches the given error code, e.g. 'E3' or 'E6'."""
    for row in table["rows"][1:]:
        if row[0] == code:
            return row
    return None


# --- Section 2.1: General Specifications table ---

@pytest.mark.parametrize("version", ["v1", "v2"])
def test_general_specifications_table_attaches_to_2_1(v1_tree, v2_tree, version):
    tree = v1_tree if version == "v1" else v2_tree
    node = _get_single_node(tree, "2.1")
    table = _get_single_table(node)

    assert table["nearest_heading_section"] == "2.1"
    assert table["row_count"] == 8
    assert table["col_count"] == 2


def test_general_specifications_table_unchanged_v1_vs_v2(v1_tree, v2_tree):
    """
    Section 2.1's table is known to be identical in content between
    V1 and V2 -- confirmed by direct inspection of both documents'
    raw extraction output.
    """
    v1_table = _get_single_table(_get_single_node(v1_tree, "2.1"))
    v2_table = _get_single_table(_get_single_node(v2_tree, "2.1"))

    assert v1_table["rows"] == v2_table["rows"]


# --- Section 4.2: Error Codes table ---

@pytest.mark.parametrize("version", ["v1", "v2"])
def test_error_codes_table_attaches_to_4_2(v1_tree, v2_tree, version):
    tree = v1_tree if version == "v1" else v2_tree
    node = _get_single_node(tree, "4.2")
    table = _get_single_table(node)

    assert table["nearest_heading_section"] == "4.2"
    assert table["col_count"] == 3


def test_error_codes_table_row_counts_differ_v1_vs_v2(v1_tree, v2_tree):
    """
    V1's Error Codes table has 5 error rows + 1 header row = 6 total.
    V2 adds a new E6 (Bluetooth sync failure) row: 6 error rows +
    1 header row = 7 total.
    """
    v1_table = _get_single_table(_get_single_node(v1_tree, "4.2"))
    v2_table = _get_single_table(_get_single_node(v2_tree, "4.2"))

    assert v1_table["row_count"] == 6
    assert v2_table["row_count"] == 7


def test_e6_row_present_only_in_v2(v1_tree, v2_tree):
    v1_table = _get_single_table(_get_single_node(v1_tree, "4.2"))
    v2_table = _get_single_table(_get_single_node(v2_tree, "4.2"))

    assert _find_row_by_code(v1_table, "E6") is None
    e6_row_v2 = _find_row_by_code(v2_table, "E6")
    assert e6_row_v2 is not None
    assert "Bluetooth sync failure" in e6_row_v2[1]


def test_e3_row_time_differs_v1_vs_v2(v1_tree, v2_tree):
    """
    Confirmed, intentional inconsistency in the source document: E3's
    recorded auto-deflation time is '2 seconds' in V1 and '1.5
    seconds' in V2, while Section 4.1 (a separate node, covered
    elsewhere) says 'within 2 seconds' in BOTH versions. This test
    only asserts the 4.2 table value -- it must not be "corrected"
    to match 4.1.
    """
    v1_table = _get_single_table(_get_single_node(v1_tree, "4.2"))
    v2_table = _get_single_table(_get_single_node(v2_tree, "4.2"))

    e3_row_v1 = _find_row_by_code(v1_table, "E3")
    e3_row_v2 = _find_row_by_code(v2_table, "E3")

    assert e3_row_v1 is not None
    assert e3_row_v2 is not None

    assert "2 seconds" in e3_row_v1[2]
    assert "1.5 seconds" not in e3_row_v1[2]

    assert "1.5 seconds" in e3_row_v2[2]