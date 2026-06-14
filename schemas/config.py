from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, ConfigDict


VALID_INLET_TYPES = {"constant", "gravity", "manual"}


class ClepsydraConfigUpdate(BaseModel):
    capacity: float = Field(..., gt=0, description="漏壶容量 (ml)，必须大于0")
    water_inlet_type: str = Field(..., description="进水方式: constant/gravity/manual")
    outlet_diameter: float = Field(..., gt=0, description="出水孔径 (mm)，必须大于0")
    target_duration: float = Field(..., gt=0, description="目标计时时长 (分钟)")

    @field_validator("water_inlet_type")
    @classmethod
    def validate_inlet_type(cls, v: str) -> str:
        if v not in VALID_INLET_TYPES:
            raise ValueError(f"进水方式必须是: {', '.join(VALID_INLET_TYPES)}")
        return v


class ClepsydraConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    capacity: float
    water_inlet_type: str
    outlet_diameter: float
    target_duration: float
    params_changed: bool = False
