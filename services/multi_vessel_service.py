from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Tuple, Dict

from sqlalchemy.orm import Session

from database import models
from schemas import (
    VesselCreate, VesselUpdate, VesselOut,
    VesselFlowRelationCreate, VesselFlowRelationOut,
    MultiVesselConfigOut,
    VesselBatchRecordCreate, VesselRecordOut,
    VesselTimeSeries, VesselLevelDataPoint,
    InterVesselError, VesselErrorAmplification, VesselScaleAdjustment,
    MultiVesselAnalysisOut,
    ScaleSchemeUpdate, ScaleMarkData,
    JointScaleAdjustmentOut, JointAdjustmentStep,
)
from services.validation_service import ValidationService, ValidationError, ERROR_THRESHOLD
from services.analysis_service import _lerp, _expected_water_level, _nearest_mark


def _compute_inflow_rate(
    records: List[models.VesselExperimentRecord],
    vessel: models.Vessel,
    upstream_vessels: List[models.Vessel],
    relations: List[models.VesselFlowRelation],
    vessel_map: Dict[int, models.Vessel],
) -> None:
    """
    计算每个记录的入流率（来自上游容器的流入）。
    基于质量守恒：入流率 = 水位变化率 + 出流率
    对于串联系统，下游容器的入流率应等于上游容器的出流率 × 流量传递系数
    """
    if len(records) < 2:
        return

    sorted_records = sorted(records, key=lambda r: r.time_point)

    up_map: Dict[int, List[models.VesselExperimentRecord]] = {}
    for up_v in upstream_vessels:
        up_recs = sorted(
            [r for r in up_v.records if r.experiment_id == records[0].experiment_id],
            key=lambda r: r.time_point
        )
        up_map[up_v.id] = up_recs

    for i in range(len(sorted_records)):
        rec = sorted_records[i]
        if i == 0:
            rec.inflow_rate = 0.0
            continue

        prev_rec = sorted_records[i - 1]
        dt = rec.time_point - prev_rec.time_point
        if dt <= 0:
            rec.inflow_rate = 0.0
            continue

        level_change = rec.water_level - prev_rec.water_level
        outflow_rate = max(0.0, -level_change / dt) if level_change < 0 else 0.0
        direct_inflow = level_change / dt if level_change > 0 else 0.0

        total_upstream_flow = 0.0
        for rel in relations:
            up_recs = up_map.get(rel.upstream_vessel_id, [])
            if len(up_recs) < 2:
                continue
            up_flow_at_t = _interpolate_flow(up_recs, rec.time_point - rel.delay_seconds / 60.0)
            total_upstream_flow += up_flow_at_t * rel.flow_coefficient

        if total_upstream_flow > 0:
            rec.inflow_rate = round(total_upstream_flow, 4)
        else:
            rec.inflow_rate = round(direct_inflow, 4)


def _interpolate_flow(records: List[models.VesselExperimentRecord], t: float) -> float:
    """插值计算某一时刻的流速"""
    if not records:
        return 0.0
    if t <= records[0].time_point:
        return records[0].computed_flow_rate or 0.0
    if t >= records[-1].time_point:
        return records[-1].computed_flow_rate or 0.0
    for i in range(len(records) - 1):
        r0, r1 = records[i], records[i + 1]
        if r0.time_point <= t <= r1.time_point:
            f0 = r0.computed_flow_rate or 0.0
            f1 = r1.computed_flow_rate or 0.0
            return _lerp(t, r0.time_point, f0, r1.time_point, f1)
    return records[-1].computed_flow_rate or 0.0


def _compute_cumulative_error(
    errors: List[float],
    threshold: float,
) -> Tuple[float, float, int]:
    """计算累计误差统计：总累计误差、最大连续超限长度、超限次数"""
    cumulative = 0.0
    max_streak = 0
    current_streak = 0
    exceed_count = 0

    for e in errors:
        cumulative += abs(e)
        if abs(e) > threshold:
            exceed_count += 1
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    return cumulative, max_streak, exceed_count


class MultiVesselService:

    @staticmethod
    def enable_multi_vessel(db: Session, project_id: int, enabled: bool = True) -> bool:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")
        project.is_multi_vessel = enabled
        db.commit()
        return True

    @staticmethod
    def get_config(db: Session, project_id: int) -> MultiVesselConfigOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        vessels = db.query(models.Vessel).filter(
            models.Vessel.project_id == project_id
        ).order_by(models.Vessel.level_index).all()

        flow_relations = db.query(models.VesselFlowRelation).filter(
            models.VesselFlowRelation.project_id == project_id
        ).all()

        vessel_out = [
            VesselOut(
                id=v.id, level_index=v.level_index, name=v.name, role=v.role,
                capacity=v.capacity, water_inlet_type=v.water_inlet_type,
                outlet_diameter=v.outlet_diameter, target_duration=v.target_duration,
                initial_level=v.initial_level, created_at=v.created_at,
            )
            for v in vessels
        ]
        rel_out = [
            VesselFlowRelationOut(
                id=r.id, upstream_vessel_id=r.upstream_vessel_id,
                downstream_vessel_id=r.downstream_vessel_id,
                flow_coefficient=r.flow_coefficient, delay_seconds=r.delay_seconds,
                relation_type=r.relation_type,
            )
            for r in flow_relations
        ]
        return MultiVesselConfigOut(
            is_multi_vessel=project.is_multi_vessel,
            vessels=vessel_out,
            flow_relations=rel_out,
        )

    @staticmethod
    def _create_default_vessel_scale(db: Session, vessel: models.Vessel) -> None:
        duration = vessel.target_duration or 60.0
        capacity = vessel.capacity
        scheme = models.ScaleScheme(
            project_id=vessel.project_id,
            vessel_id=vessel.id,
            version=1,
        )
        db.add(scheme)
        db.flush()
        marks = []
        for i in range(11):
            t = round(duration * i / 10, 2)
            level = round(capacity * (1 - i / 10), 2) if i > 0 else capacity
            marks.append(models.ScaleMark(
                scheme_id=scheme.id, mark_index=i,
                target_time=t, target_water_level=level,
            ))
        db.add_all(marks)

    @staticmethod
    def add_vessel(db: Session, project_id: int, data: VesselCreate) -> VesselOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")
        if not project.is_multi_vessel:
            project.is_multi_vessel = True

        existing = db.query(models.Vessel).filter(
            models.Vessel.project_id == project_id,
            models.Vessel.level_index == data.level_index,
        ).first()
        if existing:
            raise ValidationError(f"层级索引 {data.level_index} 已存在，请使用其他索引")

        vessel = models.Vessel(
            project_id=project_id,
            level_index=data.level_index,
            name=data.name,
            role=data.role,
            capacity=data.capacity,
            water_inlet_type=data.water_inlet_type,
            outlet_diameter=data.outlet_diameter,
            target_duration=data.target_duration,
            initial_level=data.initial_level if data.initial_level is not None else data.capacity,
        )
        db.add(vessel)
        db.flush()
        MultiVesselService._create_default_vessel_scale(db, vessel)
        db.commit()
        db.refresh(vessel)
        return VesselOut(
            id=vessel.id, level_index=vessel.level_index, name=vessel.name, role=vessel.role,
            capacity=vessel.capacity, water_inlet_type=vessel.water_inlet_type,
            outlet_diameter=vessel.outlet_diameter, target_duration=vessel.target_duration,
            initial_level=vessel.initial_level, created_at=vessel.created_at,
        )

    @staticmethod
    def update_vessel(
        db: Session, project_id: int, vessel_id: int, data: VesselUpdate
    ) -> VesselOut:
        vessel = db.query(models.Vessel).filter(
            models.Vessel.id == vessel_id, models.Vessel.project_id == project_id
        ).first()
        if not vessel:
            raise ValidationError("容器不存在")
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(vessel, key, value)
        db.commit()
        db.refresh(vessel)
        return VesselOut(
            id=vessel.id, level_index=vessel.level_index, name=vessel.name, role=vessel.role,
            capacity=vessel.capacity, water_inlet_type=vessel.water_inlet_type,
            outlet_diameter=vessel.outlet_diameter, target_duration=vessel.target_duration,
            initial_level=vessel.initial_level, created_at=vessel.created_at,
        )

    @staticmethod
    def delete_vessel(db: Session, project_id: int, vessel_id: int) -> bool:
        vessel = db.query(models.Vessel).filter(
            models.Vessel.id == vessel_id, models.Vessel.project_id == project_id
        ).first()
        if not vessel:
            return False
        db.query(models.VesselFlowRelation).filter(
            (models.VesselFlowRelation.upstream_vessel_id == vessel_id) |
            (models.VesselFlowRelation.downstream_vessel_id == vessel_id)
        ).delete(synchronize_session=False)
        db.delete(vessel)
        db.commit()
        return True

    @staticmethod
    def add_flow_relation(
        db: Session, project_id: int, data: VesselFlowRelationCreate
    ) -> VesselFlowRelationOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        upstream = db.query(models.Vessel).filter(
            models.Vessel.id == data.upstream_vessel_id,
            models.Vessel.project_id == project_id,
        ).first()
        downstream = db.query(models.Vessel).filter(
            models.Vessel.id == data.downstream_vessel_id,
            models.Vessel.project_id == project_id,
        ).first()
        if not upstream or not downstream:
            raise ValidationError("上游或下游容器不存在")
        if data.upstream_vessel_id == data.downstream_vessel_id:
            raise ValidationError("上游和下游容器不能相同")

        duplicate = db.query(models.VesselFlowRelation).filter(
            models.VesselFlowRelation.project_id == project_id,
            models.VesselFlowRelation.upstream_vessel_id == data.upstream_vessel_id,
            models.VesselFlowRelation.downstream_vessel_id == data.downstream_vessel_id,
        ).first()
        if duplicate:
            raise ValidationError("该上下游流量关系已存在，不可重复添加")

        rel = models.VesselFlowRelation(
            project_id=project_id,
            upstream_vessel_id=data.upstream_vessel_id,
            downstream_vessel_id=data.downstream_vessel_id,
            flow_coefficient=data.flow_coefficient,
            delay_seconds=data.delay_seconds,
            relation_type=data.relation_type,
        )
        db.add(rel)
        db.commit()
        db.refresh(rel)
        return VesselFlowRelationOut(
            id=rel.id, upstream_vessel_id=rel.upstream_vessel_id,
            downstream_vessel_id=rel.downstream_vessel_id,
            flow_coefficient=rel.flow_coefficient, delay_seconds=rel.delay_seconds,
            relation_type=rel.relation_type,
        )

    @staticmethod
    def delete_flow_relation(db: Session, project_id: int, relation_id: int) -> bool:
        rel = db.query(models.VesselFlowRelation).filter(
            models.VesselFlowRelation.id == relation_id,
            models.VesselFlowRelation.project_id == project_id,
        ).first()
        if not rel:
            return False
        db.delete(rel)
        db.commit()
        return True

    @staticmethod
    def get_vessel_scale_scheme(db: Session, project_id: int, vessel_id: int):
        from schemas import ScaleSchemeOut, ScaleMarkOut
        vessel = db.query(models.Vessel).filter(
            models.Vessel.id == vessel_id, models.Vessel.project_id == project_id
        ).first()
        if not vessel:
            raise ValidationError("容器不存在")
        scheme = db.query(models.ScaleScheme).filter(
            models.ScaleScheme.vessel_id == vessel_id
        ).first()
        if not scheme:
            return None
        marks = [
            ScaleMarkOut(
                id=m.id, mark_index=m.mark_index,
                target_time=m.target_time, target_water_level=m.target_water_level,
            )
            for m in scheme.marks
        ]
        return ScaleSchemeOut(id=scheme.id, vessel_id=scheme.vessel_id, version=scheme.version, created_at=scheme.created_at, marks=marks)

    @staticmethod
    def update_vessel_scale_scheme(
        db: Session, project_id: int, vessel_id: int, data: ScaleSchemeUpdate
    ):
        from schemas import ScaleSchemeOut, ScaleMarkOut
        vessel = db.query(models.Vessel).filter(
            models.Vessel.id == vessel_id, models.Vessel.project_id == project_id
        ).first()
        if not vessel:
            raise ValidationError("容器不存在")
        ValidationService.validate_scale_scheme(data, vessel.capacity)

        scheme = db.query(models.ScaleScheme).filter(
            models.ScaleScheme.vessel_id == vessel_id
        ).first()
        if scheme:
            db.query(models.ScaleMark).filter(
                models.ScaleMark.scheme_id == scheme.id
            ).delete()
            scheme.version += 1
        else:
            scheme = models.ScaleScheme(vessel_id=vessel_id, version=1)
            db.add(scheme)
            db.flush()

        new_marks = [
            models.ScaleMark(
                scheme_id=scheme.id, mark_index=m.mark_index,
                target_time=m.target_time, target_water_level=m.target_water_level,
            )
            for m in data.marks
        ]
        db.add_all(new_marks)
        db.commit()
        db.refresh(scheme)
        return MultiVesselService.get_vessel_scale_scheme(db, project_id, vessel_id)

    @staticmethod
    def create_multi_experiment(db: Session, project_id: int):
        from schemas import ExperimentOut
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")
        vessels = db.query(models.Vessel).filter(models.Vessel.project_id == project_id).all()
        if not vessels:
            raise ValidationError("请先配置多级容器结构")

        existing = db.query(models.Experiment).filter(
            models.Experiment.project_id == project_id
        ).all()
        next_round = len(existing) + 1

        exp = models.Experiment(
            project_id=project_id, round_number=next_round,
            status="recording", needs_recheck=False, is_multi_vessel=True,
        )
        db.add(exp)
        if project.status in ("ready", "configured", "draft"):
            project.status = "experimenting"
        db.commit()
        db.refresh(exp)
        return ExperimentOut(
            id=exp.id, round_number=exp.round_number, started_at=exp.started_at,
            status=exp.status, needs_recheck=exp.needs_recheck,
            is_multi_vessel=True, records=[], vessel_records=[],
        )

    @staticmethod
    def add_vessel_records(
        db: Session, project_id: int, experiment_id: int,
        data: VesselBatchRecordCreate
    ) -> list[VesselRecordOut]:
        exp = db.query(models.Experiment).filter(
            models.Experiment.id == experiment_id,
            models.Experiment.project_id == project_id,
        ).first()
        if not exp:
            raise ValidationError("实验不存在")
        if not exp.is_multi_vessel:
            raise ValidationError("此实验不是多级漏刻实验")
        if exp.status != "recording":
            raise ValidationError("只能在实验进行中录入记录")

        from sqlalchemy import func as sa_func
        existing_max_time = db.query(sa_func.max(
            models.VesselExperimentRecord.time_point
        )).filter(
            models.VesselExperimentRecord.experiment_id == experiment_id
        ).scalar()

        if existing_max_time is not None and data.time_point <= existing_max_time:
            raise ValidationError(
                f"时间节点必须递增，当前最大已录时间为 {existing_max_time} 分钟，"
                f"请输入大于 {existing_max_time} 的时间"
            )

        vessels = {v.id: v for v in db.query(models.Vessel).filter(
            models.Vessel.project_id == project_id
        ).all()}

        results = []
        for rec_data in data.records:
            vessel = vessels.get(rec_data.vessel_id)
            if not vessel:
                raise ValidationError(f"容器 {rec_data.vessel_id} 不存在")
            if rec_data.water_level > vessel.capacity:
                raise ValidationError(
                    f"容器 {vessel.name} 的记录水位 {rec_data.water_level} ml 超过容量 {vessel.capacity} ml"
                )
            existing = db.query(models.VesselExperimentRecord).filter(
                models.VesselExperimentRecord.experiment_id == experiment_id,
                models.VesselExperimentRecord.vessel_id == rec_data.vessel_id,
                models.VesselExperimentRecord.time_point == rec_data.time_point,
            ).first()
            if existing:
                raise ValidationError(
                    f"容器 {vessel.name} 在 {rec_data.time_point} 分钟已存在记录"
                )

            rec = models.VesselExperimentRecord(
                experiment_id=experiment_id,
                vessel_id=rec_data.vessel_id,
                time_point=rec_data.time_point,
                water_level=rec_data.water_level,
            )
            db.add(rec)
            db.flush()
            db.refresh(rec)
            results.append(VesselRecordOut(
                id=rec.id, vessel_id=rec.vessel_id, time_point=rec.time_point,
                water_level=rec.water_level,
            ))
        db.commit()
        return results

    @staticmethod
    def finalize_multi_experiment(db: Session, project_id: int, experiment_id: int):
        exp = db.query(models.Experiment).filter(
            models.Experiment.id == experiment_id,
            models.Experiment.project_id == project_id,
        ).first()
        if not exp:
            raise ValueError("实验不存在")
        if not exp.is_multi_vessel:
            raise ValueError("此实验不是多级漏刻实验")

        vessels = {v.id: v for v in db.query(models.Vessel).filter(
            models.Vessel.project_id == project_id
        ).all()}

        flow_relations = db.query(models.VesselFlowRelation).filter(
            models.VesselFlowRelation.project_id == project_id
        ).all()

        total_error = 0.0
        total_count = 0

        for vessel_id, vessel in vessels.items():
            scheme = db.query(models.ScaleScheme).filter(
                models.ScaleScheme.vessel_id == vessel_id
            ).first()
            marks = sorted(scheme.marks, key=lambda m: m.target_time) if scheme else []
            capacity = vessel.capacity

            records = sorted(
                [r for r in exp.vessel_records if r.vessel_id == vessel_id],
                key=lambda r: r.time_point
            )
            prev_level = vessel.initial_level or capacity
            prev_time = 0.0

            for rec in records:
                dt = rec.time_point - prev_time
                if dt > 0:
                    rec.computed_flow_rate = round((prev_level - rec.water_level) / dt, 4)
                else:
                    rec.computed_flow_rate = 0.0

                expected = _expected_water_level(rec.time_point, marks, capacity)
                if expected > 0:
                    err_pct = (rec.water_level - expected) / expected * 100.0
                else:
                    err_pct = 0.0
                rec.time_error = round(err_pct, 4)
                total_error += abs(err_pct)
                total_count += 1

                prev_level = rec.water_level
                prev_time = rec.time_point

        for vessel_id, vessel in vessels.items():
            records = [r for r in exp.vessel_records if r.vessel_id == vessel_id]
            upstream_rels = [r for r in flow_relations if r.downstream_vessel_id == vessel_id]
            upstream_ids = [r.upstream_vessel_id for r in upstream_rels]
            upstream_vessels = [vessels[uid] for uid in upstream_ids if uid in vessels]
            _compute_inflow_rate(records, vessel, upstream_vessels, upstream_rels, vessels)

        avg_error = round(total_error / total_count, 4) if total_count > 0 else 0.0
        exp.total_error = avg_error
        exp.status = "finalized"
        exp.finalized_at = exp.finalized_at or datetime.utcnow()

        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if project and project.status not in ("completed",):
            project.status = "completed"

        db.commit()
        return avg_error, total_count

    @staticmethod
    def get_multi_analysis(
        db: Session, project_id: int, experiment_id: int
    ) -> MultiVesselAnalysisOut:
        exp = db.query(models.Experiment).filter(
            models.Experiment.id == experiment_id,
            models.Experiment.project_id == project_id,
        ).first()
        if not exp:
            raise ValueError("实验不存在")
        if not exp.is_multi_vessel:
            raise ValueError("此实验不是多级漏刻实验")

        vessels = db.query(models.Vessel).filter(
            models.Vessel.project_id == project_id
        ).order_by(models.Vessel.level_index).all()
        vessel_map = {v.id: v for v in vessels}

        flow_relations = db.query(models.VesselFlowRelation).filter(
            models.VesselFlowRelation.project_id == project_id
        ).all()

        time_series: list[VesselTimeSeries] = []
        for vessel in vessels:
            records = sorted(
                [r for r in exp.vessel_records if r.vessel_id == vessel.id],
                key=lambda r: r.time_point
            )
            data_points = [
                VesselLevelDataPoint(
                    time_point=r.time_point, water_level=r.water_level,
                    computed_flow_rate=r.computed_flow_rate,
                    time_error=r.time_error,
                )
                for r in records
            ]
            time_series.append(VesselTimeSeries(
                vessel_id=vessel.id, vessel_name=vessel.name,
                level_index=vessel.level_index, role=vessel.role,
                data_points=data_points,
            ))

        inter_vessel_errors: list[InterVesselError] = []
        for rel in flow_relations:
            up_vessel = vessel_map.get(rel.upstream_vessel_id)
            down_vessel = vessel_map.get(rel.downstream_vessel_id)
            if not up_vessel or not down_vessel:
                continue

            up_records = sorted(
                [r for r in exp.vessel_records if r.vessel_id == rel.upstream_vessel_id],
                key=lambda r: r.time_point
            )
            down_records = sorted(
                [r for r in exp.vessel_records if r.vessel_id == rel.downstream_vessel_id],
                key=lambda r: r.time_point
            )
            if len(up_records) < 2 or len(down_records) < 2:
                continue

            delay_min = rel.delay_seconds / 60.0
            cumulative_err = 0.0
            cumulative_abs = 0.0

            common_times = sorted(set([r.time_point for r in up_records]) &
                                  set([r.time_point for r in down_records]))
            for t in common_times:
                up_r = next((r for r in up_records if r.time_point == t), None)
                down_r = next((r for r in down_records if r.time_point == t), None)
                if not up_r or not down_r:
                    continue
                up_flow = up_r.computed_flow_rate or 0.0
                down_inflow = down_r.inflow_rate or 0.0
                expected_flow = up_flow * rel.flow_coefficient
                actual_flow = down_inflow if down_inflow else max(0, -down_r.computed_flow_rate or 0)

                if expected_flow > 0:
                    flow_err_pct = (actual_flow - expected_flow) / expected_flow * 100.0
                else:
                    flow_err_pct = 0.0

                cumulative_err += flow_err_pct
                cumulative_abs += abs(flow_err_pct)

                inter_vessel_errors.append(InterVesselError(
                    upstream_vessel_id=rel.upstream_vessel_id,
                    upstream_vessel_name=up_vessel.name,
                    downstream_vessel_id=rel.downstream_vessel_id,
                    downstream_vessel_name=down_vessel.name,
                    time_point=t,
                    expected_flow=round(expected_flow, 4),
                    actual_flow=round(actual_flow, 4),
                    flow_error=round(actual_flow - expected_flow, 4),
                    flow_error_percent=round(flow_err_pct, 3),
                    cumulative_error=round(cumulative_abs, 3),
                    exceeded=abs(flow_err_pct) > ERROR_THRESHOLD,
                ))

        error_amplification: list[VesselErrorAmplification] = []
        prev_avg_err = 0.0
        for idx, vessel in enumerate(vessels):
            records = [r for r in exp.vessel_records if r.vessel_id == vessel.id]
            if not records:
                continue
            errors = [abs(r.time_error or 0) for r in records if r.time_error is not None]
            if not errors:
                continue
            avg_err = sum(errors) / len(errors)
            max_err = max(errors)

            if idx > 0 and prev_avg_err > 0:
                gain = avg_err / prev_avg_err
            else:
                gain = 1.0

            rel_errs = []
            for rel in flow_relations:
                if rel.downstream_vessel_id == vessel.id:
                    up_recs = [r for r in exp.vessel_records if r.vessel_id == rel.upstream_vessel_id]
                    down_recs = records
                    common_ts = sorted(set(r.time_point for r in up_recs) & set(r.time_point for r in down_recs))
                    for t in common_ts:
                        up_r = next((r for r in up_recs if r.time_point == t), None)
                        down_r = next((r for r in down_recs if r.time_point == t), None)
                        if up_r and down_r and up_r.computed_flow_rate:
                            expected = up_r.computed_flow_rate * rel.flow_coefficient
                            actual = down_r.inflow_rate or 0
                            if expected > 0:
                                rel_errs.append(abs((actual - expected) / expected * 100))

            avg_rel_err = sum(rel_errs) / len(rel_errs) if rel_errs else 0
            is_amp = (gain > 1.15 and avg_err > ERROR_THRESHOLD) or (avg_rel_err > ERROR_THRESHOLD * 1.5)

            if is_amp and gain > 1.15:
                reason = (
                    f"该级平均误差 {avg_err:.2f}% 较上一级放大 {gain:.2f} 倍，"
                    f"最大误差达 {max_err:.2f}%。"
                    f"级间流量传递误差 {avg_rel_err:.2f}%，"
                    f"可能为级间流量不稳定、孔径偏差或水位波动导致"
                )
            elif avg_rel_err > ERROR_THRESHOLD:
                reason = (
                    f"级间流量传递误差较大（平均 {avg_rel_err:.2f}%），"
                    f"建议检查上游出水孔径与下游进水匹配性"
                )
            elif avg_err > ERROR_THRESHOLD:
                reason = f"该级平均误差 {avg_err:.2f}% 超过阈值 {ERROR_THRESHOLD}%"
            else:
                reason = f"该级误差控制在合理范围内（平均 {avg_err:.2f}%）"

            error_amplification.append(VesselErrorAmplification(
                vessel_id=vessel.id, vessel_name=vessel.name,
                level_index=vessel.level_index,
                avg_error_percent=round(avg_err, 3),
                max_error_percent=round(max_err, 3),
                error_gain=round(gain, 3),
                is_amplification_stage=is_amp,
                reason=reason,
            ))
            prev_avg_err = avg_err

        scale_adjustments: list[VesselScaleAdjustment] = []
        for vessel in vessels:
            scheme = db.query(models.ScaleScheme).filter(
                models.ScaleScheme.vessel_id == vessel.id
            ).first()
            if not scheme:
                continue
            marks = sorted(scheme.marks, key=lambda m: m.target_time)
            records = sorted(
                [r for r in exp.vessel_records if r.vessel_id == vessel.id],
                key=lambda r: r.time_point
            )
            if len(records) < 2:
                continue

            capacity = vessel.capacity
            extended = [(0.0, vessel.initial_level or capacity)] + \
                       [(r.time_point, r.water_level) for r in records]

            exceeded_intervals = []
            for i in range(len(marks) - 1):
                m0, m1 = marks[i], marks[i + 1]
                t_start, t_end = m0.target_time, m1.target_time
                mid_t = (t_start + t_end) / 2.0

                actual_start = actual_end = None
                for j in range(len(extended) - 1):
                    et0, el0 = extended[j]
                    et1, el1 = extended[j + 1]
                    if et0 <= t_start <= et1:
                        actual_start = _lerp(t_start, et0, el0, et1, el1)
                    if et0 <= t_end <= et1:
                        actual_end = _lerp(t_end, et0, el0, et1, el1)
                if actual_start is None:
                    actual_start = extended[-1][1]
                if actual_end is None:
                    actual_end = extended[-1][1]

                mid_actual = _lerp(mid_t, t_start, actual_start, t_end, actual_end)
                mid_expected = _lerp(mid_t, t_start, m0.target_water_level,
                                     t_end, m1.target_water_level)
                if mid_expected > 0:
                    err_pct = (mid_actual - mid_expected) / mid_expected * 100.0
                else:
                    err_pct = 0.0
                err_abs = mid_actual - mid_expected
                if abs(err_pct) > ERROR_THRESHOLD:
                    exceeded_intervals.append((m0, m1, err_abs, err_pct, mid_t))

            seen_marks = set()
            for m0, m1, err_abs, err_pct, mid_t in exceeded_intervals:
                mark = _nearest_mark(mid_t, marks)
                if not mark or mark.mark_index in seen_marks:
                    continue
                seen_marks.add(mark.mark_index)
                direction = "下移" if err_abs > 0 else "上移"
                suggestions = round(mark.target_water_level - err_abs * 0.5, 2)
                suggestions = max(0.0, min(capacity, suggestions))
                scale_adjustments.append(VesselScaleAdjustment(
                    vessel_id=vessel.id, vessel_name=vessel.name,
                    mark_index=mark.mark_index, target_time=mark.target_time,
                    original_level=mark.target_water_level,
                    suggested_level=suggestions, direction=direction,
                    reason=(
                        f"[{vessel.name}] 刻度#{m0.mark_index}→#{m1.mark_index} 区间误差 "
                        f"{err_pct:+.2f}%，建议调整刻度 #{mark.mark_index}"
                    ),
                ))

        return MultiVesselAnalysisOut(
            experiment_id=experiment_id,
            total_vessels=len(vessels),
            time_series=time_series,
            inter_vessel_errors=inter_vessel_errors,
            error_amplification_stages=error_amplification,
            scale_adjustments=scale_adjustments,
            threshold_percent=ERROR_THRESHOLD,
        )

    @staticmethod
    def get_joint_scale_adjustment(
        db: Session, project_id: int, experiment_id: int
    ) -> JointScaleAdjustmentOut:
        """
        生成分级刻度联合调整建议。
        从最下级（计时级）开始，逆向推导每一级需要的刻度调整，
        确保整个串联系统的级联误差最小化。
        """
        analysis = MultiVesselService.get_multi_analysis(db, project_id, experiment_id)

        vessels = db.query(models.Vessel).filter(
            models.Vessel.project_id == project_id
        ).order_by(models.Vessel.level_index.desc()).all()

        flow_relations = db.query(models.VesselFlowRelation).filter(
            models.VesselFlowRelation.project_id == project_id
        ).all()

        steps: List[JointAdjustmentStep] = []
        total_expected_improvement = 0.0

        vessel_order = sorted(vessels, key=lambda v: v.level_index, reverse=True)

        for idx, vessel in enumerate(vessel_order):
            scheme = db.query(models.ScaleScheme).filter(
                models.ScaleScheme.vessel_id == vessel.id
            ).first()
            if not scheme:
                continue

            marks = sorted(scheme.marks, key=lambda m: m.target_time)
            vessel_analysis = next(
                (a for a in analysis.error_amplification_stages if a.vessel_id == vessel.id),
                None
            )
            adj_items = [
                a for a in analysis.scale_adjustments if a.vessel_id == vessel.id
            ]

            if not adj_items and not vessel_analysis:
                continue

            priority = "high" if vessel_analysis and vessel_analysis.is_amplification_stage else (
                "medium" if vessel_analysis and vessel_analysis.avg_error_percent > ERROR_THRESHOLD else "low"
            )

            impact_on_downstream = 0.0
            downstream_rels = [r for r in flow_relations if r.upstream_vessel_id == vessel.id]
            for dr in downstream_rels:
                down_amp = next(
                    (a for a in analysis.error_amplification_stages if a.vessel_id == dr.downstream_vessel_id),
                    None
                )
                if down_amp:
                    impact_on_downstream += down_amp.avg_error_percent * dr.flow_coefficient

            expected_improvement = 0.0
            if vessel_analysis:
                if priority == "high":
                    expected_improvement = vessel_analysis.avg_error_percent * 0.6
                elif priority == "medium":
                    expected_improvement = vessel_analysis.avg_error_percent * 0.4
                else:
                    expected_improvement = vessel_analysis.avg_error_percent * 0.2
            total_expected_improvement += expected_improvement

            adjustment_summary = ""
            if adj_items:
                up_count = sum(1 for a in adj_items if a.direction == "上移")
                down_count = sum(1 for a in adj_items if a.direction == "下移")
                adjustment_summary = f"需调整 {len(adj_items)} 个刻度（上移 {up_count} 个，下移 {down_count} 个）"
            else:
                adjustment_summary = "无显著超差刻度，建议微调或保持现状"

            steps.append(JointAdjustmentStep(
                step_order=idx + 1,
                vessel_id=vessel.id,
                vessel_name=vessel.name,
                level_index=vessel.level_index,
                priority=priority,
                adjustment_count=len(adj_items),
                adjustment_summary=adjustment_summary,
                current_avg_error=vessel_analysis.avg_error_percent if vessel_analysis else 0.0,
                expected_improvement=round(expected_improvement, 3),
                impact_on_downstream=round(impact_on_downstream, 3),
                details=[
                    {
                        "mark_index": a.mark_index,
                        "target_time": a.target_time,
                        "original_level": a.original_level,
                        "suggested_level": a.suggested_level,
                        "direction": a.direction,
                        "reason": a.reason,
                    }
                    for a in adj_items
                ],
                rationale=(
                    f"{'【关键环节】' if priority == 'high' else ''}"
                    f"{vessel.name}（第{vessel.level_index}级）当前平均误差 "
                    f"{vessel_analysis.avg_error_percent if vessel_analysis else 0:.2f}%。"
                    f"{adjustment_summary}。"
                    f"{'该级为误差放大环节，优先调整可显著提升整体精度' if priority == 'high' else ''}"
                ),
            ))

        overall_rationale = ""
        if steps:
            overall_rationale = (
                f"建议按从下到上（从计时级到补给级）的顺序依次调整：\n"
                + "\n".join(
                    f"  {i+1}. {s.vessel_name}：预期改善约 {s.expected_improvement:.2f}%"
                    for i, s in enumerate(steps)
                )
                + f"\n整体预期改善：约 {total_expected_improvement:.2f}%"
            )

        return JointScaleAdjustmentOut(
            experiment_id=experiment_id,
            total_vessels=len(vessels),
            adjustment_steps=steps,
            total_expected_improvement=round(total_expected_improvement, 3),
            overall_rationale=overall_rationale,
            threshold_percent=ERROR_THRESHOLD,
        )
