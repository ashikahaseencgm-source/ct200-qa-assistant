"""
Builds a hierarchical document tree from pdf_extractor.py's flat,
page-by-page block output, using document_tree.py's existing node
creation and validation utilities (create_node, build_tree).

STEP 3, INCREMENT 2: attaches body/list content and tables to each
heading node, in addition to the skeleton structure built in
Increment 1.

Hierarchy decision (unchanged from Increment 1): a node's level is
the number of dot-separated segments in its section number. Parent
assignment uses a stack keyed by level. See Increment 1's notes
(preserved below) for the reasoning behind this approach and why it
correctly handles the reading-order anomaly, skip-level numbering,
and duplicate heading text.

Content attachment decision (new in this increment): every non-
heading block (body or list) is attached to whichever heading node
is currently on top of the same level-stack, i.e. the most recently
seen heading in physical reading order. This is stored in a new
field, node["content_blocks"], as a flat list of blocks (NOT nested
further) in physical order. This field is additive to
document_tree.py's schema; it does not touch node["children"], which
document_tree.py's build_tree() reserves exclusively for child HEADING
nodes.

Tables are not duplicated into content_blocks. pdf_extractor.py
already matches each table to its nearest preceding heading on the
same page via nearest_heading_section (validated in Step 2). This
module reuses that match instead of re-implementing table-to-heading
logic: each node gets a node["tables"] list built by looking up, from
extracted["pages"][*]["tables"], every table whose
nearest_heading_section equals that node's section_number.

Known limitation: if a body/list block appears before any heading has
been seen in the document (stack empty), it cannot be attached to a
node. This has not occurred in either CT-200 manual (the title is
always the first block), but if it occurred, that content is
collected into the top-level "unattached_content" list in the return
value of build_document_tree(), rather than silently dropped or
incorrectly attached to the title node (the title is not a
content-bearing section).

---- Increment 1 notes (still accurate, kept for context) ----

The title has no section number and is treated as level 0, the root
of the whole tree. When processing headings in physical reading
order, any stack entries whose level is >= the new heading's level
are popped (they cannot be an ancestor of the new heading), and the
new heading's parent is whatever remains on top of the stack (or the
document root if the stack is empty). This is based on section-number
depth, not physical block adjacency, which is what makes the known
reading-order anomaly (Section 3.4 physically before 3.3) harmless,
and what makes section-numbering skip-levels (2.1.1.1 with no 2.1.1/
2.1.2) resolve correctly without inventing placeholder nodes.
Duplicate heading text (two "Error Codes" headings, sections 4.2 and
7.1) is handled naturally since each gets its own node_id and a
different parent.


As of Increment 3, content_hash is recomputed after content attachment
to reflect each node's actual content_blocks + table text (see
_recompute_content_hashes). It deliberately excludes heading text, so
it measures content change, not identity change.
"""

from pathlib import Path
import sys

from document_tree import create_node, build_tree
from pdf_extractor import extract_pdf
from document_tree import create_node, build_tree, generate_content_hash


def _heading_level(section_number: str | None) -> int:
    """Number of dot-separated segments in a section number.
    The title (section_number is None) is level 0."""
    if section_number is None:
        return 0
    return section_number.count(".") + 1


def build_document_tree(extracted: dict) -> dict:
    """
    Walk all pages' text blocks in physical reading order, build the
    heading/title skeleton (as in Increment 1), and additionally
    attach body/list blocks (content_blocks) and tables to each node.

    Returns a dict:
        {
            "roots": [...],              # root node(s), normally [title]
            "unattached_content": [...], # blocks seen before any heading
        }
    """
    nodes = []
    stack: list[tuple[int, dict]] = []
    unattached_content = []

    for page in extracted["pages"]:
        for block in page["text_blocks"]:
            if block["node_type"] in ("title", "heading"):
                level = _heading_level(block["section_number"])

                while stack and stack[-1][0] >= level:
                    stack.pop()

                parent_node = stack[-1][1] if stack else None

                node = create_node(
                    heading=block["text"],
                    body="",  # body text is tracked via content_blocks instead
                    level=level,
                    parent_id=parent_node["node_id"] if parent_node else None,
                )

                node["node_type"] = block["node_type"]
                node["page_number"] = block["page_number"]
                node["block_index"] = block["block_index"]
                node["content_blocks"] = []
                node["tables"] = []

                nodes.append(node)
                stack.append((level, node))

            elif block["node_type"] in ("body", "list"):
                if stack:
                    stack[-1][1]["content_blocks"].append(block)
                else:
                    unattached_content.append(block)

    roots = build_tree(nodes)
    _attach_tables(nodes, extracted)
    _recompute_content_hashes(roots)

    return {"roots": roots, "unattached_content": unattached_content}


def _attach_tables(nodes: list[dict], extracted: dict) -> None:
    """
    Match each table (already linked to a nearest_heading_section by
    pdf_extractor.py) to the node with that same section_number, and
    append it to that node's "tables" list. Mutates nodes in place.
    """
    nodes_by_section = {
        node["section_number"]: node
        for node in nodes
        if node["section_number"] is not None
    }

    for page in extracted["pages"]:
        for table in page["tables"]:
            section = table.get("nearest_heading_section")
            if section in nodes_by_section:
                nodes_by_section[section]["tables"].append(table)

def _flatten_table_text(table: dict) -> str:
    """Flatten a table's cell text into a single string, in row-major
    order, for content hashing purposes."""
    parts = []
    for row in table.get("rows", []):
        for cell in row:
            if cell:
                parts.append(str(cell))
    return " ".join(parts)


def _recompute_content_hashes(nodes: list[dict]) -> None:
    """
    document_tree.py's create_node() hashes the `body` parameter, which
    tree_builder.py leaves empty (content lives in content_blocks and
    tables instead, not in `body`). This pass overwrites each node's
    content_hash with a hash of its ACTUAL content: all content_blocks'
    text plus all tables' cell text, concatenated in order.

    Deliberately excludes the heading text itself -- this hash
    represents whether a section's CONTENT changed, not whether its
    heading/section-number identity changed. That distinction matters
    for version-matching in a later step: a node whose heading number
    shifts but content is identical should not look like a content
    change, and vice versa.

    Mutates nodes in place. Recurses into children.
    """
    for node in nodes:
        parts = [block["text"] for block in node.get("content_blocks", [])]
        parts.extend(_flatten_table_text(table) for table in node.get("tables", []))
        combined = " ".join(parts)
        node["content_hash"] = generate_content_hash(combined)
        _recompute_content_hashes(node["children"])


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
            f"{prefix}- [{node['node_type']}] {section} '{node['heading']}' "
            f"(page {node['page_number']}, block#{node['block_index']}) "
            f"content_blocks={len(node['content_blocks'])} "
            f"tables={len(node['tables'])} "
            f"hash={node['content_hash'][:8]}"
        )
        for content_block in node["content_blocks"]:
            kind = content_block["node_type"]
            preview = content_block["text"].replace("\n", " ")[:60]
            print(f"{prefix}    [{kind}] {preview!r}...")
        for table in node["tables"]:
            print(
                f"{prefix}    [table] {table['row_count']}x{table['col_count']} "
                f"status={table['extraction_status']}"
            )
        _print_tree(node["children"], indent + 1)


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
    else:
        pdf_path = project_root / "data" / "ct200_manual.pdf"

    extracted = extract_pdf(pdf_path)
    result = build_document_tree(extracted)
    roots = result["roots"]
    unattached = result["unattached_content"]

    print(f"File: {extracted['file_name']}")
    print(f"Root node(s): {len(roots)}")
    print(f"Total nodes (including title): {_count_nodes(roots)}")
    print(f"Unattached content blocks: {len(unattached)}")
    print()
    _print_tree(roots)

    if unattached:
        print("\nWARNING: unattached content blocks found:")
        for block in unattached:
            print(f"  page {block['page_number']} block#{block['block_index']}: "
                  f"{block['text'][:60]!r}...")