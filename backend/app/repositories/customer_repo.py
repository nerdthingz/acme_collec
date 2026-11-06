from pymongo import ReturnDocument
from app.core.database import db


def list_all():
    return list(db.customers.find({}, {"_id": 0}).sort("customer_id", 1))


def get(customer_id):
    return db.customers.find_one({"customer_id": customer_id}, {"_id": 0})


def update_email(customer_id, email):
    return db.customers.find_one_and_update(
        {"customer_id": customer_id},
        {"$set": {"contact_email": email}},
        projection={"_id": 0},
        return_document=ReturnDocument.AFTER,
    )