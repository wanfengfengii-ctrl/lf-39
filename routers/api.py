from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from database.connection import get_db
from services import ProjectService, ValidationError, AnalysisService
from schemas import (
    ProjectCreate, ClepsydraConfigUpdate, ScaleSchemeUpdate,
    ExperimentRecordCreate, ScaleMarkData,
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
