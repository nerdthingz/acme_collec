from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "acmecorp"
    today: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]
    data_dir: str = str(Path(__file__).resolve().parents[3] / "data")

    admin_username: str = "admin"
    admin_password: str = ""
    jwt_secret: str = ""
    jwt_hours: int = 8

    org_email: str = ""
    org_email_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    email_dry_run: bool = False
    imap_poll_seconds: int = 60
    auto_reminders: bool = False
    reminder_interval_hours: int = 24
    reminder_cooldown_days: int = 3

    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()