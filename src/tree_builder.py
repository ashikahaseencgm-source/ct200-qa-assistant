"""
Builds a hierarchical document tree from pdf_extractor.py's flat,
page-by-page block output, using document_tree.py's existing node
creation and validation utilities (create_node, build_tree).

STEP 3, INCREMENT 1: this builds only the title/heading skeleton.
Body text, lists, and tables are NOT yet attached to nodes -- see the
TODO at the bottom of this docstring. This increment exists to
validate tree *structure* (parent/child relationships, duplicate-
heading handling, skip-level handling) against the known CT-200
manual structural map before attaching content.

Because body is always "" at this stage, every node's content_hash
(computed by document_tree.py's create_node from the body text) will
be identical -- this is expected at this increment, not a bug.

Hierarchy decision: a node's level is the number of dot-separated
segments in its section number (e.g. "4.2" -> level 2, "2.1.1.1" ->
level 4). The title has no section number and is treated as level 0,
the root of the whole tree.

Parent assignment uses a stack keyed by level: when processing
headings in physical reading order, any stack entries whose level is
>= the new heading's level are popped (they cannot be an ancestor of
the new heading), and the new heading's parent is whatever remains on
top of the stack (or the document root if the stack is empty).

This is deliberately based on section-number depth, not on physical
block adjacency. That is what makes the known reading-order anomaly
harmless: Section 3.4 "Auto Shutoff" physically appears before
Section 3.3 "Result Display and Classification" in both CT-200
manual versions, but because both are level-2 headings under the
same still-open level-1 parent (Section 3), the stack assigns them
the same parent regardless of which is read first. The raw physical
order is NOT discarded -- it is preserved per node via page_number
and block_index -- it just does not distort the logical hierarchy.

This also handles section-numbering skip-levels for free: Section
2.1.1.1 (level 4) has no 2.1.1 or 2.1.2 siblings/ancestors. The stack
algorithm doesn't require intermediate levels to exist; it compares
only the levels actually present on the stack, so 2.1.1.1 correctly
attaches under 2.1 (the nearest actual ancestor on the stack) without
inventing a placeholder node.

Duplicate heading text (Section 4.2 "Error Codes" and Section 7.1
"Error Codes") is handled naturally: each has a different section
number, so each gets its own node_id via create_node() and ends up
with a different parent (section 4 vs section 7) -- two distinct
nodes, not one collapsed/deduplicated node.

TODO (next increment, not yet done): attach the body/list/table
blocks that follow each heading as that node's content, before
hitting the next heading. This increment stops at the skeleton
deliberately, to keep validation focused on structure alone.
"""

from pathlib import Path
import sys

from document_tree import create_node, build_tree
from pdf_extractor import extract_pdf


def _heading_level(section_number: str | None) -> int:
    """Number of dot-separated segments in a section number.
    The title (section_number is None) is level 0."""
    if section_number is None:
        return 0
    return section_number.count(".") + 1


def build_document_tree(extracted: dict) -> list[dict]:
    """
    Walk all pages' text blocks in physical reading order, collect
    title/heading blocks, and build a hierarchical tree from them
    using document_tree.py's create_node/build_tree.

    Returns the list of root nodes (normally a single root: the
    title node. If no title was detected, there could be multiple
    level-1 section nodes as roots instead -- not expected for the
    CT-200 manuals, but build_tree() supports it).
    """
    nodes = []
    # stack holds (level, node) pairs: the current path from the
    # root down to the most recently seen heading at each level.
    stack: list[tuple[int, dict]] = []

    for page in extracted["pages"]:
        for block in page["text_blocks"]:
            if block["node_type"] not in ("title", "heading"):
                continue

            level = _heading_level(block["section_number"])

            while stack and stack[-1][0] >= level:
                stack.pop()

            parent_node = stack[-1][1] if stack else None

            node = create_node(
                heading=block["text"],
                body="",  # content attachment is the next increment
                level=level,
                parent_id=parent_node["node_id"] if parent_node else None,
            )

            # Bookkeeping fields for traceability/debugging only --
            # not part of document_tree.py's validated core schema.
            node["node_type"] = block["node_type"]
            node["page_number"] = block["page_number"]
            node["block_index"] = block["block_index"]

            nodes.append(node)
            stack.append((level, node))

    return build_tree(nodes)


def _count_nodes(nodes: list[dict]) -> int:
    total = 0
    for node in nodes:
        total += 1 + _count_nodes(node["children"])
    return total


def _print_tree(nodes: list[dict], indent: int = 0) -> None:
    for node in nodes:
        prefix = "  " * indent
        section = node["section_number"] or "(no number)"
        print(
            f"{prefix}- [{node['node_type']}] {section} "
            f"'{node['heading']}' (page {node['page_number']}, "
            f"block#{node['block_index']})"
        )
        _print_tree(node["children"], indent + 1)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = project_root / "data" / "ct200_manual.pdf"

    extracted = extract_pdf(pdf_path)
    roots = build_document_tree(extracted)

    print(f"File: {extracted['file_name']}")
    print(f"Root node(s): {len(roots)}")
    print(f"Total nodes (including title): {_count_nodes(roots)}")
    print()
    _print_tree(roots)