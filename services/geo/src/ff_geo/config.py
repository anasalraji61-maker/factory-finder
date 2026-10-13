from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_GEO_")

    port: int = 8103
    internal_token: str | None = None  # also read from FF_INTERNAL_TOKEN by the gateway layer
    default_road_factor: float = 1.3


def get_settings() -> Settings:
    return Settings()
