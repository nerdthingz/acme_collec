from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import admin, agent, customers, invoices, organization, reconciliation
from app.core.config import settings
from app.core.database import db
from app.core.errors import register_error_handlers
from app.core.security import require_auth
from app.services import agent_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = agent_service.start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="AcmeCorp Collections", lifespan=lifespan)
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(agent.auth_router)
for module in (organization, customers, invoices, reconciliation, agent, admin):
    app.include_router(module.router, dependencies=[Depends(require_auth)])


@app.get("/health")
def health():
    db.command("ping")
    return {"status": "ok"}