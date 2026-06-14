from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="项目名称")
    description: Optional[str] = Field(default=None, max_length=500, description="研究目标描述")
    researcher: Optional[str] = Field(default=None, max_length=50, description="研究人员")


class ProjectOut(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    status: str
    needs_recheck: bool
    experiment_count: int = 0


class ProjectListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    researcher: Optional[str]
    created_at: datetime
    status: str
    needs_recheck: bool
    experiment_count: int = 0
    last_round: Optional[int] = None
