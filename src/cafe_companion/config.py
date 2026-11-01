from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# cafe-companion/ (holds .env and the default SQLite file), wherever the server is started from
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    # --- Database ---
    # Default: local SQLite file. To use Google Cloud SQL (PostgreSQL) set
    # INSTANCE_CONNECTION_NAME (project:region:instance) and the DB_* values below;
    # the app then connects through the Cloud SQL Python Connector.
    instance_connection_name: str = ""
    db_user: str = "postgres"
    db_pass: str = ""
    db_name: str = "cafe_companion"
    db_iam_auth: bool = False
    db_ip_type: str = "public"  # "public" | "private"
    # Used when INSTANCE_CONNECTION_NAME is empty. SQLite by default; can also point at
    # Cloud SQL through the Auth Proxy: postgresql+pg8000://user:pass@127.0.0.1:5432/cafe_companion
    database_url: str = "sqlite:///./cafe_companion.db"

    # --- Auth ---
    google_client_id: str = ""
    jwt_secret: str = "dev-secret-change-me"
    session_hours: int = 12

    # --- Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # --- App ---
    cors_origins: str = "http://localhost:5173"
    staff_pin: str = "1234"
    baristas: int = 2
    checkin_hours: int = 3
    # Local testing only: fill the demo cafe's room with fake guests.
    demo_guests: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
