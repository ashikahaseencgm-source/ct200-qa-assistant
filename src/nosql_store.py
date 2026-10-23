"""
Minimal NoSQL-style store for LLM-generated test cases, implemented
as a local JSON file (data/test_cases_store.json).

Per the assignment, a real MongoDB instance (local or Atlas) is
preferred, but a well-justified JSON store is explicitly allowed. At
this project's scale (a handful of selections, each with 3-5
generated test cases), a real MongoDB dependency adds real
operational risk (connection setup, auth, a running daemon) for no
meaningful benefit -- a deliberate, documented tradeoff, not a
shortcut taken silently.

Each record is keyed by selection_id (one record per selection,
overwritten on regeneration) and stores the generated test cases
plus each contributing node's content_hash at generation time, used
later for per-node staleness comparisons.
"""

import json
from datetime import datetime
from pathlib import Path
from threading import Lock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = PROJECT_ROOT / "data" / "test_cases_store.json"

_lock = Lock()


def _read_store():
    if not STORE_PATH.exists():
        return {}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_store(data):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def save_test_cases(selection_id, node_ids, content_hashes_at_generation, test_cases):
    with _lock:
        store = _read_store()
        store[str(selection_id)] = {
            "selection_id": selection_id,
            "node_ids": node_ids,
            "content_hashes_at_generation": content_hashes_at_generation,
            "generated_at": datetime.utcnow().isoformat(),
            "test_cases": test_cases,
        }
        _write_store(store)


def get_test_cases(selection_id):
    with _lock:
        store = _read_store()
        return store.get(str(selection_id))