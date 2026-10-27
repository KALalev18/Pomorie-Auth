"""Runtime configuration from environment variables (see .env.example)."""

from __future__ import annotations

from functools import cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 55432
    postgres_user: str = "pomorie"
    postgres_password: str = "pomorie"
    postgres_db: str = "pomorie"

    # Read-only login used by the dashboard (member of analytics_reader).
    dashboard_db_user: str = "dashboard"
    dashboard_db_password: str = "dashboard-local"

    kafka_bootstrap: str = "localhost:19092"
    reports_topic: str = "reports.submitted.v1"
    outcomes_topic: str = "authority.outcomes.v1"

    s3_endpoint: str = "http://localhost:8333"
    s3_access_key: str = "pomorie-local"
    s3_secret_key: str = "pomorie-local-secret"
    s3_bucket: str = "pomorie-photos"

    # Key for HMAC pseudonyms (licence plates, analytics reporter ids). In a real
    # deployment this lives in a secrets manager and is rotated; here it is a demo value.
    pseudonym_key: str = "local-demo-pseudonym-key"

    # Shared token for the manual-review endpoints. A real deployment would use the
    # municipality's identity provider (OIDC) with a reviewer role instead.
    reviewer_token: str = "local-demo-reviewer-token"

    @property
    def dashboard_dsn(self) -> str:
        return (
            f"postgresql://{self.dashboard_db_user}:{self.dashboard_db_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@cache
def get_settings() -> Settings:
    return Settings()
