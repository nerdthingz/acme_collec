from typing import Literal
from fastapi import APIRouter, HTTPException
from app.services import invoice_service

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("")
def list_invoices(
    customer_id: str | None = None,
    status: Literal["draft", "sent", "paid"] | None = None,
    overdue: bool | None = None,
):
    return invoice_service.list_invoices(customer_id, status, overdue)


@router.get("/{invoice_number}")
def get_invoice(invoice_number: str):
    invoice = invoice_service.get_invoice(invoice_number)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice