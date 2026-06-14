import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database.connection import init_db
from routers import web_router, api_router

BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="古代漏刻复原与校准研究系统",
    description="博物馆研究团队用于复原并校准不同结构古代漏刻的注水实验分析平台",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(web_router)
app.include_router(api_router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "clepsydra-research"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
