"""
Unit tests for list detection in Section 3.3, verifying the numbered
list ("1. Normal... 5. Hypertensive Crisis...") is captured correctly
as a single list block with 5 merged items -- not split into separate
blocks, and not misclassified as headings despite superficially
resembling numbered section headings (heading_signals shows
"section_number" fires, but node_type is correctly "list").

Block shape, as produced by pdf_extractor.py: each content block has
"node_type" ("body" or "list"), and list blocks have "list_items" as
a list of {"number": int, "text": str} dicts. Confirmed via direct
inspection of real extraction output for both documents.
"""

import pytest

from conftest import find_nodes_by_section


EXPECTED_ITEM_TEXTS = [
    "Normal: systolic < 120 and diastolic < 80",
    "Elevated: systolic 120\u2013129 and diastolic < 80",
    "Hypertension Stage 1: systolic 130\u2013139 or diastolic 80\u201389",
    "Hypertension Stage 2: systolic \u2265 140 or diastolic \u2265 90",
    "Hypertensive Crisis: systolic > 180 or diastolic > 120 \u2014 device "
    "recommends seeking immediate medical attention",
]


def _get_single_node(tree, section_number):
    matches = find_nodes_by_section(tree["roots"], section_number)
    assert len(matches) == 1, (
        f"Expected exactly one node for section {section_number!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _get_single_list_block(node):
    list_blocks = [b for b in node["content_blocks"] if b["node_type"] == "list"]
    assert len(list_blocks) == 1, (
        f"Expected exactly one list block in section "
        f"{node['section_number']!r}, found {len(list_blocks)}"
    )
    return list_blocks[0]


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_section_3_3_has_exactly_one_list_block(v1_tree, v2_tree, version):
    tree = v1_tree if version == "v1" else v2_tree
    node = _get_single_node(tree, "3.3")
    # Will raise via the assert inside _get_single_list_block if this
    # isn't true -- calling it is itself the assertion.
    _get_single_list_block(node)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_list_has_five_items_in_order(v1_tree, v2_tree, version):
    tree = v1_tree if version == "v1" else v2_tree
    node = _get_single_node(tree, "3.3")
    list_block = _get_single_list_block(node)

    assert len(list_block["list_items"]) == 5
    numbers = [item["number"] for item in list_block["list_items"]]
    assert numbers == [1, 2, 3, 4, 5]


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_item_five_wrapped_line_merged_into_one_item(v1_tree, v2_tree, version):
    """
    Item 5's text wraps across two physical lines in the PDF
    ("...diastolic > 120 -- device" / "recommends seeking immediate
    medical attention"). It must be merged into a single list item,
    not split into a 5th and phantom 6th item.
    """
    tree = v1_tree if version == "v1" else v2_tree
    node = _get_single_node(tree, "3.3")
    list_block = _get_single_list_block(node)

    item_five = list_block["list_items"][4]
    assert item_five["number"] == 5
    assert "Hypertensive Crisis" in item_five["text"]
    assert "recommends seeking immediate medical attention" in item_five["text"]
    # The wrap join must not leave the two original lines glued
    # together without a space (e.g. "120\u2014devicerecommends").
    assert "devicerecommends" not in item_five["text"]


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_list_item_texts_match_known_content(v1_tree, v2_tree, version):
    tree = v1_tree if version == "v1" else v2_tree
    node = _get_single_node(tree, "3.3")
    list_block = _get_single_list_block(node)

    actual_texts = [item["text"] for item in list_block["list_items"]]
    assert actual_texts == EXPECTED_ITEM_TEXTS


def test_list_content_unchanged_v1_vs_v2(v1_tree, v2_tree):
    """
    This list's content is known to be identical between V1 and V2
    (confirmed by direct inspection of both documents' raw
    extraction output).
    """
    v1_list = _get_single_list_block(_get_single_node(v1_tree, "3.3"))
    v2_list = _get_single_list_block(_get_single_node(v2_tree, "3.3"))

    assert v1_list["list_items"] == v2_list["list_items"]