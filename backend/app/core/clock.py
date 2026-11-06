from datetime import date
from app.core.config import settings


def today():
    return date.fromisoformat(settings.today) if settings.today else date.today()