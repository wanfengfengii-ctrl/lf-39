from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from database import models
from schemas import (
    ProjectCreate, ProjectOut, ProjectListItem,
    ClepsydraConfigUpdate, ClepsydraConfigOut,
    ScaleSchemeUpdate, ScaleSchemeOut, ScaleMarkOut,
    ExperimentOut, ExperimentRecordCreate, ExperimentRecordOut,
    VesselRecordOut,
)
from services.validation_service import ValidationService, ValidationError


class ProjectService:

    @staticmethod
    def list_projects(db: Session) -> list[ProjectListItem]:
        projects = db.query(models.Project).order_by(models.Project.created_at.desc()).all()
        result = []
        for p in projects:
            exp_count = len(p.experiments)
            last_round = p.experiments[-1].round_number if p.experiments else None
            item = ProjectListItem(
                id=p.id,
                name=p.name,
                description=p.description,
                researcher=p.researcher,
                created_at=p.created_at,
                status=p.status,
                needs_recheck=p.needs_recheck,
                is_multi_vessel=p.is_multi_vessel,
                experiment_count=exp_count,
                last_round=last_round,
            )
            result.append(item)
        return result

    @staticmethod
    def create_project(db: Session, data: ProjectCreate) -> ProjectOut:
        project = models.Project(
            name=data.name,
            description=data.description,
            researcher=data.researcher,
            status="draft",
            needs_recheck=False,
        )
        db.add(project)
        db.flush()

        config = models.ClepsydraConfig(
            project_id=project.id,
            capacity=1000.0,
            water_inlet_type="gravity",
            outlet_diameter=3.0,
            target_duration=60.0,
            params_changed=False,
        )
        db.add(config)

        scheme = models.ScaleScheme(project_id=project.id, version=1)
        db.add(scheme)
        db.flush()

        default_marks = []
        for i in range(11):
            t = round(config.target_duration * i / 10, 2)
            level = round(config.capacity * (1 - i / 10), 2) if i > 0 else config.capacity
            default_marks.append(models.ScaleMark(
                scheme_id=scheme.id,
                mark_index=i,
                target_time=t,
                target_water_level=level,
            ))
        db.add_all(default_marks)

        db.commit()
        db.refresh(project)

        return ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            researcher=project.researcher,
            created_at=project.created_at,
            status=project.status,
            needs_recheck=project.needs_recheck,
            is_multi_vessel=project.is_multi_vessel,
            experiment_count=0,
        )

    @staticmethod
    def get_project(db: Session, project_id: int) -> Optional[models.Project]:
        return db.query(models.Project).filter(models.Project.id == project_id).first()

    @staticmethod
    def delete_project(db: Session, project_id: int) -> bool:
        project = ProjectService.get_project(db, project_id)
        if not project:
            return False
        db.delete(project)
        db.commit()
        return True

    @staticmethod
    def get_config(db: Session, project_id: int) -> Optional[ClepsydraConfigOut]:
        cfg = (
            db.query(models.ClepsydraConfig)
            .filter(models.ClepsydraConfig.project_id == project_id)
            .first()
        )
        if not cfg:
            return None
        return ClepsydraConfigOut(
            id=cfg.id,
            capacity=cfg.capacity,
            water_inlet_type=cfg.water_inlet_type,
            outlet_diameter=cfg.outlet_diameter,
            target_duration=cfg.target_duration,
            params_changed=cfg.params_changed,
        )

    @staticmethod
    def update_config(
        db: Session, project_id: int, data: ClepsydraConfigUpdate
    ) -> tuple[ClepsydraConfigOut, bool]:
        cfg = (
            db.query(models.ClepsydraConfig)
            .filter(models.ClepsydraConfig.project_id == project_id)
            .first()
        )
        project = ProjectService.get_project(db, project_id)
        if not cfg or not project:
            raise ValidationError("项目或配置不存在")

        changed = (
            cfg.capacity != data.capacity
            or cfg.water_inlet_type != data.water_inlet_type
            or cfg.outlet_diameter != data.outlet_diameter
            or cfg.target_duration != data.target_duration
        )

        cfg.capacity = data.capacity
        cfg.water_inlet_type = data.water_inlet_type
        cfg.outlet_diameter = data.outlet_diameter
        cfg.target_duration = data.target_duration
        cfg.params_changed = changed or cfg.params_changed

        if changed:
            experiments = (
                db.query(models.Experiment)
                .filter(models.Experiment.project_id == project_id)
                .all()
            )
            for exp in experiments:
                if exp.status == "finalized":
                    exp.needs_recheck = True
            project.needs_recheck = any(e.needs_recheck for e in experiments)

        if project.status == "draft":
            project.status = "configured"

        db.commit()
        db.refresh(cfg)
        return ClepsydraConfigOut(
            id=cfg.id,
            capacity=cfg.capacity,
            water_inlet_type=cfg.water_inlet_type,
            outlet_diameter=cfg.outlet_diameter,
            target_duration=cfg.target_duration,
            params_changed=cfg.params_changed,
        ), changed

    @staticmethod
    def get_scale_scheme(db: Session, project_id: int) -> Optional[ScaleSchemeOut]:
        scheme = (
            db.query(models.ScaleScheme)
            .filter(models.ScaleScheme.project_id == project_id)
            .first()
        )
        if not scheme:
            return None
        marks = [
            ScaleMarkOut(
                id=m.id,
                mark_index=m.mark_index,
                target_time=m.target_time,
                target_water_level=m.target_water_level,
            )
            for m in scheme.marks
        ]
        return ScaleSchemeOut(
            id=scheme.id,
            version=scheme.version,
            created_at=scheme.created_at,
            marks=marks,
        )

    @staticmethod
    def update_scale_scheme(
        db: Session, project_id: int, data: ScaleSchemeUpdate
    ) -> ScaleSchemeOut:
        cfg = ProjectService.get_config(db, project_id)
        if not cfg:
            raise ValidationError("请先配置漏壶结构参数")

        ValidationService.validate_scale_scheme(data, cfg.capacity)

        scheme = (
            db.query(models.ScaleScheme)
            .filter(models.ScaleScheme.project_id == project_id)
            .first()
        )
        project = ProjectService.get_project(db, project_id)

        if scheme:
            db.query(models.ScaleMark).filter(
                models.ScaleMark.scheme_id == scheme.id
            ).delete()
            scheme.version += 1
        else:
            scheme = models.ScaleScheme(project_id=project_id, version=1)
            db.add(scheme)
            db.flush()

        new_marks = [
            models.ScaleMark(
                scheme_id=scheme.id,
                mark_index=m.mark_index,
                target_time=m.target_time,
                target_water_level=m.target_water_level,
            )
            for m in data.marks
        ]
        db.add_all(new_marks)

        if project and project.status == "configured":
            project.status = "ready"

        db.commit()
        db.refresh(scheme)
        return ProjectService.get_scale_scheme(db, project_id)

    @staticmethod
    def list_experiments(db: Session, project_id: int) -> list[ExperimentOut]:
        exps = (
            db.query(models.Experiment)
            .filter(models.Experiment.project_id == project_id)
            .order_by(models.Experiment.round_number)
            .all()
        )
        result = []
        for exp in exps:
            records = [
                ExperimentRecordOut(
                    id=r.id,
                    time_point=r.time_point,
                    water_level=r.water_level,
                    computed_flow_rate=r.computed_flow_rate,
                    time_error=r.time_error,
                )
                for r in exp.records
            ]
            vessel_records = [
                VesselRecordOut(
                    id=r.id,
                    vessel_id=r.vessel_id,
                    time_point=r.time_point,
                    water_level=r.water_level,
                    computed_flow_rate=r.computed_flow_rate,
                    time_error=r.time_error,
                    inflow_rate=r.inflow_rate,
                )
                for r in exp.vessel_records
            ]
            result.append(ExperimentOut(
                id=exp.id,
                round_number=exp.round_number,
                started_at=exp.started_at,
                finalized_at=exp.finalized_at,
                status=exp.status,
                needs_recheck=exp.needs_recheck,
                total_error=exp.total_error,
                is_multi_vessel=getattr(exp, 'is_multi_vessel', False),
                records=records,
                vessel_records=vessel_records,
            ))
        return result

    @staticmethod
    def get_experiment(db: Session, exp_id: int) -> Optional[models.Experiment]:
        return db.query(models.Experiment).filter(models.Experiment.id == exp_id).first()

    @staticmethod
    def create_experiment(db: Session, project_id: int) -> ExperimentOut:
        project = ProjectService.get_project(db, project_id)
        if not project:
            raise ValidationError("项目不存在")
        cfg = ProjectService.get_config(db, project_id)
        if not cfg:
            raise ValidationError("请先配置漏壶结构参数")

        existing = (
            db.query(models.Experiment)
            .filter(models.Experiment.project_id == project_id)
            .all()
        )
        next_round = len(existing) + 1

        exp = models.Experiment(
            project_id=project_id,
            round_number=next_round,
            status="recording",
            needs_recheck=False,
        )
        db.add(exp)

        if project.status in ("ready", "configured"):
            project.status = "experimenting"

        db.commit()
        db.refresh(exp)
        return ExperimentOut(
            id=exp.id,
            round_number=exp.round_number,
            started_at=exp.started_at,
            status=exp.status,
            needs_recheck=exp.needs_recheck,
            records=[],
        )

    @staticmethod
    def add_record(
        db: Session, project_id: int, experiment_id: int, data: ExperimentRecordCreate
    ) -> ExperimentRecordOut:
        exp = ProjectService.get_experiment(db, experiment_id)
        if not exp or exp.project_id != project_id:
            raise ValidationError("实验不存在")
        if exp.status != "recording":
            raise ValidationError("只能在实验进行中录入记录")

        cfg = ProjectService.get_config(db, project_id)
        ValidationService.validate_record(db, experiment_id, data, cfg.capacity)

        record = models.ExperimentRecord(
            experiment_id=experiment_id,
            time_point=data.time_point,
            water_level=data.water_level,
        )
        db.add(record)
        db.flush()
        db.commit()
        db.refresh(record)

        return ExperimentRecordOut(
            id=record.id,
            time_point=record.time_point,
            water_level=record.water_level,
        )

    @staticmethod
    def delete_record(
        db: Session, project_id: int, experiment_id: int, record_id: int
    ) -> bool:
        exp = ProjectService.get_experiment(db, experiment_id)
        if not exp or exp.project_id != project_id:
            return False
        if exp.status != "recording":
            return False
        rec = (
            db.query(models.ExperimentRecord)
            .filter(
                models.ExperimentRecord.id == record_id,
                models.ExperimentRecord.experiment_id == experiment_id,
            )
            .first()
        )
        if not rec:
            return False
        db.delete(rec)
        db.commit()
        return True

    @staticmethod
    def toggle_recheck(
        db: Session, project_id: int, experiment_id: int, recheck: bool
    ) -> None:
        exp = ProjectService.get_experiment(db, experiment_id)
        if not exp or exp.project_id != project_id:
            raise ValidationError("实验不存在")
        exp.needs_recheck = recheck
        project = ProjectService.get_project(db, project_id)
        if project:
            any_recheck = any(
                e.needs_recheck for e in project.experiments
            )
            project.needs_recheck = any_recheck
            cfg = (
                db.query(models.ClepsydraConfig)
                .filter(models.ClepsydraConfig.project_id == project_id)
                .first()
            )
            if cfg and not recheck:
                still_need = any(
                    e.needs_recheck for e in project.experiments
                )
                if not still_need:
                    cfg.params_changed = False
        db.commit()
