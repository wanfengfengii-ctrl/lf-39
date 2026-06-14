from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, model_validator


class PerturbationConfigUpdate(BaseModel):
    temperature_min: Optional[float] = Field(default=10.0, ge=-20, le=80)
    temperature_max: Optional[float] = Field(default=40.0, ge=-20, le=80)
    temperature_baseline: Optional[float] = Field(default=20.0, ge=-20, le=80)
    temperature_enabled: Optional[bool] = True

    viscosity_min: Optional[float] = Field(default=0.8, ge=0.1, le=10.0)
    viscosity_max: Optional[float] = Field(default=1.8, ge=0.1, le=10.0)
    viscosity_baseline: Optional[float] = Field(default=1.0, ge=0.1, le=10.0)
    viscosity_enabled: Optional[bool] = True

    inflow_fluctuation_amplitude: Optional[float] = Field(default=0.1, ge=0.0, le=1.0)
    inflow_fluctuation_frequency: Optional[float] = Field(default=0.5, ge=0.0, le=10.0)
    inflow_fluctuation_enabled: Optional[bool] = True

    orifice_wear_rate: Optional[float] = Field(default=0.02, ge=0.0, le=1.0)
    orifice_wear_max: Optional[float] = Field(default=0.3, ge=0.0, le=1.0)
    orifice_wear_enabled: Optional[bool] = True

    tilt_angle_min: Optional[float] = Field(default=0.0, ge=0.0, le=45.0)
    tilt_angle_max: Optional[float] = Field(default=5.0, ge=0.0, le=45.0)
    tilt_angle_baseline: Optional[float] = Field(default=0.0, ge=0.0, le=45.0)
    tilt_enabled: Optional[bool] = True

    simulation_duration: Optional[float] = Field(default=60.0, ge=1.0, le=1440.0)
    time_step: Optional[float] = Field(default=0.5, ge=0.01, le=10.0)
    scenario_count: Optional[int] = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def check_ranges(self) -> "PerturbationConfigUpdate":
        errors = []
        if self.temperature_min is not None and self.temperature_max is not None:
            if self.temperature_min > self.temperature_max:
                errors.append(f"温度最小值 ({self.temperature_min}) 不能大于最大值 ({self.temperature_max})")
        if self.temperature_baseline is not None:
            if self.temperature_min is not None and self.temperature_baseline < self.temperature_min:
                errors.append(f"温度基准值 ({self.temperature_baseline}) 不能小于最小值 ({self.temperature_min})")
            if self.temperature_max is not None and self.temperature_baseline > self.temperature_max:
                errors.append(f"温度基准值 ({self.temperature_baseline}) 不能大于最大值 ({self.temperature_max})")
        if self.viscosity_min is not None and self.viscosity_max is not None:
            if self.viscosity_min > self.viscosity_max:
                errors.append(f"黏度最小值 ({self.viscosity_min}) 不能大于最大值 ({self.viscosity_max})")
        if self.viscosity_baseline is not None:
            if self.viscosity_min is not None and self.viscosity_baseline < self.viscosity_min:
                errors.append(f"黏度基准值 ({self.viscosity_baseline}) 不能小于最小值 ({self.viscosity_min})")
            if self.viscosity_max is not None and self.viscosity_baseline > self.viscosity_max:
                errors.append(f"黏度基准值 ({self.viscosity_baseline}) 不能大于最大值 ({self.viscosity_max})")
        if self.tilt_angle_min is not None and self.tilt_angle_max is not None:
            if self.tilt_angle_min > self.tilt_angle_max:
                errors.append(f"倾斜角最小值 ({self.tilt_angle_min}) 不能大于最大值 ({self.tilt_angle_max})")
        if self.tilt_angle_baseline is not None:
            if self.tilt_angle_min is not None and self.tilt_angle_baseline < self.tilt_angle_min:
                errors.append(f"倾斜角基准值 ({self.tilt_angle_baseline}) 不能小于最小值 ({self.tilt_angle_min})")
            if self.tilt_angle_max is not None and self.tilt_angle_baseline > self.tilt_angle_max:
                errors.append(f"倾斜角基准值 ({self.tilt_angle_baseline}) 不能大于最大值 ({self.tilt_angle_max})")
        if self.simulation_duration is not None and self.time_step is not None:
            if self.time_step > self.simulation_duration:
                errors.append(f"时间步长 ({self.time_step}) 不能大于模拟时长 ({self.simulation_duration})")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class PerturbationConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    temperature_min: float
    temperature_max: float
    temperature_baseline: float
    temperature_enabled: bool

    viscosity_min: float
    viscosity_max: float
    viscosity_baseline: float
    viscosity_enabled: bool

    inflow_fluctuation_amplitude: float
    inflow_fluctuation_frequency: float
    inflow_fluctuation_enabled: bool

    orifice_wear_rate: float
    orifice_wear_max: float
    orifice_wear_enabled: bool

    tilt_angle_min: float
    tilt_angle_max: float
    tilt_angle_baseline: float
    tilt_enabled: bool

    simulation_duration: float
    time_step: float
    scenario_count: int


class SimulationScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    config_id: Optional[int] = None
    scenario_index: int
    name: str
    is_multi_vessel: bool
    status: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    temperature: Optional[float] = None
    viscosity: Optional[float] = None
    inflow_amplitude: Optional[float] = None
    orifice_wear: Optional[float] = None
    tilt_angle: Optional[float] = None
    params: Optional[Dict[str, Any]] = None


class SimulationResultPoint(BaseModel):
    time_point: float
    water_level: float
    expected_level: Optional[float] = None
    flow_rate: Optional[float] = None
    inflow_rate: Optional[float] = None
    time_error: Optional[float] = None
    level_error: Optional[float] = None


class SimulationScenarioDetail(BaseModel):
    scenario: SimulationScenarioOut
    results: List[SimulationResultPoint] = []
    vessel_results: Optional[Dict[str, List[SimulationResultPoint]]] = None


class SensitivityScore(BaseModel):
    parameter: str
    parameter_label: str
    score: float
    correlation: float
    p_value: Optional[float] = None
    impact_direction: str


class ParameterRanking(BaseModel):
    rank: int
    parameter: str
    parameter_label: str
    sensitivity_score: float
    category: str
    description: str


class CalibrationAdvice(BaseModel):
    parameter: str
    parameter_label: str
    priority: str
    action: str
    target_range: str
    expected_improvement: float
    reason: str


class ScenarioSummary(BaseModel):
    scenario_id: int
    scenario_index: int
    name: str
    avg_error: float
    max_error: float
    final_level_error: float
    failed: bool
    params: Dict[str, Any]


class RobustnessAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    config_id: Optional[int] = None
    is_multi_vessel: bool
    created_at: Optional[datetime] = None

    overall_stability_score: Optional[float] = None
    avg_error: Optional[float] = None
    max_error: Optional[float] = None
    error_std: Optional[float] = None
    failure_rate: Optional[float] = None

    sensitivity_scores: Optional[List[SensitivityScore]] = None
    parameter_ranking: Optional[List[ParameterRanking]] = None
    calibration_advice: Optional[List[CalibrationAdvice]] = None
    scenario_summaries: Optional[List[ScenarioSummary]] = None
    summary: Optional[str] = None


class SimulationRunRequest(BaseModel):
    is_multi_vessel: bool = False
    scenario_count: Optional[int] = None


class BatchSimulationOut(BaseModel):
    ok: bool
    total_scenarios: int
    completed: int
    assessment_id: Optional[int] = None
    message: str
