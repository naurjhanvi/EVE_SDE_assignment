from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://eve:eve@localhost:5432/eve"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret_key: str = "dev-only-change-me"
    access_token_expire_minutes: int = 60
    admin_email: str = ""
    admin_password: str = ""
    rate_limit_requests: int = 120
    rate_limit_auth_requests: int = 10
    rate_limit_payment_requests: int = 30
    rate_limit_window_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
