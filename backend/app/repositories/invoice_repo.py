from app.core.database import db


def find(query):
    return list(db.invoices.find(query, {"_id": 0}).sort("invoice_number", 1))


def get(invoice_number):
    return db.invoices.find_one({"invoice_number": invoice_number}, {"_id": 0})