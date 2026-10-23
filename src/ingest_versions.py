"""
Ingests both CT-200 manual PDF versions into the SQLite database:
parses each PDF, builds its document tree, stores every node, and
matches V2's nodes against V1's to detect new/changed/unchanged
sections (and reports any removed sections, though none exist in this
document's known differences).

Run from the project root:
    python src/ingest_versions.py

This is how to trigger V1 -> V2 re-ingestion for this project.

NOTE (time-pressure simplification): this script always deletes and
recreates the database file from scratch on each run, rather than
supporting incremental re-ingestion of additional future versions.
This is appropriate for this assignment's two-version demo scope, not
a production design -- see the Approach Document's Decision Log.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from pdf_extractor import extract_pdf
from tree_builder import build_document_tree
from database import DB_PATH, init_db, get_session
from models import Document, DocumentVersion, Node
from versioning import match_nodes


def flatten(nodes):
    result = []
    for n in nodes:
        result.append(n)
        result.extend(flatten(n["children"]))
    return result


def insert_version_nodes(session, version, flat_nodes, match_results=None):
    """
    Insert a flattened, pre-order list of tree nodes for one
    DocumentVersion. Because flatten() always lists a parent before
    its children, each node's parent has already been inserted (and
    its DB id recorded) by the time we reach the child.

    match_results, if given, maps this version's tree node_id (UUID)
    to {"match": old_node_dict_or_None, "status": str}; old_node_dict
    must already carry a "_db_id" key set when IT was inserted.

    Returns nothing; mutates each tree_node dict in place by adding a
    "_db_id" key, so a later call (for the next version) can use these
    nodes as match targets.
    """
    uuid_to_db_id = {}

    for tree_node in flat_nodes:
        parent_db_id = None
        if tree_node["parent_id"] is not None:
            parent_db_id = uuid_to_db_id.get(tree_node["parent_id"])

        if match_results is not None:
            result = match_results.get(tree_node["node_id"], {"match": None, "status": "new"})
            status = result["status"]
            matched_db_id = result["match"]["_db_id"] if result["match"] else None
        else:
            status = "baseline"
            matched_db_id = None

        db_node = Node(
            version_id=version.id,
            parent_id=parent_db_id,
            heading=tree_node["heading"],
            section_number=tree_node["section_number"],
            level=tree_node["level"],
            node_type=tree_node["node_type"],
            page_number=tree_node["page_number"],
            block_index=tree_node["block_index"],
            content_hash=tree_node["content_hash"],
            content_blocks_json=json.dumps(tree_node["content_blocks"], default=str),
            tables_json=json.dumps(tree_node["tables"], default=str),
            matched_node_id=matched_db_id,
            change_status=status,
        )
        session.add(db_node)
        session.flush()  # assigns db_node.id without committing yet

        uuid_to_db_id[tree_node["node_id"]] = db_node.id
        tree_node["_db_id"] = db_node.id


def main():
    if DB_PATH.exists():
        print(f"Removing existing database at {DB_PATH} for a fresh ingest...")
        DB_PATH.unlink()

    init_db()
    session = get_session()

    document = Document(name="CT-200 Manual")
    session.add(document)
    session.flush()

    print("Extracting and building tree for V1...")
    v1_extracted = extract_pdf(PROJECT_ROOT / "data" / "ct200_manual.pdf")
    v1_tree = build_document_tree(v1_extracted)
    v1_flat = flatten(v1_tree["roots"])

    v1_version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        source_filename="ct200_manual.pdf",
    )
    session.add(v1_version)
    session.flush()

    insert_version_nodes(session, v1_version, v1_flat, match_results=None)
    session.commit()
    print(f"V1 ingested: {len(v1_flat)} nodes.")

    print("Extracting and building tree for V2...")
    v2_extracted = extract_pdf(PROJECT_ROOT / "data" / "ct200_manual_v2.pdf")
    v2_tree = build_document_tree(v2_extracted)
    v2_flat = flatten(v2_tree["roots"])

    match_results = match_nodes(v1_flat, v2_flat)

    v2_version = DocumentVersion(
        document_id=document.id,
        version_number=2,
        source_filename="ct200_manual_v2.pdf",
    )
    session.add(v2_version)
    session.flush()

    insert_version_nodes(session, v2_version, v2_flat, match_results=match_results)
    session.commit()
    print(f"V2 ingested: {len(v2_flat)} nodes.")

    print("\n--- Version comparison report ---")

    new_nodes = [n for n in v2_flat if match_results[n["node_id"]]["status"] == "new"]
    changed_nodes = [n for n in v2_flat if match_results[n["node_id"]]["status"] == "changed"]
    unchanged_nodes = [n for n in v2_flat if match_results[n["node_id"]]["status"] == "unchanged"]

    matched_v1_db_ids = {
        r["match"]["_db_id"] for r in match_results.values() if r["match"] is not None
    }
    removed_nodes = [n for n in v1_flat if n["_db_id"] not in matched_v1_db_ids]

    print(f"\nNew in V2 ({len(new_nodes)}):")
    for n in new_nodes:
        print(f"  - {n['section_number'] or '(no number)'} {n['heading']}")

    print(f"\nChanged in V2 ({len(changed_nodes)}):")
    for n in changed_nodes:
        print(f"  - {n['section_number'] or '(no number)'} {n['heading']}")

    print(f"\nUnchanged: {len(unchanged_nodes)}")

    print(f"\nRemoved from V1 ({len(removed_nodes)}):")
    for n in removed_nodes:
        print(f"  - {n['section_number'] or '(no number)'} {n['heading']}")

    session.close()


if __name__ == "__main__":
    main()