from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "i2b2 ML UI"
    api_prefix: str = "/api"

    host: str = "127.0.0.1"
    port: int = 8003
    reload: bool = True

    # Origins allowed to call the API (the Vite dev server by default).
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    container: str = "i2b2-etl"
    db_container: str = "i2b2-pg"

    etl_url: str = "http://127.0.0.1:5001"
    etl_project: str = "Demo"
    etl_auth: str = "Basic ZGVtb1xkZW1vOkV0bEAyMDIx" # Base 64 for demo\demo:Etl@2021

    etl_app_dir: str = "/usr/src/app"
    etl_venv: str = "/usr/src/app/.venv/bin/activate"

    @property
    def etl_headers(self) -> dict[str, str]:
        return {
            "X-Project-Name": self.etl_project,
            "authorization": self.etl_auth,
            "Content-Type": "application/json",
            "accept": "application/json",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
