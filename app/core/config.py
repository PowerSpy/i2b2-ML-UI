import base64
from functools import lru_cache
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

APP_NAME = "i2b2 ML UI"
API_PREFIX = "/api"
CONFIG_FILE = Path(__file__).resolve().parents[2] / "config.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        yaml_file=CONFIG_FILE,
        yaml_file_encoding="utf-8",
    )

    host: str = "127.0.0.1"
    port: int = 8003
    reload: bool = True

    # Origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    container: str = "i2b2-etl"
    db_container: str = "i2b2-pg"

    db_user: str = "i2b2"
    db_name: str = "i2b2"
    db_schema: str = "i2b2demodata"

    etl_url: str = "http://127.0.0.1:5001"
    etl_project: str = "Demo"
    etl_user: str = ""
    etl_password: str = ""

    etl_app_dir: str = "/usr/src/app"
    etl_venv: str = "/usr/src/app/.venv/bin/activate"

    i2b2_project: str = "demo"
    i2b2_user: str = "demo"

    ml_root: str = "/ML"
    ml_time_buffer: int = 0
    ml_sample_size_limit: int = 100_000
    ml_test_size: float = 0.5
    ml_random_seed: float = 0.42

    @property
    def etl_auth(self) -> str:
        raw = f"{self.etl_user}:{self.etl_password}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    @property
    def etl_headers(self) -> dict[str, str]:
        return {
            "X-Project-Name": self.etl_project,
            "authorization": self.etl_auth,
            "Content-Type": "application/json",
            "accept": "application/json",
        }

    @property
    def psql(self) -> str:
        return f"psql -U {self.db_user} -d {self.db_name}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
