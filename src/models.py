"""
SQLAlchemy ORM models for the CT-200 QA Assistant's relational data:
documents, their versions, the tree nodes within each version, and
node selections (used later by the selection/test-case-generation
API in Step 6).

Design note: content_blocks and tables are stored as JSON text
columns (full fidelity preserved) rather than normalized into their
own tables. This is a deliberate simplification appropriate for this
project's scale -- querying inside a specific table's rows or a
list's items requires parsing JSON in Python, not SQL. See the
Approach Document's Decision Log.
"""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    source_filename = Column(String, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("nodes.id"), nullable=True)

    heading = Column(Text, nullable=False)
    section_number = Column(String, nullable=True)
    level = Column(Integer, nullable=False)
    node_type = Column(String, nullable=False)
    page_number = Column(Integer, nullable=True)
    block_index = Column(Integer, nullable=True)
    content_hash = Column(String, nullable=True)

    # Full node content, preserved exactly as produced by tree_builder.py.
    content_blocks_json = Column(Text, nullable=False, default="[]")
    tables_json = Column(Text, nullable=False, default="[]")

    # Versioning linkage: points to this node's matched counterpart in
    # the previous version's rows, if any was found. NULL for V1
    # (baseline) and for genuinely new V2 nodes.
    matched_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=True)

    # One of: "baseline", "new", "changed", "unchanged".
    # "removed" is NOT stored here -- it's computed at report time as
    # any prior-version node with no later node pointing back to it.
    change_status = Column(String, nullable=False, default="new")


# class Selection(Base):
#     __tablename__ = "selections"

#     id = Column(Integer, primary_key=True)
#     node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
#     created_at = Column(DateTime, default=datetime.utcnow)

class Selection(Base):
    __tablename__ = "selections"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SelectionNode(Base):
    __tablename__ = "selection_nodes"

    id = Column(Integer, primary_key=True)
    selection_id = Column(Integer, ForeignKey("selections.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)