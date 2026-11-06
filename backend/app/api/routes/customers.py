from fastapi import APIRouter, HTTPException
from app.schemas.customer import EmailUpdate
from app.services import customer_service

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("")
def list_customers():
    return customer_service.list_customers()


@router.get("/{customer_id}")
def get_customer(customer_id: str):
    customer = customer_service.get_customer(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.patch("/{customer_id}/email")
def update_email(customer_id: str, body: EmailUpdate):
    customer = customer_service.update_email(customer_id, body.contact_email)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer