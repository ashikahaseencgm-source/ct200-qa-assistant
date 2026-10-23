from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SelectionCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Human-readable label for this selection")
    node_ids: list[int] = Field(..., min_length=1, description="One or more node IDs to include")


class SelectionNodeOut(BaseModel):
    node_id: int
    heading: str
    section_number: Optional[str]
    version_number: int


class SelectionOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    nodes: list[SelectionNodeOut]


class TestCase(BaseModel):
    title: str = Field(..., description="Short descriptive title of the test case")
    preconditions: str = Field(..., description="State required before executing the test")
    steps: list[str] = Field(..., description="Ordered list of steps to execute")
    expected_result: str = Field(..., description="What should happen if the feature works correctly")
    priority: str = Field(..., description="One of: high, medium, low")


class TestCaseList(BaseModel):
    test_cases: list[TestCase]


class NodeStaleness(BaseModel):
    node_id: int
    heading: str
    status: str  # "unchanged" | "changed" | "removed"
    detail: str


class StalenessResult(BaseModel):
    selection_id: int
    is_stale: bool
    reason: str
    current_version_numbers: list[int]
    latest_version_number: Optional[int] = None
    node_details: list[NodeStaleness] = []