from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    id: str
    description: str

    tool: str
    action: str

    arguments: dict[str, Any] = Field(default_factory=dict)

    depends_on: list[str] = Field(default_factory=list)

    verify: bool = True

    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None


class JobPlan(BaseModel):
    goal: str
    steps: list[PlanStep]


class ToolResult(BaseModel):
    success: bool

    message: str = ""

    data: dict[str, Any] = Field(default_factory=dict)

    evidence: list[str] = Field(default_factory=list)

    error: str | None = None


class JobState(BaseModel):
    job_id: str
    status: StepStatus = StepStatus.PENDING

    current_step: str | None = None

    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)

    results: dict[str, ToolResult] = Field(default_factory=dict)


class JobInstruction(BaseModel):
    source_file: str
    text: str

    character_count: int
    word_count: int