"""
Shared pytest fixtures and helpers for the CT-200 parser/tree test
suite.

Extracting a PDF and building its document tree involves PyMuPDF
parsing, table detection, and tree construction -- not free. Each PDF
is processed once per test session via session-scoped fixtures,
rather than once per test function.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from pdf_extractor import extract_pdf
from tree_builder import build_document_tree


@pytest.fixture(scope="session")
def v1_extracted():
    return extract_pdf(PROJECT_ROOT / "data" / "ct200_manual.pdf")


@pytest.fixture(scope="session")
def v2_extracted():
    return extract_pdf(PROJECT_ROOT / "data" / "ct200_manual_v2.pdf")


@pytest.fixture(scope="session")
def v1_tree(v1_extracted):
    return build_document_tree(v1_extracted)


@pytest.fixture(scope="session")
def v2_tree(v2_extracted):
    return build_document_tree(v2_extracted)


def find_nodes_by_section(nodes, section_number):
    """
    Recursively search a list of tree nodes (and their children) for
    all nodes matching a given section_number. Returns a list, not a
    single node, because callers should explicitly assert on count --
    silently assuming uniqueness would hide a real bug if it broke.
    """
    matches = []
    for node in nodes:
        if node["section_number"] == section_number:
            matches.append(node)
        matches.extend(find_nodes_by_section(node["children"], section_number))
    return matches


def flatten_tree(nodes):
    """Flatten a tree (list of root nodes) into a single flat list of
    every node, for building node_id lookup tables in tests."""
    result = []
    for node in nodes:
        result.append(node)
        result.extend(flatten_tree(node["children"]))
    return result