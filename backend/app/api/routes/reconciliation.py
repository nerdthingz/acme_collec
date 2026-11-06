from pathlib import Path
from typing import Annotated, Literal
from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field, StringConstraints
from app.core.errors import AppError
from app.services import reconciliation_service as service

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])

MAX_BYTES = 1_000_000
InvoiceNumber = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9-]{1,30}$")]


class ApproveBody(BaseModel):
    invoice_numbers: list[InvoiceNumber] | None = Field(default=None, max_length=10)
    action: Literal["close_tds", "leave_open"] | None = None


class RejectBody(BaseModel):
    note: str | None = Field(default=None, max_length=200)


@router.post("/upload")
def upload_statement(file: UploadFile = File(...)):
    name = Path(file.filename or "").name[:100]
    if not name.lower().endswith(".csv"):
        raise AppError("Upload a .csv file")
    raw = file.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise AppError("The file is larger than 1 MB", 413)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError("The file must be UTF-8 text") from None
    return service.upload_statement(name, text)


@router.get("/batches")
def list_batches():
    return service.list_batches()


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str):
    return service.get_batch(batch_id)


@router.post("/transactions/{txn_id}/approve")
def approve(txn_id: str, body: ApproveBody = ApproveBody()):
    return service.approve(txn_id, body.invoice_numbers, body.action)


@router.post("/transactions/{txn_id}/reject")
def reject(txn_id: str, body: RejectBody = RejectBody()):
    return service.reject(txn_id, body.note)


@router.get("/payments")
def list_payments():
    return service.list_payments()