from __future__ import annotations

from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from database import models
from services import ProjectService, ValidationError, AnalysisService, MultiVesselService, RobustnessService
from schemas import (
    ProjectCreate, ClepsydraConfigUpdate, ScaleSchemeUpdate,
    ExperimentRecordCreate, ScaleMarkData,
    VesselCreate, VesselUpdate, VesselFlowRelationCreate,
    VesselBatchRecordCreate,
    PerturbationConfigUpdate,
)

router = APIRouter(prefix="/api", tags=["projects"])


def _handle_validation_error(e: ValidationError):
    return JSONResponse(
        status_code=422,
        content={"ok": False, "error": e.message},
    )


@router.post("/projects")
async def create_project(
    db: Session = Depends(get_db),
    name: Annotated[str, Form(...)] = ...,
    description: Annotated[Optional[str], Form()] = None,
    researcher: Annotated[Optional[str], Form()] = None,
):
    try:
        data = ProjectCreate(name=name, description=description, researcher=researcher)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})

    project = ProjectService.create_project(db, data)
    return RedirectResponse(url=f"/projects/{project.id}", status_code=303)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int, db: Session = Depends(get_db)):
    ok = ProjectService.delete_project(db, project_id)
    if not ok:
        raise HTTPException(status_code=404)
    return {"ok": True}


@router.post("/projects/{project_id}/config")
async def update_config(
    project_id: int,
    capacity: Annotated[float, Form(...)] = ...,
    water_inlet_type: Annotated[str, Form(...)] = ...,
    outlet_diameter: Annotated[float, Form(...)] = ...,
    target_duration: Annotated[float, Form(...)] = ...,
    db: Session = Depends(get_db),
):
    try:
        data = ClepsydraConfigUpdate(
            capacity=capacity,
            water_inlet_type=water_inlet_type,
            outlet_diameter=outlet_diameter,
            target_duration=target_duration,
        )
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})

    try:
        config, changed = ProjectService.update_config(db, project_id, data)
        if changed:
            AnalysisService.mark_finalized_needs_recheck(db, project_id)
            config = ProjectService.get_config(db, project_id)
    except ValidationError as e:
        return _handle_validation_error(e)

    return {"ok": True, "config": config.model_dump(), "params_changed": changed}


@router.post("/projects/{project_id}/scale")
async def update_scale_scheme(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
        marks_data = payload.get("marks", [])
        marks = [ScaleMarkData(**m) for m in marks_data]
        data = ScaleSchemeUpdate(marks=marks)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})

    try:
        scheme = ProjectService.update_scale_scheme(db, project_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)

    return {"ok": True, "scheme": scheme.model_dump(mode="json")}


@router.get("/projects/{project_id}/experiments/new")
async def create_experiment(project_id: int, db: Session = Depends(get_db)):
    try:
        exp = ProjectService.create_experiment(db, project_id)
    except ValidationError as e:
        return RedirectResponse(
            url=f"/projects/{project_id}?error={e.message}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/projects/{project_id}?exp={exp.id}",
        status_code=303,
    )


@router.post("/projects/{project_id}/experiments/{exp_id}/records")
async def add_record(
    project_id: int,
    exp_id: int,
    time_point: Annotated[float, Form(...)] = ...,
    water_level: Annotated[float, Form(...)] = ...,
    db: Session = Depends(get_db),
):
    try:
        data = ExperimentRecordCreate(time_point=time_point, water_level=water_level)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})

    try:
        record = ProjectService.add_record(db, project_id, exp_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)

    return {"ok": True, "record": record.model_dump()}


@router.delete("/projects/{project_id}/experiments/{exp_id}/records/{record_id}")
async def delete_record(
    project_id: int, exp_id: int, record_id: int,
    db: Session = Depends(get_db),
):
    ok = ProjectService.delete_record(db, project_id, exp_id, record_id)
    if not ok:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "无法删除该记录（实验已完成或记录不存在）"},
        )
    return {"ok": True}


@router.post("/projects/{project_id}/experiments/{exp_id}/finalize")
async def finalize_experiment(
    project_id: int, exp_id: int,
    db: Session = Depends(get_db),
):
    try:
        avg_error, count, records = AnalysisService.compute_records(db, project_id, exp_id)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})

    analysis = AnalysisService.get_analysis(db, project_id, exp_id)
    records_out = [
        {
            "id": r.id,
            "time_point": r.time_point,
            "water_level": r.water_level,
            "computed_flow_rate": r.computed_flow_rate,
            "time_error": r.time_error,
        }
        for r in records
    ]
    project = ProjectService.get_project(db, project_id)
    return {
        "ok": True,
        "avg_error": avg_error,
        "record_count": count,
        "records": records_out,
        "project_status": project.status if project else None,
        "analysis": analysis.model_dump(mode="json"),
    }


@router.get("/projects/{project_id}/analysis")
async def get_analysis(
    project_id: int,
    exp_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    experiments = ProjectService.list_experiments(db, project_id)
    if exp_id is None:
        if experiments:
            exp_id = experiments[-1].id
        else:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "error": "暂无实验数据"},
            )

    try:
        analysis = AnalysisService.get_analysis(db, project_id, exp_id)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})

    return {"ok": True, "analysis": analysis.model_dump(mode="json")}


@router.post("/projects/{project_id}/experiments/{exp_id}/recheck")
async def toggle_recheck(
    project_id: int, exp_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
        recheck = bool(payload.get("needs_recheck", True))
        ProjectService.toggle_recheck(db, project_id, exp_id, recheck)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True}


# ============ 多级漏刻 API ============

@router.get("/projects/{project_id}/multi-vessel")
async def get_multi_vessel_config(project_id: int, db: Session = Depends(get_db)):
    try:
        cfg = MultiVesselService.get_config(db, project_id)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "config": cfg.model_dump(mode="json")}


@router.post("/projects/{project_id}/multi-vessel/enable")
async def enable_multi_vessel(
    project_id: int, request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        enabled = bool(payload.get("enabled", True))
        MultiVesselService.enable_multi_vessel(db, project_id, enabled)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True}


@router.post("/projects/{project_id}/multi-vessel/vessels")
async def add_vessel(
    project_id: int, request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        data = VesselCreate(**payload)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        vessel = MultiVesselService.add_vessel(db, project_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "vessel": vessel.model_dump()}


@router.put("/projects/{project_id}/multi-vessel/vessels/{vessel_id}")
async def update_vessel(
    project_id: int, vessel_id: int,
    request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        data = VesselUpdate(**payload)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        vessel = MultiVesselService.update_vessel(db, project_id, vessel_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "vessel": vessel.model_dump()}


@router.delete("/projects/{project_id}/multi-vessel/vessels/{vessel_id}")
async def delete_vessel(project_id: int, vessel_id: int, db: Session = Depends(get_db)):
    ok = MultiVesselService.delete_vessel(db, project_id, vessel_id)
    if not ok:
        return JSONResponse(status_code=422, content={"ok": False, "error": "容器不存在"})
    return {"ok": True}


@router.post("/projects/{project_id}/multi-vessel/relations")
async def add_flow_relation(
    project_id: int, request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        data = VesselFlowRelationCreate(**payload)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        rel = MultiVesselService.add_flow_relation(db, project_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "relation": rel.model_dump()}


@router.delete("/projects/{project_id}/multi-vessel/relations/{relation_id}")
async def delete_flow_relation(
    project_id: int, relation_id: int, db: Session = Depends(get_db)
):
    ok = MultiVesselService.delete_flow_relation(db, project_id, relation_id)
    if not ok:
        return JSONResponse(status_code=422, content={"ok": False, "error": "关联不存在"})
    return {"ok": True}


@router.get("/projects/{project_id}/multi-vessel/vessels/{vessel_id}/scale")
async def get_vessel_scale(project_id: int, vessel_id: int, db: Session = Depends(get_db)):
    try:
        scheme = MultiVesselService.get_vessel_scale_scheme(db, project_id, vessel_id)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "scheme": scheme.model_dump(mode="json") if scheme else None}


@router.post("/projects/{project_id}/multi-vessel/vessels/{vessel_id}/scale")
async def update_vessel_scale(
    project_id: int, vessel_id: int,
    request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        marks_data = payload.get("marks", [])
        marks = [ScaleMarkData(**m) for m in marks_data]
        data = ScaleSchemeUpdate(marks=marks)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        scheme = MultiVesselService.update_vessel_scale_scheme(db, project_id, vessel_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "scheme": scheme.model_dump(mode="json") if scheme else None}


@router.get("/projects/{project_id}/multi-vessel/experiments/new")
async def create_multi_experiment(project_id: int, db: Session = Depends(get_db)):
    try:
        exp = MultiVesselService.create_multi_experiment(db, project_id)
    except ValidationError as e:
        return RedirectResponse(
            url=f"/projects/{project_id}?error={e.message}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/projects/{project_id}?exp={exp.id}&multi=1",
        status_code=303,
    )


@router.post("/projects/{project_id}/multi-vessel/experiments")
async def create_multi_experiment_post(
    project_id: int, db: Session = Depends(get_db)
):
    try:
        exp = MultiVesselService.create_multi_experiment(db, project_id)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "experiment": exp.model_dump(mode="json")}


@router.post("/projects/{project_id}/multi-vessel/experiments/{exp_id}/records")
async def add_multi_vessel_records(
    project_id: int, exp_id: int,
    request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        data = VesselBatchRecordCreate(**payload)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        records = MultiVesselService.add_vessel_records(db, project_id, exp_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "records": [r.model_dump() for r in records]}


@router.post("/projects/{project_id}/multi-vessel/experiments/{exp_id}/finalize")
async def finalize_multi_experiment(
    project_id: int, exp_id: int, db: Session = Depends(get_db)
):
    try:
        avg_error, count = MultiVesselService.finalize_multi_experiment(db, project_id, exp_id)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        analysis = MultiVesselService.get_multi_analysis(db, project_id, exp_id)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    project = ProjectService.get_project(db, project_id)
    exp = ProjectService.get_experiment(db, exp_id)
    vessel_records = []
    if exp:
        from schemas import VesselRecordOut
        vessel_records = [
            VesselRecordOut(
                id=r.id, vessel_id=r.vessel_id,
                time_point=r.time_point, water_level=r.water_level,
                computed_flow_rate=r.computed_flow_rate,
                time_error=r.time_error, inflow_rate=r.inflow_rate,
            ).model_dump()
            for r in exp.vessel_records
        ]
    vessel_scale_schemes = []
    vessels = db.query(models.Vessel).filter(models.Vessel.project_id == project_id).all()
    for v in vessels:
        scheme = MultiVesselService.get_vessel_scale_scheme(db, project_id, v.id)
        if scheme:
            vessel_scale_schemes.append(scheme.model_dump(mode="json"))
    return {
        "ok": True,
        "avg_error": avg_error,
        "record_count": count,
        "project_status": project.status if project else None,
        "analysis": analysis.model_dump(mode="json"),
        "vessel_records": vessel_records,
        "vessel_scale_schemes": vessel_scale_schemes,
    }


@router.get("/projects/{project_id}/multi-vessel/analysis")
async def get_multi_analysis(
    project_id: int,
    exp_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    experiments = ProjectService.list_experiments(db, project_id)
    multi_exps = [e for e in experiments if getattr(e, 'is_multi_vessel', False)]
    if exp_id is None:
        if multi_exps:
            exp_id = multi_exps[-1].id
        else:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "error": "暂无多级漏刻实验数据"},
            )
    try:
        analysis = MultiVesselService.get_multi_analysis(db, project_id, exp_id)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    vessel_scale_schemes = []
    vessels = db.query(models.Vessel).filter(models.Vessel.project_id == project_id).all()
    for v in vessels:
        scheme = MultiVesselService.get_vessel_scale_scheme(db, project_id, v.id)
        if scheme:
            vessel_scale_schemes.append(scheme.model_dump(mode="json"))
    return {"ok": True, "analysis": analysis.model_dump(mode="json"), "vessel_scale_schemes": vessel_scale_schemes}


@router.get("/projects/{project_id}/multi-vessel/joint-adjustment")
async def get_joint_scale_adjustment(
    project_id: int,
    exp_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    experiments = ProjectService.list_experiments(db, project_id)
    multi_exps = [e for e in experiments if getattr(e, 'is_multi_vessel', False)]
    if exp_id is None:
        if multi_exps:
            exp_id = multi_exps[-1].id
        else:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "error": "暂无多级漏刻实验数据"},
            )
    try:
        adjustment = MultiVesselService.get_joint_scale_adjustment(db, project_id, exp_id)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    return {"ok": True, "adjustment": adjustment.model_dump(mode="json")}


# ============ 环境扰动模拟与稳健性评估 API ============

@router.get("/projects/{project_id}/robustness/config")
async def get_perturbation_config(project_id: int, db: Session = Depends(get_db)):
    try:
        cfg = RobustnessService.get_config(db, project_id)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "config": cfg.model_dump(mode="json")}


@router.post("/projects/{project_id}/robustness/config")
async def update_perturbation_config(
    project_id: int, request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        data = PerturbationConfigUpdate(**payload)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        cfg = RobustnessService.update_config(db, project_id, data)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "config": cfg.model_dump(mode="json")}


@router.post("/projects/{project_id}/robustness/simulate")
async def run_robustness_simulation(
    project_id: int, request: Request, db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
        is_multi_vessel = bool(payload.get("is_multi_vessel", False))
        scenario_count = payload.get("scenario_count")
        if scenario_count is not None:
            scenario_count = int(scenario_count)
    except Exception as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    try:
        result = RobustnessService.run_batch_simulation(
            db, project_id, is_multi_vessel, scenario_count
        )
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": result.ok, "result": result.model_dump()}


@router.get("/projects/{project_id}/robustness/scenarios")
async def list_simulation_scenarios(
    project_id: int,
    is_multi_vessel: Optional[bool] = False,
    db: Session = Depends(get_db),
):
    scenarios = RobustnessService.list_scenarios(db, project_id, bool(is_multi_vessel))
    return {"ok": True, "scenarios": [s.model_dump(mode="json") for s in scenarios]}


@router.get("/robustness/scenarios/{scenario_id}")
async def get_simulation_scenario_detail(scenario_id: int, db: Session = Depends(get_db)):
    try:
        detail = RobustnessService.get_scenario_detail(db, scenario_id)
    except ValidationError as e:
        return _handle_validation_error(e)
    return {"ok": True, "detail": detail.model_dump(mode="json")}


@router.get("/projects/{project_id}/robustness/assessment")
async def get_robustness_assessment(
    project_id: int,
    is_multi_vessel: Optional[bool] = False,
    db: Session = Depends(get_db),
):
    assessment = RobustnessService.get_assessment(db, project_id, bool(is_multi_vessel))
    if assessment is None:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "尚未运行模拟，请先执行批量模拟"},
        )
    return {"ok": True, "assessment": assessment.model_dump(mode="json")}
