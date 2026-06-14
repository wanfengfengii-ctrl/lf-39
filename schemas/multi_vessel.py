from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator, ConfigDict


VALID_VESSEL_ROLES = {"top", "middle", "bottom", "reservoir"}
VALID_RELATION_TYPES = {"series", "parallel", "bypass"}
VALID_INLET_TYPES = {"constant", "gravity", "manual"}


class VesselCreate(BaseModel):
    level_index: int = Field(..., ge=0, description="容器层级索引（从上到下 0,1,2...）")
    name: str = Field(..., min_length=1, max_length=50, description="容器名称，如'上壶'、'中壶'")
    role: str = Field(default="middle", description="容器角色: top/middle/bottom/reservoir")
    capacity: float = Field(..., gt=0, description="容量 (ml)")
    water_inlet_type: str = Field(default="gravity", description="进水方式")
    outlet_diameter: float = Field(..., gt=0, description="出水孔径 (mm)")
    target_duration: Optional[float] = Field(default=None, gt=0, description="目标计时时长 (分钟)")
    initial_level: Optional[float] = Field(default=None, ge=0, description="初始水位 (ml)")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_VESSEL_ROLES:
            raise ValueError(f"容器角色必须是: {', '.join(VALID_VESSEL_ROLES)}")
        return v

    @field_validator("water_inlet_type")
    @classmethod
    def validate_inlet(cls, v: str) -> str:
        if v not in VALID_INLET_TYPES:
            raise ValueError(f"进水方式必须是: {', '.join(VALID_INLET_TYPES)}")
        return v


class VesselUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    role: Optional[str] = None
    capacity: Optional[float] = Field(default=None, gt=0)
    water_inlet_type: Optional[str] = None
    outlet_diameter: Optional[float] = Field(default=None, gt=0)
    target_duration: Optional[float] = Field(default=None, gt=0)
    initial_level: Optional[float] = Field(default=None, ge=0)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_VESSEL_ROLES:
            raise ValueError(f"容器角色必须是: {', '.join(VALID_VESSEL_ROLES)}")
        return v


class VesselOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level_index: int
    name: str
    role: str
    capacity: float
    water_inlet_type: str
    outlet_diameter: float
    target_duration: Optional[float] = None
    initial_level: Optional[float] = None
    created_at: Optional[datetime] = None


class VesselFlowRelationCreate(BaseModel):
    upstream_vessel_id: int = Field(..., gt=0, description="上游容器ID")
    downstream_vessel_id: int = Field(..., gt=0, description="下游容器ID")
    flow_coefficient: float = Field(default=1.0, gt=0, description="流量传递系数")
    delay_seconds: float = Field(default=0.0, ge=0, description="级间延迟 (秒)")
    relation_type: str = Field(default="series", description="关联类型: series/parallel/bypass")

    @field_validator("relation_type")
    @classmethod
    def validate_relation(cls, v: str) -> str:
        if v not in VALID_RELATION_TYPES:
            raise ValueError(f"关联类型必须是: {', '.join(VALID_RELATION_TYPES)}")
        return v


class VesselFlowRelationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    upstream_vessel_id: int
    downstream_vessel_id: int
    flow_coefficient: float
    delay_seconds: float
    relation_type: str


class MultiVesselConfigOut(BaseModel):
    is_multi_vessel: bool
    vessels: List[VesselOut] = []
    flow_relations: List[VesselFlowRelationOut] = []


class VesselRecordCreate(BaseModel):
    vessel_id: int = Field(..., gt=0, description="容器ID")
    time_point: float = Field(..., ge=0, description="时间节点 (分钟)")
    water_level: float = Field(..., ge=0, description="实测水位 (ml)")


class VesselBatchRecordCreate(BaseModel):
    time_point: float = Field(..., ge=0, description="同一时间节点 (分钟)")
    records: List[VesselRecordCreate]

    @field_validator("records")
    @classmethod
    def validate_unique_vessels(cls, v: List[VesselRecordCreate]) -> List[VesselRecordCreate]:
        ids = [r.vessel_id for r in v]
        if len(set(ids)) != len(ids):
            raise ValueError("同一时间节点每个容器只能有一条记录")
        return v


class VesselRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vessel_id: int
    time_point: float
    water_level: float
    computed_flow_rate: Optional[float] = None
    time_error: Optional[float] = None
    inflow_rate: Optional[float] = None


class VesselLevelDataPoint(BaseModel):
    time_point: float
    water_level: float
    computed_flow_rate: Optional[float] = None
    time_error: Optional[float] = None


class VesselTimeSeries(BaseModel):
    vessel_id: int
    vessel_name: str
    level_index: int
    role: str
    data_points: List[VesselLevelDataPoint] = []


class InterVesselError(BaseModel):
    upstream_vessel_id: int
    upstream_vessel_name: str
    downstream_vessel_id: int
    downstream_vessel_name: str
    time_point: float
    expected_flow: float
    actual_flow: float
    flow_error: float
    flow_error_percent: float
    cumulative_error: float
    exceeded: bool


class VesselErrorAmplification(BaseModel):
    vessel_id: int
    vessel_name: str
    level_index: int
    avg_error_percent: float
    max_error_percent: float
    error_gain: float
    is_amplification_stage: bool
    reason: str


class VesselScaleAdjustment(BaseModel):
    vessel_id: int
    vessel_name: str
    mark_index: int
    target_time: float
    original_level: float
    suggested_level: float
    direction: str
    reason: str


class MultiVesselAnalysisOut(BaseModel):
    experiment_id: int
    total_vessels: int
    time_series: List[VesselTimeSeries] = []
    inter_vessel_errors: List[InterVesselError] = []
    error_amplification_stages: List[VesselErrorAmplification] = []
    scale_adjustments: List[VesselScaleAdjustment] = []
    threshold_percent: float = 5.0


class JointAdjustmentStep(BaseModel):
    step_order: int
    vessel_id: int
    vessel_name: str
    level_index: int
    priority: str
    adjustment_count: int
    adjustment_summary: str
    current_avg_error: float
    expected_improvement: float
    impact_on_downstream: float
    details: List[dict] = []
    rationale: str


class JointScaleAdjustmentOut(BaseModel):
    experiment_id: int
    total_vessels: int
    adjustment_steps: List[JointAdjustmentStep] = []
    total_expected_improvement: float
    overall_rationale: str
    threshold_percent: float = 5.0
