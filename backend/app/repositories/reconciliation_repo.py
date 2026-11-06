from pymongo import ReturnDocument
from app.core.database import db

HIDE = {"_id": 0}


def ensure_indexes():
    db.bank_transactions.create_index("txn_id", unique=True)
    db.bank_transactions.create_index("batch_id")
    db.bank_transactions.create_index("fingerprint")


def insert_transactions(docs):
    db.bank_transactions.insert_many([dict(d) for d in docs])


def transactions_in_batch(batch_id):
    return list(db.bank_transactions.find({"batch_id": batch_id}, HIDE).sort("row", 1))


def get_transaction(txn_id):
    return db.bank_transactions.find_one({"txn_id": txn_id}, HIDE)


def approved_fingerprints(fingerprints):
    found = db.bank_transactions.find(
        {"fingerprint": {"$in": list(fingerprints)}, "review_status": "approved"},
        {"fingerprint": 1, "_id": 0},
    )
    return {d["fingerprint"] for d in found}


def transition(txn_id, allowed, fields):
    return db.bank_transactions.find_one_and_update(
        {"txn_id": txn_id, "review_status": {"$in": allowed}},
        {"$set": fields},
        projection=HIDE,
        return_document=ReturnDocument.BEFORE,
    )


def set_fields(txn_id, fields):
    db.bank_transactions.update_one({"txn_id": txn_id}, {"$set": fields})


def status_counts():
    return list(db.bank_transactions.aggregate([
        {"$group": {
            "_id": {"batch_id": "$batch_id", "status": "$review_status"},
            "count": {"$sum": 1},
            "filename": {"$first": "$filename"},
            "uploaded_at": {"$first": "$uploaded_at"},
        }},
    ]))


def get_invoice(invoice_number):
    return db.invoices.find_one({"invoice_number": invoice_number}, HIDE)


def apply_to_invoice(original, fields):
    result = db.invoices.update_one(
        {
            "invoice_number": original["invoice_number"],
            "status": "sent",
            "balance_due": original["balance_due"],
            "amount_paid": original["amount_paid"],
        },
        {"$set": fields},
    )
    return result.modified_count == 1


def restore_invoice(original):
    update = {"$set": {
        "amount_paid": original["amount_paid"],
        "balance_due": original["balance_due"],
        "status": original["status"],
    }}
    if "tds_deducted" in original:
        update["$set"]["tds_deducted"] = original["tds_deducted"]
    else:
        update["$unset"] = {"tds_deducted": ""}
    db.invoices.update_one({"invoice_number": original["invoice_number"]}, update)


def insert_payments(docs):
    db.payments.insert_many([dict(d) for d in docs])


def list_payments():
    return list(db.payments.find({}, HIDE).sort("approved_at", -1))