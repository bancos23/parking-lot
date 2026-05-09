from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    session_idle_timeout_minutes: int = 60
    session_cookie_max_age_days: int = 7

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    model_config = {"env_file": "../.env", "extra": "ignore"}


settings = Settings()
