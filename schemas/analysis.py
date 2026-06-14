from __future__ import annotations

from typing import Optional, List

from pydantic import BaseModel, ConfigDict


class IntervalError(BaseModel):
    interval: str
    start_time: float
    end_time: float
    expected_level: float
    actual_level: float
    error: float
    error_percent: float
    exceeded: bool


class AdjustmentRecommendation(BaseModel):
    mark_index: int
    target_time: float
    original_level: float
    suggested_level: float
    direction: str
    reason: str


class ErrorAnalysisOut(BaseModel):
    experiment_id: int
    total_error: float
    max_error: float
    avg_error: float
    threshold_percent: float
    interval_errors: List[IntervalError]
    adjustment_recommendations: List[AdjustmentRecommendation]
