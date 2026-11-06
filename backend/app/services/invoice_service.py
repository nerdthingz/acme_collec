from datetime import date
from app.core.clock import today
from app.repositories import invoice_repo


def enrich(invoice, current):
    due = date.fromisoformat(invoice["due_date"])
    owed = invoice["status"] == "sent" and invoice["balance_due"] > 0
    overdue = owed and due < current
    return {
        **invoice,
        "amount_owed": invoice["balance_due"] if owed else 0.0,
        "is_overdue": overdue,
        "days_overdue": (current - due).days if overdue else 0,
    }


def list_invoices(customer_id=None, status=None, overdue=None):
    query = {}
    if customer_id:
        query["customer_id"] = customer_id
    if status:
        query["status"] = status
    current = today()
    items = [enrich(i, current) for i in invoice_repo.find(query)]
    if overdue is not None:
        items = [i for i in items if i["is_overdue"] == overdue]
    return items


def get_invoice(invoice_number):
    invoice = invoice_repo.get(invoice_number)
    return enrich(invoice, today()) if invoice else None    