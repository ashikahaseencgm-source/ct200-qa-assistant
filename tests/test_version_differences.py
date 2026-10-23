"""
Unit tests for structural differences between V1 and V2 of the CT-200
manual that are NOT covered by content_hashing, tables, or lists tests:
a brand-new section appearing only in V2, and a page-boundary edge
case where a section's content physically spans two pages in V2.

These assert known, manually-confirmed facts about the fixed source
PDFs (see project structural map), not generic parsing behavior.
"""

from conftest import find_nodes_by_section, flatten_tree


def test_total_node_counts(v1_tree, v2_tree):
    """
    V1 has 28 total nodes (title + 27 headings). V2 has 29 (title +
    28 headings), the +1 being the new Section 5.3 'Data Export'.
    """
    v1_total = len(flatten_tree(v1_tree["roots"]))
    v2_total = len(flatten_tree(v2_tree["roots"]))

    assert v1_total == 28
    assert v2_total == 29


def test_section_5_3_exists_only_in_v2(v1_tree, v2_tree):
    """
    Section 5.3 'Data Export' is a new section introduced in V2. It
    must not exist anywhere in V1, and must exist exactly once in V2.
    """
    v1_matches = find_nodes_by_section(v1_tree["roots"], "5.3")
    v2_matches = find_nodes_by_section(v2_tree["roots"], "5.3")

    assert v1_matches == []
    assert len(v2_matches) == 1
    assert "Data Export" in v2_matches[0]["heading"]


def test_section_5_3_nests_under_section_5_in_v2(v2_tree):
    section_5_matches = find_nodes_by_section(v2_tree["roots"], "5")
    assert len(section_5_matches) == 1
    section_5 = section_5_matches[0]

    child_section_numbers = [c["section_number"] for c in section_5["children"]]
    assert "5.3" in child_section_numbers


def test_section_8_1_spans_page_boundary_in_v2(v2_tree):
    """
    V2's page 7 is a short, near-empty page (81 characters) containing
    only the tail end of Section 8.1's text, continuing from page 6.
    This content must be merged into Section 8.1's content_blocks
    (spanning both pages 6 and 7), not dropped, and not misclassified
    as a separate/phantom node.
    """
    matches = find_nodes_by_section(v2_tree["roots"], "8.1")
    assert len(matches) == 1
    node_8_1 = matches[0]

    pages_present = {block["page_number"] for block in node_8_1["content_blocks"]}
    assert 6 in pages_present, "Expected Section 8.1 content on page 6"
    assert 7 in pages_present, (
        "Expected Section 8.1 content to continue onto page 7 "
        "(the near-empty tail page) -- it must not be dropped"
    )

    # Confirm nothing was silently lost: total content should be
    # substantially more than just the ~81-character page-7 tail,
    # proving page 6's content is also present, not overwritten.
    total_chars = sum(block["char_count"] for block in node_8_1["content_blocks"])
    assert total_chars > 100


def test_page_7_not_misclassified_as_new_node(v2_tree):
    """
    No node anywhere in the V2 tree should claim page 7 as its primary
    page_number -- confirming the near-empty page 7 was never treated
    as the start of a new section, only as a continuation.
    """
    all_nodes = flatten_tree(v2_tree["roots"])
    nodes_starting_on_page_7 = [n for n in all_nodes if n["page_number"] == 7]

    assert nodes_starting_on_page_7 == [], (
        f"Expected no node to start on page 7, but found: "
        f"{[n['section_number'] or n['heading'] for n in nodes_starting_on_page_7]}"
    )