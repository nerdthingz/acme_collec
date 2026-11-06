from app.core.database import db


def get():
    return db.organization.find_one({}, {"_id": 0})