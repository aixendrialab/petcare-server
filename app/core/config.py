from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, field_validator
from typing import List

class Settings(BaseSettings):
    APP_NAME: str = "PetCare API"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str
    CACHE_PROVIDER: str = "memory"
    EVENT_PROVIDER: str = "memory"
    STORAGE_PROVIDER: str = "memory"
    REDIS_URL: str | None = None

    S3_ENDPOINT: str | None = None
    S3_REGION: str | None = None
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None
    S3_BUCKET: str | None = None

    CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("CORS_ORIGINS", mode="before")
    def csv(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
    class Config: env_file = ".env"

settings = Settings()
