from app.repositories import customer_repo
from app.services import invoice_service


def summarize(customer, invoices):
    mine = [i for i in invoices if i["customer_id"] == customer["customer_id"]]
    overdue = [i for i in mine if i["is_overdue"]]
    return {
        **customer,
        "outstanding": round(sum(i["amount_owed"] for i in mine), 2),
        "overdue_invoices": len(overdue),
        "overdue_amount": round(sum(i["amount_owed"] for i in overdue), 2),
    }


def list_customers():
    invoices = invoice_service.list_invoices()
    return [summarize(c, invoices) for c in customer_repo.list_all()]


def get_customer(customer_id):
    customer = customer_repo.get(customer_id)
    if not customer:
        return None
    return summarize(customer, invoice_service.list_invoices(customer_id=customer_id))


def update_email(customer_id, email):
    if not customer_repo.update_email(customer_id, email):
        return None
    return get_customer(customer_id)