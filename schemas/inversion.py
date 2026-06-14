from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, ConfigDict


class InversionParameterRange(BaseModel):
    parameter: str
    parameter_label: str
    min_value: float
    max_value: float
    baseline: float
    enabled: bool = True
    unit: Optional[str] = None


class InversionRunRequest(BaseModel):
    experiment_id: Optional[int] = Field(default=None, description="指定实验ID，默认使用最新完成的实验")
    is_multi_vessel: bool = False
    algorithm: str = Field(default="hybrid_pso_grid", pattern="^(hybrid_pso_grid|pso|grid_search|nelder_mead)$")
    particle_count: int = Field(default=30, ge=10, le=200)
    iteration_count: int = Field(default=50, ge=5, le=500)
    grid_density: int = Field(default=5, ge=2, le=15)
    confidence_level: float = Field(default=0.95, ge=0.8, le=0.99)
    custom_ranges: Optional[List[InversionParameterRange]] = None
    target_vessel_id: Optional[int] = None


class OptimalParameterSet(BaseModel):
    temperature: float
    viscosity: float
    inflow_amplitude: float
    orifice_wear: float
    tilt_angle: float
    params: Optional[Dict[str, Any]] = None


class ConfidenceInterval(BaseModel):
    parameter: str
    parameter_label: str
    low: float
    high: float
    best: float
    unit: Optional[str] = None
    width_percent: float


class FitQualityMetrics(BaseModel):
    best_fit_error: float
    avg_fit_error: float
    error_std: float
    rmse: float
    r_squared: float
    mae: Optional[float] = None


class InversionCandidate(BaseModel):
    rank: int
    temperature: float
    viscosity: float
    inflow_amplitude: float
    orifice_wear: float
    tilt_angle: float
    fit_error: float
    rmse: float


class ConvergencePoint(BaseModel):
    iteration: int
    best_error: float
    avg_error: float
    best_params: Dict[str, Any]


class AlignedDataPoint(BaseModel):
    time_point: float
    experiment_level: float
    simulated_level: float
    level_difference: float
    error_percent: Optional[float] = None


class InversionCalibrationAdvice(BaseModel):
    parameter: str
    parameter_label: str
    category: str
    priority: str
    current_estimated: float
    recommended_range: str
    action: str
    rationale: str
    expected_improvement_percent: float


class JointInversionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    experiment_id: Optional[int] = None
    is_multi_vessel: bool
    status: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    algorithm: str
    iteration_count: int
    particle_count: int
    grid_density: int

    optimal_temperature: Optional[float] = None
    optimal_viscosity: Optional[float] = None
    optimal_inflow_amplitude: Optional[float] = None
    optimal_orifice_wear: Optional[float] = None
    optimal_tilt_angle: Optional[float] = None
    optimal_params: Optional[Dict[str, Any]] = None

    best_fit_error: Optional[float] = None
    avg_fit_error: Optional[float] = None
    error_std: Optional[float] = None
    rmse: Optional[float] = None
    r_squared: Optional[float] = None

    confidence_intervals: Optional[List[ConfidenceInterval]] = None
    top_candidates: Optional[List[InversionCandidate]] = None
    convergence_history: Optional[List[ConvergencePoint]] = None
    aligned_experiment_points: Optional[List[AlignedDataPoint]] = None
    simulated_optimal_points: Optional[List[Dict[str, Any]]] = None

    calibration_advice: Optional[List[InversionCalibrationAdvice]] = None
    summary: Optional[str] = None


class InversionListOut(BaseModel):
    id: int
    project_id: int
    experiment_id: Optional[int] = None
    is_multi_vessel: bool
    status: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    algorithm: str
    best_fit_error: Optional[float] = None
    r_squared: Optional[float] = None
