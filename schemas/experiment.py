from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


class ExperimentRecordCreate(BaseModel):
    time_point: float = Field(..., gt=0, description="时间节点 (分钟)，必须大于0")
    water_level: float = Field(..., ge=0, description="实测水位 (ml)")


class ExperimentRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    time_point: float
    water_level: float
    computed_flow_rate: Optional[float] = None
    time_error: Optional[float] = None


class VesselRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vessel_id: int
    time_point: float
    water_level: float
    computed_flow_rate: Optional[float] = None
    time_error: Optional[float] = None
    inflow_rate: Optional[float] = None


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    round_number: int
    started_at: datetime
    finalized_at: Optional[datetime] = None
    status: str
    needs_recheck: bool
    total_error: Optional[float] = None
    is_multi_vessel: bool = False
    records: List[ExperimentRecordOut] = []
    vessel_records: List[VesselRecordOut] = []
