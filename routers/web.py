from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database.connection import get_db
from services import ProjectService

router = APIRouter()

templates = Jinja2Templates(directory="templates")


def _serialize_experiment(exp):
    return {
        "id": exp["id"] if isinstance(exp, dict) else exp.id,
        "round_number": exp.round_number,
        "status": exp.status,
        "needs_recheck": exp.needs_recheck,
        "total_error": exp.total_error,
        "records": [
            {
                "id": r.id,
                "time_point": r.time_point,
                "water_level": r.water_level,
                "computed_flow_rate": r.computed_flow_rate,
                "time_error": r.time_error,
            }
            for r in exp.records
        ],
    }


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    projects = ProjectService.list_projects(db)
    project_dicts = [p.model_dump() for p in projects]
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "projects": project_dicts},
    )


@router.get("/projects/new", response_class=HTMLResponse)
async def new_project_form(request: Request):
    return templates.TemplateResponse(
        "new_project.html",
        {"request": request},
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request, project_id: int, db: Session = Depends(get_db)
):
    project = ProjectService.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    config = ProjectService.get_config(db, project_id)
    scheme = ProjectService.get_scale_scheme(db, project_id)
    experiments = ProjectService.list_experiments(db, project_id)

    experiments_json = []
    for exp in experiments:
        experiments_json.append(exp.model_dump(mode="json"))

    return templates.TemplateResponse(
        "project_detail.html",
        {
            "request": request,
            "project": {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "researcher": project.researcher,
                "status": project.status,
                "needs_recheck": project.needs_recheck,
                "created_at": project.created_at.isoformat()
                if project.created_at else None,
            },
            "config": config.model_dump(mode="json") if config else None,
            "scheme": scheme.model_dump(mode="json") if scheme else None,
            "experiments": experiments_json,
        },
    )
