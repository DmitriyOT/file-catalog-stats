from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки сервиса, переопределяются переменными окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Внешнее API выдачи файлов
    api_base_url: str = "http://91.199.149.128:18001"
    candidate_id: str = "installbiz-candidate"

    # БД
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/filestats"

    # Клиент внешнего API
    request_min_interval: float = 0.3  # проактивная пауза между запросами, сек
    request_timeout: float = 30.0
    max_retries: int = 10


settings = Settings()
