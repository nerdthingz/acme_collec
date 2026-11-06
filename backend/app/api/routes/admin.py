from fastapi import APIRouter
from app.services import seed_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/reset")
def reset_demo_data():
    return seed_service.seed()