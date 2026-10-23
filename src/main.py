"""
FastAPI application for the CT-200 QA Assistant.

Endpoints:
  Browse:
    GET  /documents
    GET  /documents/{document_id}/versions
    GET  /versions/{version_id}/tree
    GET  /nodes/{node_id}
    GET  /nodes/{node_id}/diff
    GET  /search

  Selection (version-pinned: each node_id in a selection refers to
  one specific version's row, so a selection never silently shifts
  versions):
    POST /selections
    GET  /selections/{selection_id}

  Test-case generation (Gemini LLM, structured output + retry --
  see llm_client.py):
    POST /selections/{selection_id}/test-cases

  Retrieval (previously generated test cases):
    GET  /selections/{selection_id}/test-cases

  Staleness / impact detection:
    GET  /selections/{selection_id}/staleness

Run with (from project root):
    uvicorn main:app --reload --app-dir src
"""

import difflib
import json
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import get_session, init_db
from models import Document, DocumentVersion, Node, Selection, SelectionNode
from schemas import SelectionCreate, SelectionOut, SelectionNodeOut, StalenessResult, NodeStaleness
from llm_client import generate_test_cases, LLMGenerationError
import nosql_store

app = FastAPI(title="CT-200 QA Assistant")


def _node_content_text(node: Node) -> str:
    """Flatten a node's content_blocks and tables into plain text for LLM prompting."""
    blocks = json.loads(node.content_blocks_json)
    parts = [b["text"] for b in blocks if b.get("text")]
    tables = json.loads(node.tables_json)
    for t in tables:
        rows_text = "\n".join(" | ".join(row) for row in t["rows"])
        parts.append(rows_text)
    return "\n\n".join(parts)


def _normalize_for_search(text: str) -> str:
    """
    PyMuPDF extracts certain fonts' multi-letter ligature glyphs as
    single Unicode ligature characters (confirmed via direct
    inspection: U+FB00 "ff", U+FB02 "fl", also U+FB01 "fi" appears
    in "Specifications" elsewhere in this document). A user typing
    plain "cuff" or "inflation" into search would otherwise get zero
    matches against headings containing these ligature characters,
    since the ligature is a different code point than its expanded
    ASCII letters. Normalized only at the search-matching layer, not
    applied to stored data.
    """
    text = text.replace("\ufb00", "ff")   # ﬀ
    text = text.replace("\ufb01", "fi")   # ﬁ
    text = text.replace("\ufb02", "fl")   # ﬂ
    text = text.replace("\ufb03", "ffi")  # ﬃ
    text = text.replace("\ufb04", "ffl")  # ﬄ
    return text.lower()



def _node_to_dict(node: Node) -> dict:
    return {
        "id": node.id,
        "heading": node.heading,
        "section_number": node.section_number,
        "level": node.level,
        "node_type": node.node_type,
        "page_number": node.page_number,
        "content_hash": node.content_hash,
        "change_status": node.change_status,
        "matched_node_id": node.matched_node_id,
    }


def _build_tree(nodes: list[Node]) -> list[dict]:
    by_id = {n.id: {**_node_to_dict(n), "children": []} for n in nodes}
    roots = []
    for n in nodes:
        entry = by_id[n.id]
        if n.parent_id is not None and n.parent_id in by_id:
            by_id[n.parent_id]["children"].append(entry)
        else:
            roots.append(entry)
    return roots


def _lightweight_diff(old_text: str, new_text: str) -> str:
    diff_lines = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), lineterm="", n=1))
    return "\n".join(diff_lines[:20]) if diff_lines else "(no line-level differences detected)"


@app.on_event("startup")
def on_startup():
    # Does NOT re-ingest or wipe data; just ensures tables exist if
    # the API is started before ever running ingest_versions.py.
    init_db()


# ---------- Browse API ----------

@app.get("/documents")
def list_documents():
    session: Session = get_session()
    try:
        docs = session.query(Document).all()
        return [{"id": d.id, "name": d.name} for d in docs]
    finally:
        session.close()


@app.get("/documents/{document_id}/versions")
def list_versions(document_id: int):
    session: Session = get_session()
    try:
        versions = (
            session.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)
            .all()
        )
        if not versions:
            raise HTTPException(status_code=404, detail="No versions found for this document")
        return [
            {"id": v.id, "version_number": v.version_number, "source_filename": v.source_filename}
            for v in versions
        ]
    finally:
        session.close()


@app.get("/versions/{version_id}/tree")
def get_version_tree(version_id: int):
    session: Session = get_session()
    try:
        nodes = session.query(Node).filter(Node.version_id == version_id).all()
        if not nodes:
            raise HTTPException(status_code=404, detail="No nodes found for this version")
        return {"version_id": version_id, "roots": _build_tree(nodes)}
    finally:
        session.close()


@app.get("/nodes/{node_id}")
def get_node(node_id: int):
    session: Session = get_session()
    try:
        node = session.get(Node, node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        result = _node_to_dict(node)
        result["content_blocks"] = json.loads(node.content_blocks_json)
        result["tables"] = json.loads(node.tables_json)
        return result
    finally:
        session.close()


@app.get("/nodes/{node_id}/diff")
def get_node_diff(node_id: int):
    session: Session = get_session()
    try:
        node = session.get(Node, node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        version = session.get(DocumentVersion, node.version_id)

        if node.change_status in ("changed", "unchanged", "new"):
            if node.change_status == "new":
                return {
                    "node_id": node.id, "heading": node.heading, "version_number": version.version_number,
                    "has_changed": True, "detail": "New in this version; no prior version to compare.",
                    "diff": None,
                }

            old_node = session.get(Node, node.matched_node_id) if node.matched_node_id else None
            has_changed = node.change_status == "changed"
            diff_summary = (
                _lightweight_diff(_node_content_text(old_node), _node_content_text(node))
                if (has_changed and old_node) else None
            )
            return {
                "node_id": node.id, "heading": node.heading, "version_number": version.version_number,
                "has_changed": has_changed,
                "detail": "Content changed relative to prior version." if has_changed else "Unchanged relative to prior version.",
                "diff": diff_summary,
            }

        later_versions = (
            session.query(DocumentVersion)
            .filter(
                DocumentVersion.document_id == version.document_id,
                DocumentVersion.version_number > version.version_number,
            )
            .order_by(DocumentVersion.version_number)
            .all()
        )
        if not later_versions:
            return {
                "node_id": node.id, "heading": node.heading, "version_number": version.version_number,
                "has_changed": False, "detail": "No newer document version exists.", "diff": None,
            }

        latest_version = later_versions[-1]
        matched = (
            session.query(Node)
            .filter(Node.version_id == latest_version.id, Node.matched_node_id == node.id)
            .first()
        )
        if matched is None:
            return {
                "node_id": node.id, "heading": node.heading, "version_number": version.version_number,
                "has_changed": True, "detail": f"Removed by version {latest_version.version_number}.",
                "diff": None,
            }

        has_changed = matched.content_hash != node.content_hash
        diff_summary = (
            _lightweight_diff(_node_content_text(node), _node_content_text(matched)) if has_changed else None
        )
        return {
            "node_id": node.id, "heading": node.heading, "version_number": version.version_number,
            "has_changed": has_changed,
            "detail": f"Changed in version {latest_version.version_number}." if has_changed else "Unchanged.",
            "diff": diff_summary,
        }
    finally:
        session.close()


@app.get("/search")
def search_nodes(q: str, version_id: Optional[int] = None):
    session: Session = get_session()
    try:
        query = session.query(Node)
        if version_id is not None:
            query = query.filter(Node.version_id == version_id)
        nodes = query.all()

        q_norm = _normalize_for_search(q)
        results = []
        for node in nodes:
            heading_norm = _normalize_for_search(node.heading or "")
            body_norm = _normalize_for_search(_node_content_text(node))
            heading_match = q_norm in heading_norm
            body_match = q_norm in body_norm
            if heading_match or body_match:
                results.append({
                    "id": node.id,
                    "heading": node.heading,
                    "section_number": node.section_number,
                    "version_id": node.version_id,
                    "matched_in": "heading" if heading_match else "body",
                })
        return {"query": q, "count": len(results), "results": results}
    finally:
        session.close()


# ---------- Selection API ----------

def _selection_to_out(session: Session, selection: Selection) -> SelectionOut:
    selection_nodes = (
        session.query(SelectionNode)
        .filter(SelectionNode.selection_id == selection.id)
        .all()
    )
    nodes_out = []
    for sn in selection_nodes:
        node = session.get(Node, sn.node_id)
        if node is None:
            continue  # node was deleted outright; surfaced via staleness, not here
        version = session.get(DocumentVersion, node.version_id)
        nodes_out.append(
            SelectionNodeOut(
                node_id=node.id,
                heading=node.heading,
                section_number=node.section_number,
                version_number=version.version_number,
            )
        )
    return SelectionOut(id=selection.id, name=selection.name, created_at=selection.created_at, nodes=nodes_out)


def _reconstruct_selection_text(nodes: list[Node]) -> str:
    parts = []
    for node in nodes:
        label = f"{node.section_number + ' ' if node.section_number else ''}{node.heading}".strip()
        parts.append(f"=== {label} ===\n{_node_content_text(node)}")
    return "\n\n".join(parts)


@app.post("/selections", response_model=SelectionOut)
def create_selection(payload: SelectionCreate):
    session: Session = get_session()
    try:
        nodes = []
        for node_id in payload.node_ids:
            node = session.get(Node, node_id)
            if node is None:
                raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
            nodes.append(node)

        selection = Selection(name=payload.name)
        session.add(selection)
        session.flush()

        for node in nodes:
            session.add(SelectionNode(selection_id=selection.id, node_id=node.id))

        session.commit()
        session.refresh(selection)
        return _selection_to_out(session, selection)
    finally:
        session.close()


@app.get("/selections/{selection_id}", response_model=SelectionOut)
def get_selection(selection_id: int):
    session: Session = get_session()
    try:
        selection = session.get(Selection, selection_id)
        if selection is None:
            raise HTTPException(status_code=404, detail="Selection not found")
        return _selection_to_out(session, selection)
    finally:
        session.close()


# ---------- Test-case generation API ----------

@app.post("/selections/{selection_id}/test-cases")
def create_test_cases(selection_id: int):
    session: Session = get_session()
    try:
        selection = session.get(Selection, selection_id)
        if selection is None:
            raise HTTPException(status_code=404, detail="Selection not found")

        selection_nodes = (
            session.query(SelectionNode)
            .filter(SelectionNode.selection_id == selection.id)
            .all()
        )
        nodes = []
        for sn in selection_nodes:
            node = session.get(Node, sn.node_id)
            if node is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Node {sn.node_id} referenced by this selection no longer exists",
                )
            nodes.append(node)
        nodes.sort(key=lambda n: (n.page_number or 0, n.block_index or 0, n.id))

        combined_content = _reconstruct_selection_text(nodes)
        selection_label = selection.name

        try:
            test_cases = generate_test_cases(selection_label, combined_content)
        except LLMGenerationError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

        content_hashes = {str(n.id): n.content_hash for n in nodes}

        nosql_store.save_test_cases(
            selection_id=selection.id,
            node_ids=[n.id for n in nodes],
            content_hashes_at_generation=content_hashes,
            test_cases=test_cases,
        )

        return {"selection_id": selection.id, "test_cases": test_cases}
    finally:
        session.close()


# ---------- Retrieval API ----------

@app.get("/selections/{selection_id}/test-cases")
def retrieve_test_cases(selection_id: int):
    record = nosql_store.get_test_cases(selection_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No test cases generated yet for this selection")
    return record


# ---------- Staleness / impact detection API ----------

@app.get("/selections/{selection_id}/staleness", response_model=StalenessResult)
def check_staleness(selection_id: int):
    session: Session = get_session()
    try:
        selection = session.get(Selection, selection_id)
        if selection is None:
            raise HTTPException(status_code=404, detail="Selection not found")

        record = nosql_store.get_test_cases(selection_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail="No test cases generated yet for this selection -- nothing to check for staleness",
            )

        stored_hashes = record["content_hashes_at_generation"]

        selection_nodes = (
            session.query(SelectionNode)
            .filter(SelectionNode.selection_id == selection.id)
            .all()
        )

        node_details = []
        is_stale_overall = False
        current_version_numbers = set()
        latest_version_number = None

        for sn in selection_nodes:
            node = session.get(Node, sn.node_id)
            if node is None:
                node_details.append(
                    NodeStaleness(
                        node_id=sn.node_id,
                        heading="(deleted)",
                        status="removed",
                        detail="Node row no longer exists in the database.",
                    )
                )
                is_stale_overall = True
                continue

            version = session.get(DocumentVersion, node.version_id)
            current_version_numbers.add(version.version_number)

            later_versions = (
                session.query(DocumentVersion)
                .filter(
                    DocumentVersion.document_id == version.document_id,
                    DocumentVersion.version_number > version.version_number,
                )
                .order_by(DocumentVersion.version_number)
                .all()
            )

            if not later_versions:
                node_details.append(
                    NodeStaleness(
                        node_id=node.id, heading=node.heading, status="unchanged",
                        detail="No newer document version exists.",
                    )
                )
                continue

            latest_version = later_versions[-1]
            if latest_version_number is None or latest_version.version_number > latest_version_number:
                latest_version_number = latest_version.version_number

            matched_in_latest = (
                session.query(Node)
                .filter(Node.version_id == latest_version.id, Node.matched_node_id == node.id)
                .first()
            )

            if matched_in_latest is None:
                node_details.append(
                    NodeStaleness(
                        node_id=node.id, heading=node.heading, status="removed",
                        detail=f"Section removed by version {latest_version.version_number}.",
                    )
                )
                is_stale_overall = True
                continue

            stored_hash = stored_hashes.get(str(node.id))
            if matched_in_latest.content_hash != stored_hash:
                node_details.append(
                    NodeStaleness(
                        node_id=node.id, heading=node.heading, status="changed",
                        detail=f"Content changed in version {latest_version.version_number}.",
                    )
                )
                is_stale_overall = True
            else:
                node_details.append(
                    NodeStaleness(
                        node_id=node.id, heading=node.heading, status="unchanged",
                        detail="Content unchanged in latest version.",
                    )
                )

        reason = (
            "One or more sections in this selection changed or were removed in a later document version."
            if is_stale_overall
            else "All sections in this selection are unchanged in the latest document version."
        )

        return StalenessResult(
            selection_id=selection_id,
            is_stale=is_stale_overall,
            reason=reason,
            current_version_numbers=sorted(current_version_numbers),
            latest_version_number=latest_version_number,
            node_details=node_details,
        )
    finally:
        session.close()