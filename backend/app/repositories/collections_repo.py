from datetime import datetime, timezone
from app.core.database import db

HIDE = {"_id": 0}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def ensure_indexes():
    db.conversations.create_index("conversation_id", unique=True)
    db.conversations.create_index("customer_id")
    db.conversations.create_index("sender_email")
    db.messages.create_index("id", unique=True)
    db.messages.create_index("message_id", unique=True)
    db.messages.create_index("conversation_id")


def get_conversation(conversation_id):
    return db.conversations.find_one({"conversation_id": conversation_id}, HIDE)


def customer_conversation(customer_id):
    return db.conversations.find_one({"customer_id": customer_id}, HIDE)


def sender_conversation(sender_email):
    return db.conversations.find_one({"customer_id": None, "sender_email": sender_email}, HIDE)


def create_conversation(doc):
    db.conversations.insert_one(dict(doc))
    return doc


def update_conversation(conversation_id, fields=None, push=None):
    update = {}
    if fields:
        update["$set"] = fields
    if push:
        update["$push"] = push
    if update:
        db.conversations.update_one({"conversation_id": conversation_id}, update)


def list_conversations():
    return list(db.conversations.find({}, HIDE).sort("last_message_at", -1))


def add_message(doc):
    db.messages.insert_one(dict(doc))
    snippet = " ".join((doc.get("body") or "").split())[:120]
    db.conversations.update_one(
        {"conversation_id": doc["conversation_id"]},
        {"$set": {"last_message_at": doc["created_at"], "last_snippet": snippet}, "$inc": {"message_count": 1}},
    )


def has_message(message_id):
    return db.messages.count_documents({"message_id": message_id}, limit=1) > 0


def get_message(item_id):
    return db.messages.find_one({"id": item_id}, HIDE)


def update_message(item_id, fields):
    db.messages.update_one({"id": item_id}, {"$set": fields})


def messages_in(conversation_id):
    return list(db.messages.find({"conversation_id": conversation_id}, HIDE).sort("created_at", 1))


def find_by_email_ids(ids):
    ids = [i for i in ids if i]
    if not ids:
        return None
    return db.messages.find_one({"message_id": {"$in": ids}}, HIDE)


def last_reminder(customer_id):
    return db.messages.find_one({"customer_id": customer_id, "kind": "reminder"}, HIDE, sort=[("created_at", -1)])


def count_auto_answers_since(conversation_id, since_iso):
    return db.messages.count_documents(
        {"conversation_id": conversation_id, "kind": "auto_answer", "created_at": {"$gte": since_iso}}
    )


def attention_items():
    return list(db.messages.find({"attention.status": "open"}, HIDE).sort("created_at", -1))


def open_attention_count(conversation_id):
    return db.messages.count_documents({"conversation_id": conversation_id, "attention.status": "open"})