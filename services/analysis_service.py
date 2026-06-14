from __future__ import annotations

import math
from typing import Optional

from sqlalchemy.orm import Session

from database import models
from schemas import (
    ErrorAnalysisOut, IntervalError, AdjustmentRecommendation,
)
from services.validation_service import ERROR_THRESHOLD


def _lerp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if abs(x1 - x0) < 1e-9:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _expected_water_level(
    t: float, marks: list[models.ScaleMark], capacity: float
) -> float:
    if not marks:
        return capacity
    sorted_marks = sorted(marks, key=lambda m: m.target_time)
    if t <= sorted_marks[0].target_time:
        return sorted_marks[0].target_water_level
    if t >= sorted_marks[-1].target_time:
        return sorted_marks[-1].target_water_level
    for i in range(len(sorted_marks) - 1):
        m0, m1 = sorted_marks[i], sorted_marks[i + 1]
        if m0.target_time <= t <= m1.target_time:
            return _lerp(t, m0.target_time, m0.target_water_level,
                         m1.target_time, m1.target_water_level)
    return sorted_marks[-1].target_water_level


def _nearest_mark(
    t: float, marks: list[models.ScaleMark]
) -> Optional[models.ScaleMark]:
    if not marks:
        return None
    return min(marks, key=lambda m: abs(m.target_time - t))


class AnalysisService:

    @staticmethod
    def compute_records(
        db: Session, project_id: int, experiment_id: int,
    ) -> tuple[float, float]:
        exp = (
            db.query(models.Experiment)
            .filter(
                models.Experiment.id == experiment_id,
                models.Experiment.project_id == project_id,
            )
            .first()
        )
        if not exp:
            raise ValueError("实验不存在")
        if not exp.records:
            raise ValueError("暂无实验记录可供分析")

        scheme = (
            db.query(models.ScaleScheme)
            .filter(models.ScaleScheme.project_id == project_id)
            .first()
        )
        marks = scheme.marks if scheme else []
        cfg = (
            db.query(models.ClepsydraConfig)
            .filter(models.ClepsydraConfig.project_id == project_id)
            .first()
        )
        capacity = cfg.capacity if cfg else 1000.0

        records = sorted(exp.records, key=lambda r: r.time_point)
        prev_level = capacity
        prev_time = 0.0
        total_error = 0.0
        count = 0

        for rec in records:
            dt = rec.time_point - prev_time
            if dt > 0:
                flow = (prev_level - rec.water_level) / dt
                rec.computed_flow_rate = round(flow, 4)
            else:
                rec.computed_flow_rate = 0.0

            expected = _expected_water_level(rec.time_point, marks, capacity)
            if expected > 0:
                err_pct = (rec.water_level - expected) / expected * 100.0
            else:
                err_pct = 0.0
            rec.time_error = round(err_pct, 4)
            total_error += abs(err_pct)
            count += 1

            prev_level = rec.water_level
            prev_time = rec.time_point

        avg_error = round(total_error / count, 4) if count > 0 else 0.0
        exp.total_error = avg_error
        exp.status = "finalized"
        exp.finalized_at = exp.finalized_at or __import__("datetime").datetime.utcnow()

        db.commit()
        db.refresh(exp)

        project = (
            db.query(models.Project)
            .filter(models.Project.id == project_id)
            .first()
        )
        if project and project.status not in ("completed",):
            project.status = "completed"
            db.commit()

        refreshed_records = (
            db.query(models.ExperimentRecord)
            .filter(models.ExperimentRecord.experiment_id == experiment_id)
            .order_by(models.ExperimentRecord.time_point)
            .all()
        )
        return avg_error, count, refreshed_records

    @staticmethod
    def get_analysis(
        db: Session, project_id: int, experiment_id: int,
    ) -> ErrorAnalysisOut:
        exp = (
            db.query(models.Experiment)
            .filter(
                models.Experiment.id == experiment_id,
                models.Experiment.project_id == project_id,
            )
            .first()
        )
        if not exp:
            raise ValueError("实验不存在")

        scheme = (
            db.query(models.ScaleScheme)
            .filter(models.ScaleScheme.project_id == project_id)
            .first()
        )
        marks = sorted(scheme.marks, key=lambda m: m.target_time) if scheme else []
        cfg = (
            db.query(models.ClepsydraConfig)
            .filter(models.ClepsydraConfig.project_id == project_id)
            .first()
        )
        capacity = cfg.capacity if cfg else 1000.0
        records = sorted(exp.records, key=lambda r: r.time_point)

        interval_errors: list[IntervalError] = []
        max_error = 0.0
        total_abs = 0.0
        count = 0

        extended = [(0.0, capacity)] + [(r.time_point, r.water_level) for r in records]

        for i in range(len(marks) - 1):
            m0, m1 = marks[i], marks[i + 1]
            t_start, t_end = m0.target_time, m1.target_time
            mid_t = (t_start + t_end) / 2.0

            actual_start = None
            actual_end = None
            for j in range(len(extended) - 1):
                et0, el0 = extended[j]
                et1, el1 = extended[j + 1]
                if et0 <= t_start <= et1:
                    actual_start = _lerp(t_start, et0, el0, et1, el1)
                if et0 <= t_end <= et1:
                    actual_end = _lerp(t_end, et0, el0, et1, el1)

            if actual_start is None:
                actual_start = extended[-1][1] if extended else m0.target_water_level
            if actual_end is None:
                actual_end = extended[-1][1] if extended else m1.target_water_level

            mid_actual = _lerp(mid_t, t_start, actual_start, t_end, actual_end)
            mid_expected = _lerp(mid_t, t_start, m0.target_water_level,
                                 t_end, m1.target_water_level)

            if mid_expected > 0:
                err_pct = (mid_actual - mid_expected) / mid_expected * 100.0
            else:
                err_pct = 0.0
            err_abs = mid_actual - mid_expected
            exceeded = abs(err_pct) > ERROR_THRESHOLD

            total_abs += abs(err_pct)
            count += 1
            if abs(err_pct) > max_error:
                max_error = abs(err_pct)

            interval_errors.append(IntervalError(
                interval=f"刻度#{m0.mark_index}→#{m1.mark_index}",
                start_time=t_start,
                end_time=t_end,
                expected_level=round(mid_expected, 3),
                actual_level=round(mid_actual, 3),
                error=round(err_abs, 3),
                error_percent=round(err_pct, 3),
                exceeded=exceeded,
            ))

        avg_error = round(total_abs / count, 3) if count > 0 else 0.0

        recommendations: list[AdjustmentRecommendation] = []
        for interval in interval_errors:
            if interval.exceeded:
                t_mid = (interval.start_time + interval.end_time) / 2.0
                mark = _nearest_mark(t_mid, marks)
                if mark:
                    expected = _expected_water_level(mark.target_time, marks, capacity)
                    actual_mid = (
                        _expected_water_level(mark.target_time,
                                              [type("M", (), {"target_time": ie.start_time,
                                                              "target_water_level": ie.actual_level})()
                                               for ie in interval_errors],
                                              capacity)
                        if expected else expected
                    )
                    direction = "下移" if interval.error > 0 else "上移"
                    suggestions = round(mark.target_water_level - interval.error * 0.5, 2)
                    suggestions = max(0.0, min(capacity, suggestions))
                    reason = (
                        f"区间 {interval.interval} 误差 {interval.error_percent:+.2f}%，"
                        f"实际水位 {'偏高' if interval.error > 0 else '偏低'}，"
                        f"建议调整刻度 #{mark.mark_index}"
                    )
                    recommendations.append(AdjustmentRecommendation(
                        mark_index=mark.mark_index,
                        target_time=mark.target_time,
                        original_level=mark.target_water_level,
                        suggested_level=suggestions,
                        direction=direction,
                        reason=reason,
                    ))

        return ErrorAnalysisOut(
            experiment_id=experiment_id,
            total_error=round(total_abs, 3),
            max_error=round(max_error, 3),
            avg_error=avg_error,
            threshold_percent=ERROR_THRESHOLD,
            interval_errors=interval_errors,
            adjustment_recommendations=recommendations,
        )

    @staticmethod
    def mark_finalized_needs_recheck(
        db: Session, project_id: int,
    ) -> None:
        experiments = (
            db.query(models.Experiment)
            .filter(
                models.Experiment.project_id == project_id,
                models.Experiment.status == "finalized",
            )
            .all()
        )
        for exp in experiments:
            exp.needs_recheck = True
        project = (
            db.query(models.Project)
            .filter(models.Project.id == project_id)
            .first()
        )
        if project and experiments:
            project.needs_recheck = True
        db.commit()
