import json
from pathlib import Path
from app.core.config import settings
from app.core.database import db

COLLECTIONS = [
    "organization",
    "customers",
    "invoices",
    "conversations",
    "messages",
    "bank_transactions",
    "payments",
]


def read_json(name):
    path = Path(settings.data_dir) / name
    return json.loads(path.read_text(encoding="utf-8"))


def seed():
    for name in COLLECTIONS:
        db[name].drop()

    db.organization.insert_one(read_json("organization.json"))
    db.customers.insert_many(read_json("customers.json"))
    db.invoices.insert_many(read_json("invoices.json"))

    db.customers.create_index("customer_id", unique=True)
    db.invoices.create_index("invoice_number", unique=True)
    db.invoices.create_index("customer_id")

    return {
        "organization": db.organization.count_documents({}),
        "customers": db.customers.count_documents({}),
        "invoices": db.invoices.count_documents({}),
    }