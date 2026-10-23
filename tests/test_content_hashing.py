"""
Unit tests for content hashing, directly protecting the version-matching
logic that Step 5 (SQLite versioning) will depend on.

content_hash is computed from each node's actual content_blocks and
tables, excluding the heading text itself (see document_tree.py). This
means two nodes with the same heading/section number should hash
identically only if their actual paragraph/list/table content matches.

These tests assert known, manually-confirmed facts about the fixed
CT-200 manual source PDFs (V1 vs V2) -- not generic hashing behavior.
"""

import pytest

from conftest import find_nodes_by_section


UNCHANGED_SECTIONS = [
    "1",
    "1.1",
    "1.2",
    "2.2",
    "3.3",
    "4.1",
    "5.1",
    "5.2",
    "6.2",
    "7.1",
    "7.2",
    "8.1",
]

CHANGED_SECTIONS = [
    "2.1.1.1",  # battery life: ~300 cycles (V1) vs ~250 cycles (V2) + added sentence
    "3.2",      # cuff inflation increment: 40 mmHg (V1) vs 30 mmHg (V2) + added sentence
    "4.2",      # error codes table: E3 time changed, E6 row added in V2
    "4.3",      # alarm thresholds: E1-E5 (V1) vs E1-E6 (V2)
]


def _get_single_node(tree, section_number):
    matches = find_nodes_by_section(tree["roots"], section_number)
    assert len(matches) == 1, (
        f"Expected exactly one node for section {section_number!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


@pytest.mark.parametrize("section_number", UNCHANGED_SECTIONS)
def test_unchanged_section_hashes_match(v1_tree, v2_tree, section_number):
    """
    These sections' text is identical between V1 and V2 (manually
    confirmed). Their content_hash must therefore match exactly --
    if this fails, either the source PDFs changed, or content_hash
    is unstable/non-deterministic, both of which would break
    Step 5's version-matching logic.
    """
    v1_node = _get_single_node(v1_tree, section_number)
    v2_node = _get_single_node(v2_tree, section_number)

    assert v1_node["content_hash"] == v2_node["content_hash"], (
        f"Section {section_number} was expected to be unchanged "
        f"between V1 and V2, but its content_hash differs."
    )


@pytest.mark.parametrize("section_number", CHANGED_SECTIONS)
def test_changed_section_hashes_differ(v1_tree, v2_tree, section_number):
    """
    These sections have manually-confirmed real text/table differences
    between V1 and V2. Their content_hash must therefore differ --
    if this fails, content_hash is not sensitive to the actual content
    change (e.g. it's only hashing the heading, or truncating content),
    which would cause Step 5's versioning to wrongly treat a changed
    node as unchanged.
    """
    v1_node = _get_single_node(v1_tree, section_number)
    v2_node = _get_single_node(v2_tree, section_number)

    assert v1_node["content_hash"] != v2_node["content_hash"], (
        f"Section {section_number} was expected to differ between "
        f"V1 and V2, but its content_hash is identical."
    )