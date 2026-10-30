"""FastAPI application entry point for the maintenance workflow API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.v1 import router
from app.runtime import runtime


@asynccontextmanager
async def lifespan(_: FastAPI):
    runtime.pipeline.start()
    yield
    await runtime.close()


app = FastAPI(
    title="Agentic Maintenance Workflow",
    version="0.1.0",
    description="Simulated telemetry and human-approved maintenance workflows.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "Agentic Maintenance Workflow", "docs": "/docs", "api": "/api/v1"}