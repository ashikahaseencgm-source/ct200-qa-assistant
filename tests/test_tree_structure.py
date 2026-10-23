"""
Unit tests for document tree structure, targeting known irregularities
in the CT-200 manual (documented in the project's structural map).
These are NOT generic PDF-parsing tests -- they verify specific,
manually-confirmed facts about this exact document, in both versions.
"""

from conftest import find_nodes_by_section, flatten_tree


def _check_duplicate_heading_text(tree):
    """
    'Error Codes' appears twice in the document (Section 4.2 and
    Section 7.1), with different content and different parents. The
    tree must produce two distinct nodes, not collapse them into one.
    """
    roots = tree["roots"]

    error_codes_42 = find_nodes_by_section(roots, "4.2")
    error_codes_71 = find_nodes_by_section(roots, "7.1")

    assert len(error_codes_42) == 1, "Expected exactly one node for section 4.2"
    assert len(error_codes_71) == 1, "Expected exactly one node for section 7.1"

    node_42 = error_codes_42[0]
    node_71 = error_codes_71[0]

    assert node_42["heading"].strip().endswith("Error Codes")
    assert node_71["heading"].strip().endswith("Error Codes")

    # Must be genuinely distinct nodes, not the same dict/ID reused.
    assert node_42["node_id"] != node_71["node_id"]

    # Must have different parents: 4.2's parent is section 4,
    # 7.1's parent is section 7 -- not accidentally merged.
    assert node_42["parent_id"] != node_71["parent_id"]

    all_nodes = {n["node_id"]: n for n in flatten_tree(roots)}
    parent_of_42 = all_nodes[node_42["parent_id"]]
    parent_of_71 = all_nodes[node_71["parent_id"]]

    assert parent_of_42["section_number"] == "4"
    assert parent_of_71["section_number"] == "7"


def test_duplicate_heading_text_v1(v1_tree):
    _check_duplicate_heading_text(v1_tree)


def test_duplicate_heading_text_v2(v2_tree):
    _check_duplicate_heading_text(v2_tree)


def _check_skip_level_numbering(tree):
    """
    Section 2.1.1.1 exists with no 2.1.1 or 2.1.2 siblings/ancestors
    anywhere in the document. It must nest directly under 2.1, the
    nearest actual ancestor -- not under a fabricated 2.1.1 placeholder
    node, and not directly under section 2.
    """
    roots = tree["roots"]

    battery_life_nodes = find_nodes_by_section(roots, "2.1.1.1")
    assert len(battery_life_nodes) == 1
    battery_life = battery_life_nodes[0]

    # No 2.1.1 or 2.1.2 node should exist anywhere in this document.
    assert find_nodes_by_section(roots, "2.1.1") == []
    assert find_nodes_by_section(roots, "2.1.2") == []

    all_nodes = {n["node_id"]: n for n in flatten_tree(roots)}
    parent = all_nodes[battery_life["parent_id"]]

    assert parent["section_number"] == "2.1"


def test_skip_level_numbering_v1(v1_tree):
    _check_skip_level_numbering(v1_tree)


def test_skip_level_numbering_v2(v2_tree):
    _check_skip_level_numbering(v2_tree)


def _check_title_detection(tree):
    """
    The document title has no section number and must be detected as
    a single root node of node_type 'title'. This specifically guards
    against the old, now-fixed heuristic, which structurally could
    never detect a title because it required a section number to be
    both present and absent at the same time.
    """
    roots = tree["roots"]

    assert len(roots) == 1, "Expected exactly one root node (the title)"
    title_node = roots[0]

    assert title_node["node_type"] == "title"
    assert title_node["section_number"] is None
    assert "CardioTrack" in title_node["heading"]


def test_title_detection_v1(v1_tree):
    _check_title_detection(v1_tree)


def test_title_detection_v2(v2_tree):
    _check_title_detection(v2_tree)


def _check_reading_order_anomaly(tree):
    """
    Section 3.4 'Auto Shutoff' physically appears before Section 3.3
    'Result Display and Classification' in the extracted block order,
    in both manual versions. The tree must preserve both as siblings
    under Section 3 (parenting is based on section-number depth, not
    physical adjacency) -- the anomaly must not cause either heading
    to be mis-parented, duplicated, or dropped.
    """
    roots = tree["roots"]

    section_3_nodes = find_nodes_by_section(roots, "3")
    assert len(section_3_nodes) == 1
    section_3 = section_3_nodes[0]

    child_section_numbers = [c["section_number"] for c in section_3["children"]]

    assert "3.3" in child_section_numbers
    assert "3.4" in child_section_numbers

    # Confirm the physical reading-order anomaly is still present in
    # the recorded block order: 3.4 appears before 3.3 among section
    # 3's children, exactly as pdf_extractor.py read it off the page.
    index_34 = child_section_numbers.index("3.4")
    index_33 = child_section_numbers.index("3.3")
    assert index_34 < index_33, (
        "Expected 3.4 to appear before 3.3 in physical reading order "
        "(confirmed anomaly in both CT-200 manual versions)"
    )


def test_reading_order_anomaly_v1(v1_tree):
    _check_reading_order_anomaly(v1_tree)


def test_reading_order_anomaly_v2(v2_tree):
    _check_reading_order_anomaly(v2_tree)