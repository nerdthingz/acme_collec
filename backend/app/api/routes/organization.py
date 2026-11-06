from fastapi import APIRouter
from app.repositories import organization_repo

router = APIRouter(prefix="/api/organization", tags=["organization"])


@router.get("")
def get_organization():
    return organization_repo.get()