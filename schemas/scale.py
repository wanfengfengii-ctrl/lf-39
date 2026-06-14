from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator, ConfigDict


class ScaleMarkData(BaseModel):
    mark_index: int = Field(..., ge=0)
    target_time: float = Field(..., ge=0, description="目标时间 (分钟)")
    target_water_level: float = Field(..., gt=0, description="对应水位 (ml)")


class ScaleSchemeUpdate(BaseModel):
    marks: List[ScaleMarkData]

    @field_validator("marks")
    @classmethod
    def validate_marks(cls, v: List[ScaleMarkData]) -> List[ScaleMarkData]:
        if not v:
            raise ValueError("刻度方案不能为空")
        indices = [m.mark_index for m in v]
        times = [m.target_time for m in v]
        if len(set(indices)) != len(indices):
            raise ValueError("刻度序号不能重复")
        for i in range(1, len(times)):
            if times[i] <= times[i - 1]:
                raise ValueError("目标时间必须严格递增")
        return v


class ScaleMarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    mark_index: int
    target_time: float
    target_water_level: float


class ScaleSchemeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    version: int = 1
    created_at: Optional[datetime] = None
    marks: List[ScaleMarkOut] = []
